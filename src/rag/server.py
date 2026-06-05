"""FastAPI server with search, index, and status routes."""

from __future__ import annotations

import asyncio
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from rag.config import get_or_create_token, get_settings, reload_settings
from rag.core.embedder import HybridEmbedder
from rag.core.jobs import load_jobs, prune_jobs, save_job
from rag.core.vectorstore import QdrantVectorStore

logger = structlog.get_logger()

MAX_QUERY_LENGTH = 2000
MAX_TOP_K = 200


# --- Request/Response Models with Validation ---


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=MAX_QUERY_LENGTH)
    top_k: int | None = Field(None, ge=1, le=MAX_TOP_K)
    filters: dict[str, Any] | None = None
    repo: str | None = None
    # ``rerank`` is kept for back-compat with existing clients but is
    # ignored — the cross-encoder reranker was removed alongside FastEmbed.
    rerank: bool = True


class SearchResultItem(BaseModel):
    file_path: str
    name: str
    parent_name: str
    chunk_type: str
    language: str
    lines: str
    code: str
    score: float
    matched_queries: list[int] = []
    citation: str = ""  # Human-readable source reference


class SearchPlanInfo(BaseModel):
    strategy: str
    queries: list[str]
    filters: dict[str, Any] = {}


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    query: str
    plan: SearchPlanInfo | None = None
    total: int
    latency_ms: float


class EnumerateRequest(BaseModel):
    """Exhaustive metadata enumeration via Qdrant scroll. No vector search.
    Matches payload filters directly and pages through ALL results up to limit."""
    filters: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(500, ge=1, le=10000)
    fields: list[str] = Field(
        default_factory=lambda: [
            "file_path",
            "name",
            "parent_name",
            "language",
            "chunk_type",
            "start_line",
            "end_line",
        ]
    )


class EnumerateResponse(BaseModel):
    count: int
    filters: dict[str, Any]
    results: list[dict[str, Any]]
    truncated: bool


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=MAX_QUERY_LENGTH)
    top_k: int = Field(8, ge=1, le=20)
    repo: str | None = None  # optional file_path prefix filter
    max_chunk_chars: int = Field(1200, ge=200, le=4000)


class Citation(BaseModel):
    file_path: str
    lines: str
    name: str
    score: float


class AskResponse(BaseModel):
    question: str
    answer: str
    citations: list[Citation]
    model: str
    retrieval_ms: float
    generation_ms: float
    latency_ms: float


class IndexRequest(BaseModel):
    repo_path: str = Field(..., min_length=1)
    full: bool = False
    languages: list[str] | None = None
    collection: str | None = None

    @field_validator("repo_path")
    @classmethod
    def validate_repo_path(cls, v: str) -> str:
        p = Path(v).resolve()
        if not p.exists():
            raise ValueError(f"Path does not exist: {v}")
        if not p.is_dir():
            raise ValueError(f"Path is not a directory: {v}")
        # Block path traversal — must be absolute and real
        if ".." in p.parts:
            raise ValueError("Path traversal not allowed")
        return str(p)


class IndexResponse(BaseModel):
    files_processed: int
    chunks_indexed: int
    files_skipped: int
    files_deleted: int
    errors: list[str]


class ReloadRequest(BaseModel):
    force: bool = False


class ReloadResponse(BaseModel):
    reloaded: bool
    embedder_reinitialized: bool
    # Always False — reranker was removed but the field is kept for
    # response-schema back-compat with existing CLI clients.
    reranker_reinitialized: bool = False
    detail: str = ""


class HealthResponse(BaseModel):
    status: str
    components: dict[str, str]


class StatusResponse(BaseModel):
    status: str
    embedder_provider: str
    embedder_model: str
    # ``reranker_*`` fields are vestigial — reranker was removed but the
    # response schema is preserved so older clients keep parsing.
    reranker_model: str = "disabled"
    reranker_enabled: bool = False
    collections: list[dict[str, Any]]
    uptime_seconds: float
    files_indexed: int = 0
    embedder_warm_ms: float | None = None
    restart_count: int = 0
    gen_model: str = ""
    gen_ctx_size: int | None = None


class ErrorResponse(BaseModel):
    error: str
    code: str
    detail: str | None = None


# --- Shared State ---

_state: dict[str, Any] = {}


def get_reranker():
    return _state.get("reranker")


def get_vectorstore() -> QdrantVectorStore:
    return _state["vectorstore"]


_EVENT_RING_MAX = 500


def _push_event(event: str, **fields: Any) -> None:
    """Append a structured event to the bounded ring buffer for TUI logs tail."""
    ring = _state.get("events")
    if ring is None:
        return
    entry = {"ts": time.time(), "event": event, **fields}
    ring.append(entry)
    # Trim
    if len(ring) > _EVENT_RING_MAX:
        del ring[: len(ring) - _EVENT_RING_MAX]


def _push_recent_file(path: str, chunks: int) -> None:
    ring = _state.get("recent_indexed_files")
    if ring is None:
        return
    ring.append({"ts": time.time(), "path": path, "chunks": chunks})
    if len(ring) > 100:
        del ring[: len(ring) - 100]


# --- Auth dependency ---


def _extract_bearer(request: Request) -> str | None:
    auth = request.headers.get("Authorization") or request.headers.get("authorization")
    if not auth:
        return None
    parts = auth.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip()


