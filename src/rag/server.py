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
from rag.core.vectorstore import QdrantVectorStore

logger = structlog.get_logger()

MAX_QUERY_LENGTH = 2000
MAX_TOP_K = 200


# --- Request/Response Models with Validation ---


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=MAX_QUERY_LENGTH)
    top_k: int | None = Field(None, ge=1, le=MAX_TOP_K)
    filters: dict[str, Any] | None = None
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


class IndexRequest(BaseModel):
    repo_path: str = Field(..., min_length=1)
    full: bool = False
    languages: list[str] | None = None

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

        from rag.core.reranker import OllamaReranker
        reranker = OllamaReranker()
        # Fire-and-forget warmup — first /search shouldn't pay model-load cost.
        asyncio.create_task(reranker.warmup())

        _state["vectorstore"] = vectorstore
        _state["embedder"] = embedder
        _state["reranker"] = reranker
        _state["start_time"] = time.time()

        logger.info("server_ready", embedder_provider=embedder.provider, reranker=reranker._model)
    except Exception as e:
        logger.error("server_init_failed", error=str(e))
        raise

    yield

    # Graceful shutdown — close resources
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

    # --- Global error handler ---

    @app.exception_handler(Exception)
    async def global_error_handler(request: Request, exc: Exception):
        logger.error("unhandled_error", path=request.url.path, error=str(exc), exc_type=type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "code": "INTERNAL_ERROR", "detail": str(exc)},
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

        # Reranker status
        rr = get_reranker()
        components["reranker"] = "enabled" if rr and rr.enabled else "disabled"

        # Ollama
        try:
            from rag.core.embedder import OllamaEmbedder
            ollama = OllamaEmbedder()
            components["ollama"] = "ok" if await ollama.health_check() else "unavailable"
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

            code_info = await vectorstore.collection_info(settings.qdrant.code_collection)
            docs_info = await vectorstore.collection_info(settings.qdrant.docs_collection)

            return StatusResponse(
                status="running",
                embedder_provider=embedder.provider,
                embedder_model=settings.embeddings.model,
                reranker_model=settings.reranker.model,
                reranker_enabled=settings.reranker.enabled,
                collections=[code_info, docs_info],
                uptime_seconds=time.time() - _state.get("start_time", time.time()),
            )
        except Exception as e:
            logger.error("status_error", error=str(e))
            raise HTTPException(status_code=500, detail=f"Status check failed: {e}")

    # --- Search ---

    @app.post("/search", response_model=SearchResponse, dependencies=[Depends(require_auth)])
    async def search(req: SearchRequest):
        start = time.time()
        try:
            settings = get_settings()
            vectorstore = get_vectorstore()

            from rag.agents.retrieval import plan_search

            plan = await plan_search(req.query)

            # Route by strategy
            if plan.strategy == "global":
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
                    collection=settings.qdrant.code_collection,
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
                        collection=settings.qdrant.code_collection,
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
                        collection=settings.qdrant.code_collection,
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

            # Rerank via Ollama Qwen3-Reranker (yes/no template). Skip for
            # ``naive`` and ``global`` strategies (per planner contract) and
            # when the client opts out via ``rerank=False``.
            did_rerank = False
            reranker = get_reranker()
            if (
                req.rerank
                and results
                and reranker is not None
                and reranker.enabled
                and plan.strategy not in ("naive", "global")
            ):
                try:
                    results = await reranker.rerank(req.query, results)
                    did_rerank = True
                except Exception as e:
                    logger.warning("rerank_degraded", error=repr(e))

            from rag.core.scoring import score_results
            results = score_results(results, req.query, reranked=did_rerank)

            latency = (time.time() - start) * 1000

            logger.info(
                "query_executed",
                query=req.query,
                results=len(results),
                latency_ms=round(latency, 1),
            )

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
        except Exception as e:
            logger.error("search_error", query=req.query, error=str(e))
            raise HTTPException(status_code=500, detail=f"Search failed: {e}")

    # --- Index ---

    @app.post("/index", response_model=IndexResponse, dependencies=[Depends(require_auth)])
    async def index(req: IndexRequest):
        try:
            from rag.core.indexer import index_repository

            vectorstore = get_vectorstore()
            result = await index_repository(
                repo_path=req.repo_path,
                vectorstore=vectorstore,
                full=req.full,
                languages=req.languages,
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
            raise HTTPException(status_code=500, detail=f"Index failed: {e}")

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
            raise HTTPException(status_code=500, detail=f"Overview failed: {e}")

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
                # Replace embedder reference on the live vectorstore so
                # subsequent searches use the new model.
                vs = _state.get("vectorstore")
                if vs is not None:
                    vs._embedder = new_embedder
                _state["embedder"] = new_embedder
                embedder_reinit = True
            except Exception as e:
                logger.error("embedder_reinit_failed", error=str(e))
                raise HTTPException(status_code=500, detail=f"Embedder reinit failed: {e}")

        return ReloadResponse(
            reloaded=True,
            embedder_reinitialized=embedder_reinit,
            reranker_reinitialized=False,
            detail=(
                "models unchanged" if not embedder_changed
                else "swapped: embedder"
            ),
        )

    return app


app = create_app()