def require_auth(request: Request) -> None:
    """FastAPI dependency: enforce ``Authorization: Bearer <token>``."""
    presented = _extract_bearer(request)
    expected = get_or_create_token()
    if not presented or not secrets.compare_digest(presented, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


# --- Lifespan ---


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and tear down shared resources."""
    settings = get_settings()
    logger.info("server_starting", host=settings.server.host, port=settings.server.port)

    try:
        embedder = HybridEmbedder()
        await embedder.initialize()

        vectorstore = QdrantVectorStore(embedder=embedder)
        await vectorstore._get_client()

        _state["vectorstore"] = vectorstore
        _state["embedder"] = embedder
        _state["reranker"] = None
        _state["start_time"] = time.time()
        # Persistent job + in-memory event tracking (TUI surfaces these)
        _state["jobs"] = load_jobs()
        prune_jobs()
        _state["events"] = []  # bounded ring of recent log events
        _state["recent_indexed_files"] = []  # bounded ring

        # Persistent restart counter — incremented every cold start.
        try:
            from rag.config import RAG_HOME
            rc_path = RAG_HOME / "restart_count"
            current = 0
            if rc_path.exists():
                try:
                    current = int(rc_path.read_text().strip() or "0")
                except Exception:
                    current = 0
            current += 1
            rc_path.write_text(str(current))
            _state["restart_count"] = current
        except Exception as _e:
            logger.debug("restart_count_persist_failed", error=str(_e))
            _state["restart_count"] = 0

        # Periodic embedder warm probe — first call pays cold cost; subsequent
        # calls measure the steady-state hot latency that drives the KPI caption.
        async def _warm_probe_loop():
            await asyncio.sleep(2.0)  # let lifespan finish
            while True:
                try:
                    t0 = time.time()
                    await embedder.embed_query("warmup")
                    _state["embedder_warm_ms"] = (time.time() - t0) * 1000.0
                except Exception as _e:
                    logger.debug("warm_probe_failed", error=str(_e))
                await asyncio.sleep(60.0)
        asyncio.create_task(_warm_probe_loop())

        # Initialize SQLite tables (query_log, index_runs, overview_stats, rate_buckets).
        try:
            from rag.storage import db as _db
            _db.init_db()
        except Exception as _e:
            logger.warning("db_init_failed", error=str(_e))

        # Optional file watcher used by `rag start --watch`.
        watch_path = ""
        try:
            import os

            watch_path = os.environ.get("RAG_WATCH_PATH", "")
            if watch_path:
                from rag.core.indexer import index_repository
                from rag.core.watcher import FileWatcher

                async def _on_change(changed: list[str]) -> None:
                    _push_event("watch_reindex_start", path=watch_path, changed=len(changed))
                    result = await index_repository(
                        repo_path=watch_path,
                        vectorstore=vectorstore,
                        full=False,
                    )
                    _push_event(
                        "watch_reindex_done",
                        path=watch_path,
                        files_processed=result.files_processed,
                        chunks_indexed=result.chunks_indexed,
                        errors=len(result.errors),
                    )

                watcher = FileWatcher(watch_path, _on_change)
                await watcher.start()
                _state["watcher"] = watcher
        except Exception as _e:
            logger.warning("watcher_start_failed", path=watch_path, error=str(_e))

        logger.info("server_ready", embedder_provider=embedder.provider, reranker="removed")
    except Exception as e:
        logger.error("server_init_failed", error=str(e))
        raise

    yield

    # Graceful shutdown — stop background work, then close resources.
    try:
        watcher = _state.get("watcher")
        if watcher:
            await watcher.stop()
    except Exception as e:
        logger.warning("watcher_shutdown_error", error=str(e))
    try:
        vs = _state.get("vectorstore")
        if vs:
            await vs.close()
    except Exception as e:
        logger.warning("shutdown_error", error=str(e))
    logger.info("server_stopped")


# --- App Factory ---


def create_app() -> FastAPI:
    app = FastAPI(title="RAG System", version="0.1.0", lifespan=lifespan)

    def _persist_job(job_id: str) -> None:
        job = _state.get("jobs", {}).get(job_id)
        if job is None:
            return
        try:
            save_job(job_id, job)
        except Exception as e:
            logger.warning("job_persist_failed", job_id=job_id, error=str(e))

    def _update_job(job_id: str, **updates: Any) -> dict[str, Any]:
        job = _state.setdefault("jobs", {}).setdefault(job_id, {})
        job.update(updates)
        _persist_job(job_id)
        return job

    # --- Global error handler ---

    @app.exception_handler(Exception)
    async def global_error_handler(request: Request, exc: Exception):
        # Log the full exception server-side (with traceback) but never echo the
        # raw message to the client — it can carry paths, config, or internals.
        logger.error(
            "unhandled_error",
            path=request.url.path,
            method=request.method,
            error=str(exc),
            exc_type=type(exc).__name__,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "code": "INTERNAL_ERROR",
                # Only the exception class name leaks — enough to triage, no PII.
                "detail": type(exc).__name__,
            },
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.detail, "code": "HTTP_ERROR", "detail": None},
        )

    # --- Rate limiting middleware (per-token bucket) ---

    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        from rag.storage import db as _db

        token = _extract_bearer(request) or "anonymous"
        try:
            allowed = _db.check_rate_bucket(token)
        except Exception as e:
            # Fail open on storage errors — better than locking out the daemon.
            logger.warning("rate_bucket_error", error=str(e))
            allowed = True
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"error": "Rate limit exceeded", "code": "RATE_LIMITED", "detail": "Token bucket exhausted"},
            )
        return await call_next(request)

    # --- CSRF guard middleware ---
    #
    # The daemon binds to localhost by default but a malicious page could still
    # try to POST/DELETE to it. We require either a bearer token (already
    # enforced on protected routes via ``require_auth``) OR — if an Origin
    # header is present at all — that it be a localhost origin. This blocks
    # cross-site form submissions that have no Authorization header.

    @app.middleware("http")
    async def csrf_guard_middleware(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin:
                low = origin.lower()
                ok = (
                    low.startswith("http://localhost:")
                    or low.startswith("http://127.0.0.1:")
                    or low == "http://localhost"
                    or low == "http://127.0.0.1"
                )
                if not ok and not _extract_bearer(request):
                    return JSONResponse(
                        status_code=403,
                        content={"error": "Forbidden origin", "code": "CSRF_BLOCKED", "detail": origin},
                    )
        return await call_next(request)

    # --- Request logging middleware ---

    @app.middleware("http")
    async def logging_middleware(request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        latency = (time.time() - start) * 1000
        logger.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            latency_ms=round(latency, 1),
        )
        _push_event(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            latency_ms=round(latency, 1),
        )
        return response

    # --- Health ---

    @app.get("/health", response_model=HealthResponse)
    async def health():
        components: dict[str, str] = {}

        # Qdrant
        try:
            vs = get_vectorstore()
            await vs._get_client()
            components["qdrant"] = "ok"
        except Exception:
            components["qdrant"] = "error"

        # Embedder
        embedder: HybridEmbedder = _state.get("embedder")
        components["embedder"] = embedder.provider if embedder else "not_initialized"

        components["reranker"] = "disabled"

        # Ollama — reuse the shared embedder's underlying client instead of
        # constructing a fresh OllamaEmbedder on every /health hit (which is
        # public + unauthenticated and would otherwise be a cheap amplification
        # vector). Fall back to a transient instance only if not initialized.
        try:
            dense = getattr(embedder, "_dense", None) if embedder else None
            if dense is None:
                from rag.core.embedder import OllamaEmbedder
                dense = OllamaEmbedder()
            components["ollama"] = "ok" if await dense.health_check() else "unavailable"
        except Exception:
            components["ollama"] = "unavailable"

        overall = "ok" if components.get("qdrant") == "ok" else "degraded"
        return HealthResponse(status=overall, components=components)

    # --- Status ---

    @app.get("/status", response_model=StatusResponse, dependencies=[Depends(require_auth)])
    async def status():
        try:
            settings = get_settings()
            vectorstore = get_vectorstore()
            embedder: HybridEmbedder = _state["embedder"]

            collections: list[dict[str, Any]] = []
            for name in (settings.qdrant.code_collection, settings.qdrant.docs_collection):
                try:
                    info = await vectorstore.collection_info(name)
                    collections.append({"name": name, "kind": "default", **info})
                except Exception:
                    collections.append(
                        {"name": name, "kind": "default", "status": "not_found", "points_count": 0}
                    )

            try:
                from rag.core.repos import RepoManager

                for repo in RepoManager().list_repos():
                    try:
                        info = await vectorstore.collection_info(repo.collection)
                        collections.append(
                            {
                                "name": repo.collection,
                                "repo": repo.name,
                                "path": repo.path,
                                "kind": "repo",
                                **info,
                            }
                        )
                    except Exception:
                        collections.append(
                            {
                                "name": repo.collection,
                                "repo": repo.name,
                                "path": repo.path,
                                "kind": "repo",
                                "status": "not_found",
                                "points_count": 0,
                            }
                        )
            except Exception as e:
                logger.debug("status_repo_collections_failed", error=str(e))

            # files_indexed = sum of file_hashes counts across every repo's state.json
            files_indexed = 0
            try:
                from rag.config import RAG_HOME
                import json as _json
                for sp in (RAG_HOME / "repos").glob("*/state.json"):
                    try:
                        data = _json.loads(sp.read_text())
                        files_indexed += len(data.get("file_hashes", {}) or {})
                    except Exception:
                        pass
            except Exception:
                pass

            gen_model = settings.llm.gen_model or settings.llm.agent_model or ""
            gen_ctx = getattr(settings.llm, "ctx_size", None) or getattr(settings.llm, "num_ctx", None)

            return StatusResponse(
                status="running",
                embedder_provider=embedder.provider,
                embedder_model=settings.embeddings.model,
                reranker_model="disabled",
                reranker_enabled=False,
                collections=collections,
                uptime_seconds=time.time() - _state.get("start_time", time.time()),
                files_indexed=files_indexed,
                embedder_warm_ms=_state.get("embedder_warm_ms"),
                restart_count=_state.get("restart_count", 0),
                gen_model=gen_model,
                gen_ctx_size=gen_ctx,
            )
        except Exception as e:
            logger.error("status_error", error=str(e))
            raise HTTPException(status_code=500, detail=f"Status check failed ({type(e).__name__})")

    # --- Recent queries (for TUI Live Log panel) ---

    @app.get("/queries/recent", dependencies=[Depends(require_auth)])
    async def queries_recent(limit: int = 20):
        from rag.storage import db as _db
        rows = _db.recent_queries(limit=max(1, min(limit, 200)))
        return {"queries": rows}

    # --- Query stats (rolling p50/p95 latency + qpm) ---

    @app.get("/queries/stats", dependencies=[Depends(require_auth)])
    async def queries_stats(window: int = 100):
        from rag.storage import db as _db
        rows = _db.recent_queries(limit=max(10, min(window, 500)))
        if not rows:
            return {"count": 0, "p50_ms": 0, "p95_ms": 0, "qpm": 0.0, "avg_results": 0.0}
        lats = sorted(float(r.get("latency_ms") or 0.0) for r in rows)
        n = len(lats)

        def _pct(p: float) -> float:
            idx = max(0, min(n - 1, int(round((p / 100.0) * (n - 1)))))
            return round(lats[idx], 1)

        # qpm — count of queries in last 60s. Timestamps may be ISO strings
        # or epoch floats depending on storage; tolerate both, skip unparseable.
        from datetime import datetime, timezone

        now_ts = time.time()
        recent_60 = 0
        for r in rows:
            ts = r.get("timestamp")
            if ts is None:
                continue
            try:
                if isinstance(ts, (int, float)):
                    t = float(ts)
                else:
                    t = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).replace(tzinfo=timezone.utc).timestamp()
                if now_ts - t <= 60:
                    recent_60 += 1
            except Exception:
                continue
        avg_results = round(sum(float(r.get("results_count") or 0) for r in rows) / n, 2)
        return {
            "count": n,
            "p50_ms": _pct(50),
            "p95_ms": _pct(95),
            "qpm": float(recent_60),
            "avg_results": avg_results,
        }

    # --- Collections list (for multi-repo cards) ---

    @app.get("/collections", dependencies=[Depends(require_auth)])
    async def collections_list():
        vectorstore = get_vectorstore()
        settings = get_settings()
        results = []
        for name in (settings.qdrant.code_collection, settings.qdrant.docs_collection):
            try:
                info = await vectorstore.collection_info(name)
                results.append({"name": name, "kind": "default", **info})
            except Exception:
                results.append({"name": name, "kind": "default", "status": "not_found", "points_count": 0})
        try:
            from rag.core.repos import RepoManager

            for repo in RepoManager().list_repos():
                try:
                    info = await vectorstore.collection_info(repo.collection)
                    results.append(
                        {
                            "name": repo.collection,
                            "repo": repo.name,
                            "path": repo.path,
                            "kind": "repo",
                            **info,
                        }
                    )
                except Exception:
                    results.append(
                        {
                            "name": repo.collection,
                            "repo": repo.name,
                            "path": repo.path,
                            "kind": "repo",
                            "status": "not_found",
                            "points_count": 0,
                        }
                    )
        except Exception as e:
            logger.debug("collections_repo_list_failed", error=str(e))
        return {"collections": results}

    # --- Plugins (loaded YAML manifests in ~/.rag/plugins/) ---

    @app.get("/plugins", dependencies=[Depends(require_auth)])
    async def plugins_list():
        try:
            from rag.core.plugins import discover_plugins
            plugins = discover_plugins()
            return {
                "plugins": [
                    {
                        "name": getattr(p, "name", "?"),
                        "version": getattr(p, "version", "?"),
                        "patterns": len(getattr(p, "patterns", {}) or {}),
                        "domains": len(getattr(p, "domain_keywords", {}) or {}),
                    }
                    for p in plugins
                ]
            }
        except Exception as e:
            logger.debug("plugins_list_error", error=str(e))
            return {"plugins": []}

    # --- Recent events ring (logs tail for TUI) ---

    @app.get("/events/recent", dependencies=[Depends(require_auth)])
    async def events_recent(limit: int = 100, after_ts: float = 0.0):
        ring = list(_state.get("events", []))
        if after_ts > 0:
            ring = [e for e in ring if e.get("ts", 0) > after_ts]
        return {"events": ring[-limit:]}

    # --- Health detail (drill-down) ---

    @app.get("/health/detail", dependencies=[Depends(require_auth)])
    async def health_detail():
        settings = get_settings()
        out: dict[str, Any] = {
            "embedder_model": settings.embeddings.model,
            "agent_model": settings.llm.agent_model,
            "ollama_url": settings.llm.ollama_url,
        }
        # Ollama version + model digests
        try:
            import httpx as _h
            async with _h.AsyncClient(timeout=3.0) as client:
                v = await client.get(f"{settings.llm.ollama_url}/api/version")
                if v.status_code == 200:
                    out["ollama_version"] = v.json().get("version", "?")
                tags = await client.get(f"{settings.llm.ollama_url}/api/tags")
                if tags.status_code == 200:
                    out["ollama_models"] = [
                        {"name": m.get("name"), "size": m.get("size"), "digest": (m.get("digest") or "")[:12]}
                        for m in tags.json().get("models", [])
                    ]
        except Exception as e:
            out["ollama_error"] = str(e)
        # Last embed latency from event ring
        embed_events = [e for e in _state.get("events", []) if e.get("event") == "embed_latency"]
        if embed_events:
            recent = embed_events[-50:]
            lats = sorted(float(e.get("ms", 0.0)) for e in recent)
            mid = len(lats) // 2
            out["embed_p50_ms"] = round(lats[mid], 1)
            out["embed_p95_ms"] = round(lats[max(0, int(len(lats) * 0.95) - 1)], 1)
        return out

    # --- Overview for TUI (module summaries + KG communities digest) ---

    @app.get("/overview/tui", dependencies=[Depends(require_auth)])
    async def overview_tui():
        out: dict[str, Any] = {"summaries": [], "communities": [], "top_nodes": []}
        try:
            from rag.core.summaries import list_summaries

            out["summaries"] = await list_summaries(get_vectorstore(), limit=20)
        except Exception as e:
            logger.debug("overview_summaries_error", error=str(e))
        try:
            from rag.core.graph import get_graph

            g = get_graph()
            communities = sorted(
                g.communities.values(),
                key=lambda c: len(c.members),
                reverse=True,
            )[:10]
            out["communities"] = [
                {
                    "id": c.id,
                    "label": c.label,
                    "member_count": len(c.members),
                    "files": c.files[:10],
                }
                for c in communities
            ]
            out["top_nodes"] = [
                {
                    "id": node,
                    "degree": degree,
                    "file_path": g.graph.nodes[node].get("file_path", ""),
                    "name": g.graph.nodes[node].get("name", ""),
                    "chunk_type": g.graph.nodes[node].get("chunk_type", ""),
                }
                for node, degree in sorted(
                    g.graph.degree(),
                    key=lambda item: item[1],
                    reverse=True,
                )[:10]
            ]
        except Exception as e:
            logger.debug("overview_graph_error", error=str(e))
        return out

    # --- Recently re-indexed files (TUI) ---

    @app.get("/files/recent", dependencies=[Depends(require_auth)])
    async def files_recent(limit: int = 50):
        ring = list(_state.get("recent_indexed_files", []))
        return {"files": ring[-limit:]}

    # --- Async index job (TUI fires & polls progress) ---

    @app.post("/index/start", dependencies=[Depends(require_auth)])
    async def index_start(req: IndexRequest):
        job_id = secrets.token_urlsafe(8)
        _state["jobs"][job_id] = {
            "status": "queued",
            "started_at": time.time(),
            "repo_path": req.repo_path,
            "full": req.full,
            "collection": req.collection,
            "languages": req.languages,
            "files_processed": 0,
            "total_files": 0,
            "chunks_indexed": 0,
            "files_skipped": 0,
            "files_deleted": 0,
            "chunks_seen": 0,
            "chunks_total_estimate": 0,
            "timings_ms": {},
            "current_file": "",
            "errors": [],
        }
        _persist_job(job_id)

        async def _run():
            try:
                from rag.core.indexer import index_repository

                _update_job(job_id, status="scanning")
                vectorstore = get_vectorstore()

                def _progress(progress: dict[str, Any]) -> None:
                    job = _state["jobs"].get(job_id)
                    if job is None:
                        return
                    rel_path = str(progress.get("current_file") or "")
                    current = int(progress.get("files_processed") or 0)
                    total = int(progress.get("total_files") or 0)
                    job.update(
                        {
                            "status": progress.get("status") or "running",
                            "current_file": rel_path,
                            "files_processed": current,
                            "total_files": total,
                            "chunks_seen": int(progress.get("chunks_seen") or 0),
                            "chunks_total_estimate": int(progress.get("chunks_total_estimate") or 0),
                            "chunks_indexed": int(progress.get("chunks_indexed") or job.get("chunks_indexed") or 0),
                        }
                    )
                    if rel_path:
                        _push_recent_file(rel_path, 0)
                    if current == total or current % 10 == 0:
                        _persist_job(job_id)

                result = await index_repository(
                    repo_path=req.repo_path,
                    vectorstore=vectorstore,
                    collection=req.collection,
                    full=req.full,
                    languages=req.languages,
                    on_progress=_progress,
                )
                _update_job(
                    job_id,
                    status="completed",
                    finished_at=time.time(),
                    files_processed=getattr(result, "files_processed", _state["jobs"][job_id]["files_processed"]),
                    chunks_indexed=getattr(result, "chunks_indexed", 0),
                    files_skipped=getattr(result, "files_skipped", 0),
                    files_deleted=getattr(result, "files_deleted", 0),
                    errors=getattr(result, "errors", []),
                    timings_ms={
                        key: round(value, 1)
                        for key, value in getattr(result, "timings_ms", {}).items()
                    },
                )
                if req.collection:
                    try:
                        from rag.core.repos import RepoManager

                        mgr = RepoManager()
                        for repo in mgr.list_repos():
                            if repo.collection == req.collection:
                                mgr.update_stats(repo.name, result.chunks_indexed)
                                break
                    except Exception as e:
                        logger.warning(
                            "repo_stats_update_failed",
                            collection=req.collection,
                            chunks_indexed=result.chunks_indexed,
                            error=str(e),
                        )
            except Exception as e:
                _update_job(
                    job_id,
                    status="failed",
                    error=str(e),
                    finished_at=time.time(),
                )
                logger.error("index_job_failed", job_id=job_id, error=str(e))

        asyncio.get_running_loop().call_later(0.1, lambda: asyncio.create_task(_run()))
        return {"job_id": job_id, "status": "queued"}

    @app.get("/index/progress/{job_id}", dependencies=[Depends(require_auth)])
    async def index_progress(job_id: str):
        job = _state.get("jobs", {}).get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Unknown job_id: {job_id}")
        return job

    @app.get("/index/jobs", dependencies=[Depends(require_auth)])
    async def index_jobs():
        return {"jobs": _state.get("jobs", {})}

    # --- Search ---

    @app.post("/search", response_model=SearchResponse, dependencies=[Depends(require_auth)])
    async def search(req: SearchRequest):
        start = time.time()
        try:
            settings = get_settings()
            vectorstore = get_vectorstore()
            code_collection = settings.qdrant.code_collection
            if req.repo:
                from rag.core.repos import RepoManager

                repo_info = RepoManager().get(req.repo)
                if repo_info is None:
                    raise HTTPException(status_code=404, detail=f"Unknown repo: {req.repo}")
                code_collection = repo_info.collection

            from rag.agents.retrieval import plan_search

            plan = await plan_search(req.query)
            if req.repo and plan.strategy in ("lod_drill", "global", "graph_walk"):
                # LOD summaries and the graph cache are shared process-wide,
                # while named repos live in separate Qdrant collections.
                # Keep repo-scoped searches strictly inside that collection.
                plan.strategy = "hybrid"

            # Route by strategy
            if plan.strategy == "lod_drill":
                # Hierarchical drill-down: L0 (modules) → L1 (files) → L2 (chunks).
                # Falls back to flat hybrid if L0/L1 collections empty (e.g.
                # index pre-dates LOD or RAG_SKIP_SUMMARIES=1 was set).
                from rag.core.summaries import LOD_L0_COLLECTION, LOD_L1_COLLECTION

                l0_count = await vectorstore.count(LOD_L0_COLLECTION)
                if l0_count == 0:
                    # No LOD data — degrade to flat hybrid search.
                    logger.info("lod_drill_degraded", reason="no_lod_data")
                    result_map: dict[str, tuple[Any, list[int]]] = {}
                    for qi, q in enumerate(plan.queries):
                        merged_filters = {**(plan.filters or {}), **(req.filters or {})}
                        query_results = await vectorstore.search(
                            collection=code_collection,
                            query=q,
                            top_k=req.top_k or plan.top_k,
                            filters=merged_filters if merged_filters else None,
                        )
                        for r in query_results:
                            if r.point_id in result_map:
                                result_map[r.point_id][1].append(qi)
                            else:
                                result_map[r.point_id] = (r, [qi])
                    results = [r for r, _ in result_map.values()]
                    matched_queries_map = {pid: qis for pid, (_, qis) in result_map.items()}
                else:
                    # Hop 1: top-3 modules
                    l0_hits = await vectorstore.search(
                        collection=LOD_L0_COLLECTION,
                        query=req.query,
                        top_k=3,
                    )
                    top_modules = [
                        h.payload.get("module_path") for h in l0_hits
                        if h.payload.get("module_path")
                    ]

                    # Hop 2: top-5 files within those modules
                    l1_hits = []
                    if top_modules:
                        l1_hits = await vectorstore.search(
                            collection=LOD_L1_COLLECTION,
                            query=req.query,
                            top_k=5,
                            filters={"module_path": top_modules},
                        )
                    top_files = [
                        h.payload.get("file_path") for h in l1_hits
                        if h.payload.get("file_path")
                    ]

                    # Hop 3: chunks within those files
                    results = []
                    if top_files:
                        merged_filters = {
                            "file_path": top_files,
                            **(plan.filters or {}),
                            **(req.filters or {}),
                        }
                        results = await vectorstore.search(
                            collection=code_collection,
                            query=req.query,
                            top_k=req.top_k or plan.top_k,
                            filters=merged_filters,
                        )
                    matched_queries_map = {}
                    logger.info(
                        "lod_drill_executed",
                        modules=len(top_modules),
                        files=len(top_files),
                        chunks=len(results),
                    )

            elif plan.strategy == "global":
                # Search module summaries collection
                from rag.core.summaries import SUMMARY_COLLECTION
                results = await vectorstore.search(
                    collection=SUMMARY_COLLECTION,
                    query=req.query,
                    top_k=req.top_k or 5,
                )
                matched_queries_map = {}

            elif plan.strategy == "graph_walk":
                # Use code graph for multi-hop traversal + vector search
                from rag.core.graph import get_graph
                graph = get_graph()
                # Find entry point via vector search
                seed_results = await vectorstore.search(
                    collection=code_collection,
                    query=req.query,
                    top_k=3,
                )
                # Traverse graph from each seed in score order (seed_results
                # is already score-sorted). Collect related file paths in
                # insertion order so the downstream slice [:10] is stable
                # across runs — sets are hash-randomized in Python, so the
                # previous ``set | list(...)[:10]`` truncation produced
                # different results between processes.
                ordered_files: dict[str, None] = {}
                for sr in seed_results:
                    node_id = f"{sr.payload.get('file_path', '')}:{sr.payload.get('parent_name', '')}.{sr.payload.get('name', '')}".replace(".:", ":")
                    # ``traverse`` returns BFS-ordered neighbours; preserve it.
                    for n in graph.traverse(node_id, max_hops=2):
                        if ":" not in n:
                            continue
                        fp = n.split(":")[0]
                        if fp:
                            ordered_files.setdefault(fp, None)

                related_files_ordered = list(ordered_files.keys())
                results = []
                for fp in related_files_ordered[:10]:
                    file_results = await vectorstore.search(
                        collection=code_collection,
                        query=req.query,
                        top_k=5,
                        filters={"file_path": fp},
                    )
                    results.extend(file_results)

                # Deduplicate
                seen = set()
                deduped = []
                for r in results:
                    if r.point_id not in seen:
                        seen.add(r.point_id)
                        deduped.append(r)
                results = deduped[:req.top_k or plan.top_k]
                matched_queries_map = {}

            else:
                # Standard: hybrid, filtered, naive, aggregate
                result_map: dict[str, tuple[Any, list[int]]] = {}
                for qi, q in enumerate(plan.queries):
                    merged_filters = {**(plan.filters or {}), **(req.filters or {})}
                    query_results = await vectorstore.search(
                        collection=code_collection,
                        query=q,
                        top_k=req.top_k or plan.top_k,
                        filters=merged_filters if merged_filters else None,
                    )
                    for r in query_results:
                        if r.point_id in result_map:
                            result_map[r.point_id][1].append(qi)
                        else:
                            result_map[r.point_id] = (r, [qi])

                results = [r for r, _ in result_map.values()]
                matched_queries_map = {pid: qis for pid, (_, qis) in result_map.items()}

            # Reranker was removed. Keep the old request field accepted for
            # back-compat, but scoring below is always dense + metadata boosts.
            did_rerank = False

            from rag.core.scoring import score_results
            results = score_results(results, req.query, reranked=did_rerank)

            latency = (time.time() - start) * 1000

            logger.info(
                "query_executed",
                query=req.query,
                results=len(results),
                latency_ms=round(latency, 1),
            )

            try:
                from rag.storage import db as _db
                _db.log_query(req.query, len(results), latency)
            except Exception as _e:
                logger.debug("query_log_write_failed", error=str(_e))

            result_items = []
            for r in results:
                item = SearchResultItem(
                    **r.slim(),
                    matched_queries=matched_queries_map.get(r.point_id, []),
                )
                result_items.append(item)

            return SearchResponse(
                results=result_items,
                query=req.query,
                plan=SearchPlanInfo(
                    strategy=plan.strategy,
                    queries=plan.queries,
                    filters=plan.filters,
                ),
                total=len(results),
                latency_ms=round(latency, 1),
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error("search_error", query=req.query, error=str(e))
            raise HTTPException(status_code=500, detail=f"Search failed ({type(e).__name__})")

    # --- Enumerate (exhaustive metadata-only listing via Qdrant scroll) ---

    @app.post("/enumerate", response_model=EnumerateResponse, dependencies=[Depends(require_auth)])
    async def enumerate_chunks(req: EnumerateRequest):
        """Return ALL chunks matching payload filters. No vector search,
        no top-k cutoff. Pages through Qdrant via scroll. Use this for
        questions like 'list every suspend function' or 'every @Singleton class'
        where exhaustiveness matters more than ranking."""
        try:
            from rag.core.vectorstore import _build_qdrant_filter

            vectorstore = get_vectorstore()
            settings = get_settings()
            client = await vectorstore._get_client()
            qf = _build_qdrant_filter(req.filters) if req.filters else None

            results: list[dict[str, Any]] = []
            seen_ids: set[str] = set()
            next_offset = None
            page_size = 256
            truncated = False
            while len(results) < req.limit:
                points, next_offset = await client.scroll(
                    collection_name=settings.qdrant.code_collection,
                    scroll_filter=qf,
                    with_payload=True,
                    with_vectors=False,
                    limit=min(page_size, req.limit - len(results)),
                    offset=next_offset,
                )
                if not points:
                    break
                for p in points:
                    pid = str(getattr(p, "id", ""))
                    if pid and pid in seen_ids:
                        continue
                    seen_ids.add(pid)
                    payload = p.payload or {}
                    results.append({k: payload.get(k) for k in req.fields})
                if next_offset is None:
                    break

            # If next_offset still set and we hit limit, more matches exist.
            if next_offset is not None and len(results) >= req.limit:
                truncated = True

            logger.info(
                "enumerate_executed",
                filters=req.filters,
                count=len(results),
                truncated=truncated,
            )
            return EnumerateResponse(
                count=len(results),
                filters=req.filters,
                results=results,
                truncated=truncated,
            )
        except Exception as e:
            logger.error("enumerate_error", error=str(e))
            raise HTTPException(status_code=500, detail=f"Enumerate failed ({type(e).__name__})")

    # --- Ask (RAG: retrieve + generate) ---

    @app.post("/ask", response_model=AskResponse, dependencies=[Depends(require_auth)])
    async def ask(req: AskRequest):
        """Retrieval-Augmented Generation: search the index, then ground an
        Ollama LLM answer in the retrieved chunks with citations."""
        import httpx

        start = time.time()
        settings = get_settings()
        vectorstore = get_vectorstore()
        collection = settings.qdrant.code_collection
        filters = None
        if req.repo:
            from rag.core.repos import RepoManager

            repo_info = RepoManager().get(req.repo)
            if repo_info is not None:
                collection = repo_info.collection
            else:
                filters = {"file_path": req.repo}

        # 1. Retrieve — raw vector search, no planner filters.
        try:
            r_start = time.time()
            results = await vectorstore.search(
                collection=collection,
                query=req.question,
                top_k=req.top_k,
                filters=filters,
            )
            retrieval_ms = (time.time() - r_start) * 1000
        except Exception as e:
            logger.error("ask_retrieval_error", error=str(e))
            raise HTTPException(status_code=500, detail=f"Retrieval failed ({type(e).__name__})")

        gen_model = settings.llm.gen_model or settings.llm.agent_model

        if not results:
            return AskResponse(
                question=req.question,
                answer="No relevant code found in the index for this question.",
                citations=[],
                model=gen_model,
                retrieval_ms=round(retrieval_ms, 1),
                generation_ms=0.0,
                latency_ms=round((time.time() - start) * 1000, 1),
            )

        # 2. Build grounded prompt.
        ctx_parts = []
        citations: list[Citation] = []
        for i, r in enumerate(results, 1):
            p = r.payload
            file_path = p.get("file_path", "?")
            lines = f"{p.get('start_line', '?')}-{p.get('end_line', '?')}"
            name = p.get("name", "") or p.get("parent_name", "")
            code = (p.get("content") or p.get("code") or "")[: req.max_chunk_chars]
            ctx_parts.append(
                f"[{i}] {file_path}:{lines} ({name})\n```{p.get('language', '')}\n{code}\n```"
            )
            citations.append(
                Citation(
                    file_path=file_path,
                    lines=lines,
                    name=name,
                    score=round(r.score, 4),
                )
            )

        context_block = "\n\n".join(ctx_parts)
        system = (
            "You are a code assistant. Answer the user's question using ONLY "
            "the provided code snippets. Cite sources inline as [N] matching "
            "the snippet numbers. If the answer is not in the snippets, say "
            "you don't know. Be concise and concrete."
        )
        user = f"Question: {req.question}\n\nCode snippets:\n{context_block}\n\nAnswer (with [N] citations):"

        # 3. Generate via Ollama /api/chat (non-streaming).
        g_start = time.time()
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                resp = await client.post(
                    f"{settings.llm.ollama_url}/api/chat",
                    json={
                        "model": gen_model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "stream": False,
                        "options": {"temperature": 0.2, "num_ctx": 8192},
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                answer = data.get("message", {}).get("content", "").strip()
        except Exception as e:
            logger.error("ask_generation_error", error=str(e))
            raise HTTPException(status_code=502, detail=f"LLM generation failed ({type(e).__name__})")
        generation_ms = (time.time() - g_start) * 1000

        total = (time.time() - start) * 1000
        logger.info(
            "ask_executed",
            question=req.question,
            chunks=len(results),
            retrieval_ms=round(retrieval_ms, 1),
            generation_ms=round(generation_ms, 1),
        )

        try:
            from rag.storage import db as _db
            _db.log_query(f"ask: {req.question}", len(results), total)
        except Exception as _e:
            logger.debug("query_log_write_failed", error=str(_e))

        return AskResponse(
            question=req.question,
            answer=answer,
            citations=citations,
            model=gen_model,
            retrieval_ms=round(retrieval_ms, 1),
            generation_ms=round(generation_ms, 1),
            latency_ms=round(total, 1),
        )

    # --- Index ---

    @app.post("/index", response_model=IndexResponse, dependencies=[Depends(require_auth)])
    async def index(req: IndexRequest):
        try:
            from rag.core.indexer import index_repository

            vectorstore = get_vectorstore()
            result = await index_repository(
                repo_path=req.repo_path,
                vectorstore=vectorstore,
                collection=req.collection,
                full=req.full,
                languages=req.languages,
            )
            if req.collection:
                try:
                    from rag.core.repos import RepoManager

                    mgr = RepoManager()
                    for repo in mgr.list_repos():
                        if repo.collection == req.collection:
                            mgr.update_stats(repo.name, result.chunks_indexed)
                            break
                except Exception as e:
                    logger.warning(
                        "repo_stats_update_failed",
                        collection=req.collection,
                        chunks_indexed=result.chunks_indexed,
                        error=str(e),
                    )
            return IndexResponse(
                files_processed=result.files_processed,
                chunks_indexed=result.chunks_indexed,
                files_skipped=result.files_skipped,
                files_deleted=result.files_deleted,
                errors=result.errors,
            )
        except Exception as e:
            logger.error("index_error", repo_path=req.repo_path, error=str(e))
            raise HTTPException(status_code=500, detail=f"Index failed ({type(e).__name__})")

    # --- Overview (P3-18: Codebase aggregation) ---

    @app.get("/overview", dependencies=[Depends(require_auth)])
    async def overview():
        """Aggregate codebase metadata: languages, patterns, complexity stats.

        Prefers the materialized counters in SQLite (populated incrementally
        by the indexer); falls back to a full Qdrant scroll if those are
        empty (e.g. the index pre-dates the counter table) and seeds them
        from the scroll so subsequent calls stay cheap.
        """
        try:
            from rag.storage import db as _db
            cached = _db.get_overview()
            if cached.get("total_chunks", 0) > 0:
                return cached

            settings = get_settings()
            vectorstore = get_vectorstore()
            client = await vectorstore._get_client()

            # Scroll through all points to aggregate
            langs: dict[str, int] = {}
            patterns: dict[str, int] = {}
            complexities: list[int] = []
            total_chunks = 0

            offset = None
            while True:
                points, offset = await client.scroll(
                    collection_name=settings.qdrant.code_collection,
                    limit=100,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                if not points:
                    break
                for p in points:
                    if not p.payload:
                        continue
                    total_chunks += 1
                    lang = p.payload.get("language", "unknown")
                    langs[lang] = langs.get(lang, 0) + 1
                    pats = p.payload.get("patterns", []) or []
                    for pat in pats:
                        patterns[pat] = patterns.get(pat, 0) + 1
                    cc = p.payload.get("complexity_cyclomatic")
                    if cc is not None and isinstance(cc, (int, float)):
                        complexities.append(int(cc))
                    # Seed materialized counters so the next call hits the
                    # fast path. Failure is silent — fallback still works.
                    try:
                        _db.incr_overview(lang, list(pats), cc if isinstance(cc, (int, float)) else None)
                    except Exception:
                        pass
                if offset is None:
                    break

            avg_complexity = sum(complexities) / len(complexities) if complexities else 0

            return {
                "total_chunks": total_chunks,
                "languages": dict(sorted(langs.items(), key=lambda x: -x[1])),
                "patterns": dict(sorted(patterns.items(), key=lambda x: -x[1])),
                "complexity": {
                    "average": round(avg_complexity, 1),
                    "max": max(complexities) if complexities else 0,
                    "high_count": sum(1 for c in complexities if c > 10),
                },
            }
        except Exception as e:
            logger.error("overview_error", error=str(e))
            raise HTTPException(status_code=500, detail=f"Overview failed ({type(e).__name__})")

    # --- Admin: hot-reload settings ---

    @app.post("/admin/reload", response_model=ReloadResponse, dependencies=[Depends(require_auth)])
    async def admin_reload(req: ReloadRequest):
        """Re-read config files and lazily reinitialize the embedder if
        its model changed. Refuses to swap the embedding model (which
        would invalidate the index) unless ``force=true``.

        Reranker reload was dropped when the reranker was removed.
        """
        # Snapshot current model name *before* clearing the cache.
        old_settings = get_settings()
        old_embed_model = old_settings.embeddings.model

        reload_settings()
        new_settings = get_settings()

        embedder_changed = new_settings.embeddings.model != old_embed_model

        if embedder_changed and not req.force:
            # Roll back the cache so the running daemon still matches the
            # old settings — refusing the reload is meaningless if the next
            # caller sees the new config.
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Embedding model change ({old_embed_model} -> "
                    f"{new_settings.embeddings.model}) would invalidate the index. "
                    "Re-index from scratch and pass force=true."
                ),
            )

        embedder_reinit = False

        if embedder_changed:
            try:
                new_embedder = HybridEmbedder()
                await new_embedder.initialize()
                # The embedding cache is keyed by content hash only — it has no
                # idea which model produced a vector. After a model swap every
                # cached vector is from the OLD model (likely a different dim),
                # so reusing them would mix incompatible vectors into the index
                # and break search. Clear it before any new upsert can hit it.
                from rag.core.cache import EmbeddingCache
                EmbeddingCache().clear()
                logger.info("embed_cache_cleared", reason="embedding_model_changed")
                # Replace embedder reference on the live vectorstore so
                # subsequent searches use the new model.
                vs = _state.get("vectorstore")
                if vs is not None:
                    vs._embedder = new_embedder
                _state["embedder"] = new_embedder
                embedder_reinit = True
            except Exception as e:
                logger.error("embedder_reinit_failed", error=str(e))
                raise HTTPException(status_code=500, detail=f"Embedder reinit failed ({type(e).__name__})")

        return ReloadResponse(
            reloaded=True,
            embedder_reinitialized=embedder_reinit,
            reranker_reinitialized=False,
            detail=(
                "models unchanged" if not embedder_changed
                else "swapped: embedder"
            ),
        )

    # --- Web dashboard (v2) ---
    #
    # A self-contained single-page dashboard served from the daemon itself so
    # it is *same-origin*: the browser inherits the daemon's auth token (which
    # we inject into the page at serve time) and sails past the CSRF guard
    # without any CORS configuration. The TUI remains the primary client; this
    # is a browser-based alternative that polls the same read endpoints.
    _WEB_DIR = Path(__file__).parent / "web"

    @app.get("/", include_in_schema=False)
    async def web_dashboard():
        from fastapi.responses import HTMLResponse

        index = _WEB_DIR / "index.html"
        if not index.exists():
            return JSONResponse(
                status_code=404,
                content={
                    "error": "Web dashboard not installed",
                    "code": "WEB_NOT_FOUND",
                    "detail": "src/rag/web/index.html is missing",
                },
            )
        # Inject the daemon token so same-origin fetch() calls can authenticate
        # without the user pasting it. The token never leaves localhost — the
        # page is only reachable from a browser pointed at 127.0.0.1:7890.
        html = index.read_text(encoding="utf-8")
        token = get_or_create_token()
        html = html.replace("__RAG_TOKEN__", token)
        return HTMLResponse(content=html)

    # NB: we intentionally do *not* mount the web/ directory as static files.
    # The only document is index.html, which must be served through the route
    # above so the token placeholder gets substituted — serving it verbatim via
    # a static mount would hand the browser a non-functional page (literal
    # ``__RAG_TOKEN__`` → every API call 401s). If real assets (favicon, fonts)
    # are added later, mount them under a dedicated prefix that excludes
    # index.html.

    return app


app = create_app()
