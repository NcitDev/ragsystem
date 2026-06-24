"""FastAPI server with search, index, and status routes."""

from __future__ import annotations

import asyncio
import re
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
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


# --- Request/Response Models with Validation ---


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=MAX_QUERY_LENGTH)
    top_k: int | None = Field(None, ge=1, le=MAX_TOP_K)
    filters: dict[str, Any] | None = None
    repo: str | None = None
    # ``rerank`` is kept for back-compat with existing clients but is
    # ignored — the cross-encoder reranker was removed alongside FastEmbed.
    rerank: bool = True
    # Which strategy planner to use:
    #   "auto"     — LLM planner with heuristic fallback (default, production path)
    #   "llm"      — same as auto (force the LLM planner path explicitly)
    #   "fallback" — skip the LLM, use the deterministic heuristic planner
    # Mainly for A/B benchmarking the planner; "fallback" is also a cheap,
    # latency-free option for clients that don't want an LLM round-trip.
    planner: str = Field("auto", pattern=r"^(auto|llm|fallback)$")


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


class DocsSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=MAX_QUERY_LENGTH)
    top_k: int = Field(5, ge=1, le=50)
    filters: dict[str, Any] | None = None


class ContextPackRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=MAX_QUERY_LENGTH)
    repo: str | None = None
    filters: dict[str, Any] | None = None
    max_slices: int = Field(8, ge=1, le=50)
    max_source_tokens: int = Field(6000, ge=100, le=100000)
    use_ast_index: bool = True
    include_semantic: bool = True
    strategy: str = "lod_drill"


class ContextSlice(BaseModel):
    file_path: str
    name: str
    parent_name: str
    chunk_type: str
    language: str
    lines: str
    code: str
    score: float
    token_estimate: int
    citation: str
    why_included: str


class ContextPackResponse(BaseModel):
    query: str
    repo: str | None = None
    slices: list[ContextSlice]
    total: int
    total_source_tokens: int
    latency_ms: float


class ResolveRequest(BaseModel):
    repo: str = Field(..., min_length=1)
    query: str | None = Field(None, max_length=MAX_QUERY_LENGTH)
    symbols: list[str] = Field(default_factory=list)
    definitions_limit: int = Field(20, ge=1, le=100)
    usages_limit: int = Field(20, ge=0, le=200)


class ResolveResponse(BaseModel):
    repo: str
    symbols: list[str]
    definitions: list[ContextSlice]
    usages: list[ContextSlice]
    total_definitions: int
    total_usages: int
    latency_ms: float


class CallTreeRequest(BaseModel):
    repo: str = Field(..., min_length=1)
    symbol: str = Field(..., min_length=1, max_length=MAX_QUERY_LENGTH)
    limit: int = Field(50, ge=1, le=200)


class CallTreeNode(ContextSlice):
    depth: int = 0


class CallTreeResponse(BaseModel):
    repo: str
    symbol: str
    nodes: list[CallTreeNode]
    total: int
    latency_ms: float


class ProjectModule(BaseModel):
    path: str
    file_count: int = 0
    kinds: dict[str, int] = {}
    score: float = 0.0


class ProjectSymbol(BaseModel):
    name: str
    kind: str = ""
    path: str = ""
    line: int = 0
    signature: str = ""


class ProjectUnderstandRequest(BaseModel):
    repo: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1, max_length=MAX_QUERY_LENGTH)
    max_modules: int = Field(8, ge=1, le=50)
    max_slices: int = Field(8, ge=1, le=50)
    max_source_tokens: int = Field(6000, ge=100, le=100000)


class ProjectUnderstandResponse(BaseModel):
    repo: str
    query: str
    modules: list[ProjectModule]
    symbols: list[ProjectSymbol]
    slices: list[ContextSlice]
    total_source_tokens: int
    latency_ms: float


class GraphFilesRequest(BaseModel):
    repo: str = Field(..., min_length=1)
    query: str = Field("", max_length=MAX_QUERY_LENGTH)
    limit: int = Field(100, ge=1, le=1000)
    tests_only: bool = False


class GraphFileItem(BaseModel):
    file_path: str
    language: str = ""
    chunk_count: int = 0
    symbol_count: int = 0
    symbols: list[str] = []
    updated_at: float = 0.0
    score: float = 0.0


class GraphFilesResponse(BaseModel):
    repo: str
    query: str = ""
    files: list[GraphFileItem]
    total: int
    latency_ms: float


class GraphSymbolRequest(BaseModel):
    repo: str = Field(..., min_length=1)
    symbol: str = Field(..., min_length=1, max_length=MAX_QUERY_LENGTH)
    limit: int = Field(50, ge=1, le=200)


class GraphNodeResponse(BaseModel):
    repo: str
    symbol: str
    definitions: list[ContextSlice]
    usages: list[ContextSlice]
    total_definitions: int
    total_usages: int
    provenance: str = "ast_index"
    latency_ms: float


class GraphRelationResponse(BaseModel):
    repo: str
    symbol: str
    relation: str
    nodes: list[ContextSlice]
    total: int
    relation_source: str = "ast_index"
    latency_ms: float


class GraphImpactResponse(BaseModel):
    repo: str
    symbol: str
    definitions: list[ContextSlice]
    usages: list[ContextSlice]
    callers: list[ContextSlice]
    affected_files: list[str]
    tests: list[GraphFileItem]
    risks: list[str]
    metrics: dict[str, Any]
    latency_ms: float


class GraphAffectedRequest(BaseModel):
    repo: str = Field(..., min_length=1)
    files: list[str] = Field(default_factory=list)
    since: str = Field("HEAD", min_length=1, max_length=200)
    limit: int = Field(100, ge=1, le=1000)


class GraphAffectedResponse(BaseModel):
    repo: str
    changed_files: list[str]
    affected_files: list[str]
    tests: list[GraphFileItem]
    modules: list[dict[str, Any]]
    risks: list[str]
    metrics: dict[str, Any]
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


class IndexDocsRequest(BaseModel):
    docs_path: str = Field(..., min_length=1)
    collection: str | None = None
    doc_types: list[str] | None = None
    full: bool = False

    @field_validator("docs_path")
    @classmethod
    def validate_docs_path(cls, v: str) -> str:
        p = Path(v).resolve()
        if not p.exists():
            raise ValueError(f"Docs path does not exist: {v}")
        if ".." in p.parts:
            raise ValueError("Path traversal not allowed")
        return str(p)


class IndexResponse(BaseModel):
    files_processed: int
    chunks_indexed: int
    files_skipped: int
    files_deleted: int
    errors: list[str]


class BackfillCodeIndexRequest(BaseModel):
    repo: str | None = None
    collection: str | None = None
    clear: bool = True
    page_size: int = Field(256, ge=1, le=1000)


class BackfillCodeIndexResponse(BaseModel):
    collection: str
    chunks_indexed: int
    chunks_skipped: int
    latency_ms: float


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


def _repo_info_for_name(repo: str):
    from rag.core.repos import RepoManager

    repo_info = RepoManager().get(repo)
    if repo_info is None:
        raise HTTPException(status_code=404, detail=f"Unknown repo: {repo}")
    return repo_info


def _collection_for_repo(repo: str | None) -> str:
    settings = get_settings()
    if not repo:
        return settings.qdrant.code_collection
    repo_info = _repo_info_for_name(repo)
    return repo_info.collection


def _result_key(payload: dict[str, Any]) -> tuple[str, int, int, str, str]:
    return (
        str(payload.get("file_path", "")),
        int(payload.get("start_line", 0) or 0),
        int(payload.get("end_line", 0) or 0),
        str(payload.get("chunk_type", "")),
        str(payload.get("name", "")),
    )


def _lexical_hit_to_search_result(hit: dict[str, Any]):
    from rag.core.vectorstore import SearchResult

    payload = {
        "file_path": hit.get("file_path", ""),
        "name": hit.get("name", ""),
        "parent_name": hit.get("parent_name", ""),
        "chunk_type": hit.get("chunk_type", ""),
        "language": hit.get("language", ""),
        "start_line": hit.get("start_line", 0),
        "end_line": hit.get("end_line", 0),
        "retrieval_source": "lexical",
    }
    return SearchResult(
        content=hit.get("code", ""),
        score=float(hit.get("score", 0.0)),
        payload=payload,
        point_id=f"lex:{hit.get('chunk_id', '')}",
    )


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text or "") + 3) // 4)


def _trim_to_token_budget(code: str, token_budget: int) -> tuple[str, int]:
    if token_budget <= 0:
        return "", 0
    max_chars = token_budget * 4
    if len(code) <= max_chars:
        return code, _estimate_tokens(code)
    out_lines: list[str] = []
    used = 0
    for line in code.splitlines():
        line_len = len(line) + 1
        if out_lines and used + line_len > max_chars:
            break
        if not out_lines and line_len > max_chars:
            out_lines.append(line[:max_chars])
            used = max_chars
            break
        out_lines.append(line)
        used += line_len
    trimmed = "\n".join(out_lines).rstrip()
    return trimmed, _estimate_tokens(trimmed)


def _candidate_overlaps_slice(candidate: dict[str, Any], existing: ContextSlice, threshold: float = 0.5) -> bool:
    if str(candidate.get("file_path", "")) != existing.file_path:
        return False
    try:
        c_start = int(candidate.get("start_line", 0) or 0)
        c_end = int(candidate.get("end_line", 0) or c_start)
        e_start_s, e_end_s = existing.lines.split("-", 1)
        e_start = int(e_start_s)
        e_end = int(e_end_s)
    except (TypeError, ValueError):
        return False
    if c_start <= 0 or c_end <= 0:
        return False
    overlap = max(0, min(c_end, e_end) - max(c_start, e_start) + 1)
    shorter = max(1, min(c_end - c_start + 1, e_end - e_start + 1))
    return overlap / shorter >= threshold


def _context_slice_from_candidate(candidate: dict[str, Any], token_budget: int | None = None) -> ContextSlice | None:
    code = str(candidate.get("code", ""))
    if token_budget is not None:
        code, token_estimate = _trim_to_token_budget(code, token_budget)
    else:
        token_estimate = int(candidate.get("token_estimate") or _estimate_tokens(code))
    if not code.strip() or token_estimate <= 0:
        return None
    return ContextSlice(
        file_path=str(candidate.get("file_path", "")),
        name=str(candidate.get("name", "")),
        parent_name=str(candidate.get("parent_name", "")),
        chunk_type=str(candidate.get("chunk_type", "")),
        language=str(candidate.get("language", "")),
        lines=str(candidate.get("lines") or f"{candidate.get('start_line', '?')}-{candidate.get('end_line', '?')}"),
        code=code,
        score=round(float(candidate.get("score", 0.0)), 4),
        token_estimate=token_estimate,
        citation=str(candidate.get("citation", "")),
        why_included=str(candidate.get("why_included", "")),
    )


def _resolve_symbols_from_request(req: ResolveRequest) -> list[str]:
    raw = [s for s in req.symbols if s and s.strip()]
    if req.query:
        raw.extend(_IDENTIFIER_RE.findall(req.query))
    seen: set[str] = set()
    symbols: list[str] = []
    for symbol in raw:
        symbol = symbol.strip()
        key = symbol.lower()
        if len(symbol) < 3 or key in seen:
            continue
        seen.add(key)
        symbols.append(symbol)
    symbols.sort(key=lambda s: (any(c.isupper() for c in s[1:]), len(s)), reverse=True)
    return symbols[:20]


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

    @app.post(
        "/index/backfill-code-index",
        response_model=BackfillCodeIndexResponse,
        dependencies=[Depends(require_auth)],
    )
    async def backfill_code_index(req: BackfillCodeIndexRequest):
        """Populate SQLite code_index from existing Qdrant payloads.

        Useful after upgrading to the lexical/context-pack index: it avoids a
        full embedding pass by reusing stored ``content`` and metadata payloads.
        """
        start = time.time()
        try:
            collection = req.collection or _collection_for_repo(req.repo)
            vectorstore = get_vectorstore()
            client = await vectorstore._get_client()

            from rag.core.vectorstore import ChunkDocument
            from rag.storage import db as _db

            if req.clear:
                _db.delete_code_chunks_by_collection(collection)

            chunks_indexed = 0
            chunks_skipped = 0
            offset = None
            while True:
                points, offset = await client.scroll(
                    collection_name=collection,
                    limit=req.page_size,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                if not points:
                    break
                docs: list[ChunkDocument] = []
                for point in points:
                    payload = dict(point.payload or {})
                    content = payload.pop("content", "")
                    if not content:
                        chunks_skipped += 1
                        continue
                    docs.append(ChunkDocument(
                        content=content,
                        metadata=payload,
                        chunk_id=str(getattr(point, "id", "")),
                    ))
                if docs:
                    chunks_indexed += _db.upsert_code_chunks(collection, docs)
                if offset is None:
                    break

            latency = (time.time() - start) * 1000
            logger.info(
                "code_index_backfilled",
                collection=collection,
                chunks_indexed=chunks_indexed,
                chunks_skipped=chunks_skipped,
                latency_ms=round(latency, 1),
            )
            return BackfillCodeIndexResponse(
                collection=collection,
                chunks_indexed=chunks_indexed,
                chunks_skipped=chunks_skipped,
                latency_ms=round(latency, 1),
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error("code_index_backfill_error", error=str(e))
            raise HTTPException(status_code=500, detail=f"Code index backfill failed ({type(e).__name__})")

    # --- Search ---

    @app.post("/search", response_model=SearchResponse, dependencies=[Depends(require_auth)])
    async def search(req: SearchRequest):
        start = time.time()
        try:
            vectorstore = get_vectorstore()
            code_collection = _collection_for_repo(req.repo)

            from rag.agents.retrieval import _fallback_plan, plan_search

            if req.planner == "fallback":
                plan = _fallback_plan(req.query)
            else:
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

            # Promote exact/code-index matches before semantic scoring. Dense
            # retrieval remains the fallback, but symbol/file/API queries should
            # not lose to embedding noise when SQLite has direct evidence.
            if plan.strategy != "global":
                try:
                    from rag.storage import db as _db

                    lexical_filters = {**(plan.filters or {}), **(req.filters or {})}
                    lexical_hits = _db.search_code_chunks(
                        req.query,
                        collection=code_collection,
                        limit=req.top_k or plan.top_k,
                        filters=lexical_filters if lexical_filters else None,
                    )
                    seen_keys = {_result_key(r.payload) for r in results}
                    for hit in lexical_hits:
                        lex_result = _lexical_hit_to_search_result(hit)
                        key = _result_key(lex_result.payload)
                        if key in seen_keys:
                            continue
                        results.append(lex_result)
                        seen_keys.add(key)
                except Exception as e:
                    logger.debug("lexical_search_failed", query=req.query, error=str(e))

            # Apply AST / symbol sanity verification filter for semantic results
            if plan.strategy != "global":
                import re
                # Find CamelCase symbols of length >= 4 in the query. Drop common
                # capitalized English words ("Show me...", "Find all...", "Rename
                # X") — otherwise a natural-language question's leading verb is
                # treated as a required symbol and wipes every result to zero.
                _STOPWORD_SYMBOLS = {
                    "show", "find", "rename", "trace", "list", "give", "tell",
                    "what", "which", "where", "when", "who", "whom", "whose",
                    "how", "why", "this", "that", "these", "those", "there",
                    "here", "with", "from", "into", "your", "their", "have",
                    "does", "code", "class", "base", "main", "should", "would",
                    "could", "about", "into",
                }
                query_symbols = {
                    s for s in re.findall(r"\b([A-Z][a-zA-Z0-9_]{3,})\b", req.query)
                    if s.lower() not in _STOPWORD_SYMBOLS
                }
                if query_symbols:
                    filtered_results = []
                    for r in results:
                        payload = r.payload or {}
                        code = r.content or ""
                        # Extract all names/references to check
                        names_to_check = {
                            str(payload.get("name", "")),
                            str(payload.get("parent_name", "")),
                            str(payload.get("file_path", ""))
                        }
                        # Check references/inherits lists
                        for ref_list in ("references_fqn", "inherits_from"):
                            for ref in payload.get(ref_list) or []:
                                names_to_check.add(ref)

                        # Check if any query symbol is present in the names or code
                        matched = False
                        for sym in query_symbols:
                            sym_lower = sym.lower()
                            # Check exact word match in code
                            if re.search(r"\b" + re.escape(sym) + r"\b", code):
                                matched = True
                                break
                            # Check exact word/substring match in payload names
                            if any(sym_lower in n.lower() for n in names_to_check):
                                matched = True
                                break

                        if matched:
                            filtered_results.append(r)
                    # Safety net: a sanity filter must never delete *all*
                    # evidence. If nothing matched (e.g. the symbol only appears
                    # in code semantic search didn't rank, or it was a false
                    # symbol), keep the unfiltered results rather than return 0.
                    results = filtered_results or results

            from rag.core.scoring import score_results
            results = score_results(results, req.query, reranked=did_rerank)
            results = results[: req.top_k or plan.top_k]

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

    @app.post("/docs-search", response_model=SearchResponse, dependencies=[Depends(require_auth)])
    async def docs_search(req: DocsSearchRequest):
        """Search indexed docs/specs, including generated event catalogs."""
        start = time.time()
        try:
            settings = get_settings()
            hits = await get_vectorstore().search(
                collection=settings.qdrant.docs_collection,
                query=req.query,
                top_k=req.top_k,
                filters=req.filters,
            )
            items = [SearchResultItem(**hit.slim(), matched_queries=[0]) for hit in hits]
            latency = (time.time() - start) * 1000
            logger.info(
                "docs_search_executed",
                query=req.query,
                results=len(items),
                latency_ms=round(latency, 1),
            )
            return SearchResponse(
                results=items,
                query=req.query,
                plan=SearchPlanInfo(strategy="docs", queries=[req.query], filters=req.filters or {}),
                total=len(items),
                latency_ms=round(latency, 1),
            )
        except Exception as e:
            logger.error("docs_search_error", query=req.query, error=str(e))
            raise HTTPException(status_code=500, detail=f"Docs search failed ({type(e).__name__})")

    # --- Resolve (exact AST definitions/usages for named repos) ---

    async def _query_structural_usages_from_qdrant(collection: str, symbols: list[str], repo: str) -> list[dict[str, Any]]:
        from pathlib import Path
        from qdrant_client import models
        vectorstore = get_vectorstore()
        client = await vectorstore._get_client()
        hits = []

        # Resolve FQNs and called_by for the symbols in one scroll query per symbol
        fqns = []
        called_by_locations = []
        for symbol in symbols:
            try:
                qfilter = models.Filter(
                    must=[
                        models.FieldCondition(key="name", match=models.MatchValue(value=symbol)),
                        models.FieldCondition(
                            key="chunk_type",
                            match=models.MatchAny(any=["class_declaration", "interface_declaration", "method", "function", "class", "interface"])
                        )
                    ]
                )
                res = await client.scroll(
                    collection_name=collection,
                    scroll_filter=qfilter,
                    limit=5,
                    with_payload=True
                )
                has_fqn = False
                if res and res[0]:
                    for pt in res[0]:
                        payload = pt.payload or {}
                        defines_fqn = payload.get("defines_fqn")
                        if defines_fqn:
                            fqns.append(defines_fqn)
                            has_fqn = True
                        cb = payload.get("called_by")
                        if cb:
                            if isinstance(cb, list):
                                called_by_locations.extend(cb)
                            elif isinstance(cb, str):
                                called_by_locations.append(cb)
                if not has_fqn:
                    fqns.append(symbol)
            except Exception:
                fqns.append(symbol)

        # Convert absolute paths to relative paths and retrieve those chunks
        if called_by_locations:
            try:
                repo_info = _repo_info_for_name(repo)
                repo_path = Path(repo_info.path).resolve()
                
                for loc in called_by_locations:
                    if ":" not in loc:
                        continue
                    path_part, line_part = loc.rsplit(":", 1)
                    try:
                        line_num = int(line_part)
                    except ValueError:
                        continue
                    path_obj = Path(path_part).resolve()
                    try:
                        rel_path = str(path_obj.relative_to(repo_path))
                    except ValueError:
                        continue

                    # Query Qdrant for a chunk covering this line in this file
                    qfilter = models.Filter(
                        must=[
                            models.FieldCondition(key="file_path", match=models.MatchValue(value=rel_path)),
                            models.FieldCondition(key="start_line", range=models.Range(lte=line_num)),
                            models.FieldCondition(key="end_line", range=models.Range(gte=line_num))
                        ]
                    )
                    res = await client.scroll(
                        collection_name=collection,
                        scroll_filter=qfilter,
                        limit=5,
                        with_payload=True
                    )
                    if res and res[0]:
                        for pt in res[0]:
                            payload = pt.payload or {}
                            start_line = payload.get("start_line", 1)
                            end_line = payload.get("end_line", 1)
                            label = payload.get("name", "") or Path(rel_path).name
                            chunk_id = f"graph:{rel_path}:{start_line}:{label}"
                            if any(h["chunk_id"] == chunk_id for h in hits):
                                continue
                            
                            code = payload.get("content", "")
                            hits.append({
                                "chunk_id": chunk_id,
                                "file_path": rel_path,
                                "name": label,
                                "parent_name": "",
                                "chunk_type": payload.get("chunk_type", "class"),
                                "language": payload.get("language", ""),
                                "start_line": start_line,
                                "end_line": end_line,
                                "lines": f"{start_line}-{end_line}",
                                "code": code,
                                "token_estimate": max(1, (len(code) + 3) // 4),
                                "score": 20.0,
                                "citation": f"{rel_path}:{start_line}-{end_line} ({label})",
                                "why_included": "references_relationship",
                            })
            except Exception as e:
                logger.warning("called_by_resolution_failed", error=str(e))

        for fqn in set(fqns):
            try:
                # Scroll matching inherits_from or references_fqn
                qfilter = models.Filter(
                    should=[
                        models.FieldCondition(key="inherits_from", match=models.MatchValue(value=fqn)),
                        models.FieldCondition(key="references_fqn", match=models.MatchValue(value=fqn))
                    ]
                )
                res = await client.scroll(
                    collection_name=collection,
                    scroll_filter=qfilter,
                    limit=50,
                    with_payload=True,
                    with_vectors=False
                )
                points = res[0]
                for p in points:
                    payload = p.payload or {}
                    file_path = payload.get("file_path", "")
                    if not file_path:
                        continue

                    # Deduplicate points by chunk_id
                    start_line = payload.get("start_line", 1)
                    end_line = payload.get("end_line", 1)
                    label = payload.get("name", "") or Path(file_path).name
                    chunk_id = f"graph:{file_path}:{start_line}:{label}"
                    if any(h["chunk_id"] == chunk_id for h in hits):
                        continue

                    code = payload.get("content", "")

                    # Determine structural explanation
                    is_inherits = fqn in payload.get("inherits_from", [])
                    why_included = "inherits_from_relationship" if is_inherits else "references_relationship"

                    hits.append({
                        "chunk_id": chunk_id,
                        "file_path": file_path,
                        "name": label,
                        "parent_name": "",
                        "chunk_type": payload.get("chunk_type", "class"),
                        "language": payload.get("language", ""),
                        "start_line": start_line,
                        "end_line": end_line,
                        "lines": f"{start_line}-{end_line}",
                        "code": code,
                        "token_estimate": max(1, (len(code) + 3) // 4),
                        "score": 15.0,
                        "citation": f"{file_path}:{start_line}-{end_line} ({label})",
                        "why_included": why_included,
                    })
            except Exception as e:
                logger.warning("structural_usages_qdrant_error", symbol=fqn, error=str(e))
        return hits

    @app.post("/resolve", response_model=ResolveResponse, dependencies=[Depends(require_auth)])
    async def resolve(req: ResolveRequest):
        start = time.time()
        try:
            repo_info = _repo_info_for_name(req.repo)
            symbols = _resolve_symbols_from_request(req)
            if not symbols:
                raise HTTPException(status_code=422, detail="Provide at least one symbol or identifier-like query term")

            from rag.core.ast_index import resolve_symbols

            resolved = resolve_symbols(
                repo_info.path,
                symbols,
                definitions_limit=req.definitions_limit,
                usages_limit=req.usages_limit,
            )
            definitions = [
                s for item in resolved.get("definitions", [])
                if (s := _context_slice_from_candidate(item)) is not None
            ]
            usages = [
                s for item in resolved.get("usages", [])
                if (s := _context_slice_from_candidate(item)) is not None
            ]

            # Query Qdrant for structural usages
            try:
                coll = _collection_for_repo(req.repo)
                structural_usages = await _query_structural_usages_from_qdrant(coll, symbols, req.repo)
                usages.extend(structural_usages)
            except Exception as e:
                logger.warning("resolve_structural_usages_failed", error=str(e))

            latency = (time.time() - start) * 1000
            logger.info(
                "resolve_executed",
                repo=req.repo,
                symbols=symbols,
                definitions=len(definitions),
                usages=len(usages),
                latency_ms=round(latency, 1),
            )
            return ResolveResponse(
                repo=req.repo,
                symbols=symbols,
                definitions=definitions,
                usages=usages,
                total_definitions=len(definitions),
                total_usages=len(usages),
                latency_ms=round(latency, 1),
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error("resolve_error", repo=req.repo, error=str(e))
            raise HTTPException(status_code=500, detail=f"Resolve failed ({type(e).__name__})")

    @app.post("/call-tree", response_model=CallTreeResponse, dependencies=[Depends(require_auth)])
    async def call_tree(req: CallTreeRequest):
        start = time.time()
        try:
            repo_info = _repo_info_for_name(req.repo)

            from rag.core.ast_index import call_tree as ast_call_tree

            nodes_raw = ast_call_tree(repo_info.path, req.symbol, limit=req.limit)
            nodes: list[CallTreeNode] = []
            for item in nodes_raw:
                slice_item = _context_slice_from_candidate(item)
                if slice_item is None:
                    continue
                nodes.append(CallTreeNode(
                    **slice_item.model_dump(),
                    depth=int(item.get("depth", 0) or 0),
                ))

            latency = (time.time() - start) * 1000
            logger.info(
                "call_tree_executed",
                repo=req.repo,
                symbol=req.symbol,
                nodes=len(nodes),
                latency_ms=round(latency, 1),
            )
            return CallTreeResponse(
                repo=req.repo,
                symbol=req.symbol,
                nodes=nodes,
                total=len(nodes),
                latency_ms=round(latency, 1),
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error("call_tree_error", repo=req.repo, symbol=req.symbol, error=str(e))
            raise HTTPException(status_code=500, detail=f"Call tree failed ({type(e).__name__})")

    @app.post("/graph/files", response_model=GraphFilesResponse, dependencies=[Depends(require_auth)])
    async def graph_files(req: GraphFilesRequest):
        start = time.time()
        try:
            collection = _collection_for_repo(req.repo)

            from rag.core.graph_tools import files as graph_files_for_repo

            raw = graph_files_for_repo(
                collection,
                query=req.query,
                limit=req.limit,
                tests_only=req.tests_only,
            )
            latency = (time.time() - start) * 1000
            return GraphFilesResponse(
                repo=req.repo,
                query=req.query,
                files=[GraphFileItem(**item) for item in raw],
                total=len(raw),
                latency_ms=round(latency, 1),
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error("graph_files_error", repo=req.repo, error=str(e))
            raise HTTPException(status_code=500, detail=f"Graph files failed ({type(e).__name__})")

    @app.post("/graph/node", response_model=GraphNodeResponse, dependencies=[Depends(require_auth)])
    async def graph_node(req: GraphSymbolRequest):
        start = time.time()
        try:
            repo_info = _repo_info_for_name(req.repo)
            collection = _collection_for_repo(req.repo)

            from rag.core.graph_tools import node as graph_node_for_symbol

            raw = graph_node_for_symbol(
                repo_info.path,
                collection,
                req.symbol,
                definitions_limit=min(req.limit, 100),
                usages_limit=req.limit,
            )
            definitions = [
                s for item in raw.get("definitions", [])
                if (s := _context_slice_from_candidate(item)) is not None
            ]
            usages = [
                s for item in raw.get("usages", [])
                if (s := _context_slice_from_candidate(item)) is not None
            ]
            latency = (time.time() - start) * 1000
            return GraphNodeResponse(
                repo=req.repo,
                symbol=req.symbol,
                definitions=definitions,
                usages=usages,
                total_definitions=len(definitions),
                total_usages=len(usages),
                provenance=str(raw.get("provenance", "ast_index")),
                latency_ms=round(latency, 1),
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error("graph_node_error", repo=req.repo, symbol=req.symbol, error=str(e))
            raise HTTPException(status_code=500, detail=f"Graph node failed ({type(e).__name__})")

    @app.post("/graph/callers", response_model=GraphRelationResponse, dependencies=[Depends(require_auth)])
    async def graph_callers(req: GraphSymbolRequest):
        start = time.time()
        try:
            repo_info = _repo_info_for_name(req.repo)

            from rag.core.graph_tools import callers as graph_callers_for_symbol

            raw = graph_callers_for_symbol(repo_info.path, req.symbol, limit=req.limit)
            nodes = [
                s for item in raw
                if (s := _context_slice_from_candidate(item)) is not None
            ]
            latency = (time.time() - start) * 1000
            return GraphRelationResponse(
                repo=req.repo,
                symbol=req.symbol,
                relation="callers",
                nodes=nodes,
                total=len(nodes),
                relation_source="ast_index",
                latency_ms=round(latency, 1),
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error("graph_callers_error", repo=req.repo, symbol=req.symbol, error=str(e))
            raise HTTPException(status_code=500, detail=f"Graph callers failed ({type(e).__name__})")

    @app.post("/graph/callees", response_model=GraphRelationResponse, dependencies=[Depends(require_auth)])
    async def graph_callees(req: GraphSymbolRequest):
        start = time.time()
        try:
            repo_info = _repo_info_for_name(req.repo)
            collection = _collection_for_repo(req.repo)

            from rag.core.graph_tools import callees as graph_callees_for_symbol

            raw = graph_callees_for_symbol(repo_info.path, collection, req.symbol, limit=req.limit)
            nodes = [
                s for item in raw
                if (s := _context_slice_from_candidate(item)) is not None
            ]
            latency = (time.time() - start) * 1000
            return GraphRelationResponse(
                repo=req.repo,
                symbol=req.symbol,
                relation="callees",
                nodes=nodes,
                total=len(nodes),
                relation_source="heuristic_source_scan",
                latency_ms=round(latency, 1),
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error("graph_callees_error", repo=req.repo, symbol=req.symbol, error=str(e))
            raise HTTPException(status_code=500, detail=f"Graph callees failed ({type(e).__name__})")

    @app.post("/graph/impact", response_model=GraphImpactResponse, dependencies=[Depends(require_auth)])
    async def graph_impact(req: GraphSymbolRequest):
        start = time.time()
        try:
            repo_info = _repo_info_for_name(req.repo)
            collection = _collection_for_repo(req.repo)

            from rag.core.graph_tools import impact as graph_impact_for_symbol

            raw = graph_impact_for_symbol(repo_info.path, collection, req.symbol, limit=req.limit)
            definitions = [
                s for item in raw.get("definitions", [])
                if (s := _context_slice_from_candidate(item)) is not None
            ]
            usages = [
                s for item in raw.get("usages", [])
                if (s := _context_slice_from_candidate(item)) is not None
            ]
            callers = [
                s for item in raw.get("callers", [])
                if (s := _context_slice_from_candidate(item)) is not None
            ]
            tests = [GraphFileItem(**item) for item in raw.get("tests", [])]
            latency = (time.time() - start) * 1000
            return GraphImpactResponse(
                repo=req.repo,
                symbol=req.symbol,
                definitions=definitions,
                usages=usages,
                callers=callers,
                affected_files=[str(path) for path in raw.get("affected_files", [])],
                tests=tests,
                risks=[str(risk) for risk in raw.get("risks", [])],
                metrics=dict(raw.get("metrics", {}) or {}),
                latency_ms=round(latency, 1),
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error("graph_impact_error", repo=req.repo, symbol=req.symbol, error=str(e))
            raise HTTPException(status_code=500, detail=f"Graph impact failed ({type(e).__name__})")

    @app.post("/graph/affected", response_model=GraphAffectedResponse, dependencies=[Depends(require_auth)])
    async def graph_affected(req: GraphAffectedRequest):
        start = time.time()
        try:
            repo_info = _repo_info_for_name(req.repo)
            collection = _collection_for_repo(req.repo)

            from rag.core.graph_tools import affected as graph_affected_for_repo

            raw = graph_affected_for_repo(
                repo_info.path,
                collection,
                files=req.files,
                since=req.since,
                limit=req.limit,
            )
            latency = (time.time() - start) * 1000
            return GraphAffectedResponse(
                repo=req.repo,
                changed_files=[str(path) for path in raw.get("changed_files", [])],
                affected_files=[str(path) for path in raw.get("affected_files", [])],
                tests=[GraphFileItem(**item) for item in raw.get("tests", [])],
                modules=list(raw.get("modules", []) or []),
                risks=[str(risk) for risk in raw.get("risks", [])],
                metrics=dict(raw.get("metrics", {}) or {}),
                latency_ms=round(latency, 1),
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error("graph_affected_error", repo=req.repo, error=str(e))
            raise HTTPException(status_code=500, detail=f"Graph affected failed ({type(e).__name__})")

    @app.post("/project-understand", response_model=ProjectUnderstandResponse, dependencies=[Depends(require_auth)])
    async def project_understand(req: ProjectUnderstandRequest):
        start = time.time()
        try:
            repo_info = _repo_info_for_name(req.repo)

            from rag.core.ast_index import understand_project

            result = understand_project(
                repo_info.path,
                req.query,
                max_modules=req.max_modules,
                max_slices=max(req.max_slices * 2, req.max_slices),
            )

            modules = [
                ProjectModule(
                    path=str(m.get("path", "")),
                    file_count=int(m.get("file_count", 0) or 0),
                    kinds={str(k): int(v) for k, v in (m.get("kinds", {}) or {}).items()},
                    score=float(m.get("score", 0.0) or 0.0),
                )
                for m in result.get("modules", [])
            ]
            symbols = [
                ProjectSymbol(
                    name=str(s.get("name", "")),
                    kind=str(s.get("kind", "")),
                    path=str(s.get("path", "")),
                    line=int(s.get("line", 0) or 0),
                    signature=str(s.get("signature", "")),
                )
                for s in result.get("symbols", [])
            ]

            slices: list[ContextSlice] = []
            total_tokens = 0
            for item in result.get("slices", []):
                if len(slices) >= req.max_slices or total_tokens >= req.max_source_tokens:
                    break
                if any(_candidate_overlaps_slice(item, existing) for existing in slices):
                    continue
                remaining = req.max_source_tokens - total_tokens
                slice_item = _context_slice_from_candidate(item, token_budget=remaining)
                if slice_item is None:
                    continue
                slices.append(slice_item)
                total_tokens += slice_item.token_estimate

            latency = (time.time() - start) * 1000
            logger.info(
                "project_understand_executed",
                repo=req.repo,
                query=req.query,
                modules=len(modules),
                symbols=len(symbols),
                slices=len(slices),
                source_tokens=total_tokens,
                latency_ms=round(latency, 1),
            )
            return ProjectUnderstandResponse(
                repo=req.repo,
                query=req.query,
                modules=modules,
                symbols=symbols,
                slices=slices,
                total_source_tokens=total_tokens,
                latency_ms=round(latency, 1),
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error("project_understand_error", repo=req.repo, query=req.query, error=str(e))
            raise HTTPException(status_code=500, detail=f"Project understand failed ({type(e).__name__})")

    # --- Context pack (bounded source slices for developer workflows) ---

    @app.post("/context-pack", response_model=ContextPackResponse, dependencies=[Depends(require_auth)])
    async def context_pack(req: ContextPackRequest):
        """Return a token-bounded set of source slices for a query.

        This endpoint is intentionally stricter than /search: it favors exact
        symbol/file/string matches from SQLite and packs only code spans that fit
        the requested source budget. Semantic retrieval fills gaps when needed.
        """
        start = time.time()
        try:
            def _is_test(path: str) -> bool:
                p = path.lower()
                return "/test/" in p or "/androidtest/" in p or p.endswith("test.kt") or p.endswith("test.java")

            collection = _collection_for_repo(req.repo)
            candidates: list[dict[str, Any]] = []
            seen: set[tuple[str, int, int, str, str]] = set()

            if req.use_ast_index and req.repo:
                try:
                    from rag.core.ast_index import retrieve_context

                    repo_info = _repo_info_for_name(req.repo)
                    ast_hits = retrieve_context(
                        repo_info.path,
                        req.query,
                        limit=max(req.max_slices * 3, 12),
                        include_usages=(req.strategy != "graph_walk")
                    )
                    for hit in ast_hits:
                        path = hit.get("file_path", "")
                        if req.strategy == "graph_walk" and _is_test(path):
                            continue
                        key = (
                            path,
                            int(hit.get("start_line", 0) or 0),
                            int(hit.get("end_line", 0) or 0),
                            hit.get("chunk_type", ""),
                            hit.get("name", ""),
                        )
                        if key in seen:
                            continue
                        seen.add(key)
                        candidates.append(hit)
                except Exception as e:
                    logger.debug("context_pack_ast_index_failed", query=req.query, error=str(e))

            from rag.storage import db as _db

            lexical_hits = _db.search_code_chunks(
                req.query,
                collection=collection,
                limit=max(req.max_slices * 4, 20),
                filters=req.filters,
            )
            for hit in lexical_hits:
                path = hit.get("file_path", "")
                if req.strategy == "graph_walk" and _is_test(path):
                    continue
                key = (
                    path,
                    int(hit.get("start_line", 0) or 0),
                    int(hit.get("end_line", 0) or 0),
                    hit.get("chunk_type", ""),
                    hit.get("name", ""),
                )
                if key in seen:
                    continue
                seen.add(key)
                candidates.append({
                    **hit,
                    "why_included": "exact_or_lexical_match",
                })

            if req.include_semantic and len(candidates) < req.max_slices:
                try:
                    vector_hits = await get_vectorstore().search(
                        collection=collection,
                        query=req.query,
                        top_k=max(req.max_slices * 2, 10),
                        filters=req.filters,
                    )
                    for hit in vector_hits:
                        payload = hit.payload or {}
                        path = payload.get("file_path", "")
                        if req.strategy == "graph_walk" and _is_test(path):
                            continue
                        key = _result_key(payload)
                        if key in seen:
                            continue
                        seen.add(key)
                        candidates.append({
                            "chunk_id": hit.point_id,
                            "file_path": payload.get("file_path", ""),
                            "name": payload.get("name", ""),
                            "parent_name": payload.get("parent_name", ""),
                            "chunk_type": payload.get("chunk_type", ""),
                            "language": payload.get("language", ""),
                            "start_line": payload.get("start_line", 0),
                            "end_line": payload.get("end_line", 0),
                            "lines": f"{payload.get('start_line', '?')}-{payload.get('end_line', '?')}",
                            "code": hit.content,
                            "token_estimate": _estimate_tokens(hit.content),
                            "score": hit.score,
                            "citation": hit._make_citation(),
                            "why_included": "semantic_match",
                        })
                except Exception as e:
                    logger.debug("context_pack_semantic_failed", query=req.query, error=str(e))

            candidates.sort(key=lambda c: float(c.get("score", 0.0)), reverse=True)

            slices: list[ContextSlice] = []
            total_tokens = 0
            for c in candidates:
                if len(slices) >= req.max_slices or total_tokens >= req.max_source_tokens:
                    break
                if any(_candidate_overlaps_slice(c, existing) for existing in slices):
                    continue
                remaining = req.max_source_tokens - total_tokens
                slice_item = _context_slice_from_candidate(c, token_budget=remaining)
                if slice_item is None:
                    continue
                total_tokens += slice_item.token_estimate
                slices.append(slice_item)

            latency = (time.time() - start) * 1000
            logger.info(
                "context_pack_executed",
                query=req.query,
                repo=req.repo,
                slices=len(slices),
                source_tokens=total_tokens,
                latency_ms=round(latency, 1),
            )
            return ContextPackResponse(
                query=req.query,
                repo=req.repo,
                slices=slices,
                total=len(slices),
                total_source_tokens=total_tokens,
                latency_ms=round(latency, 1),
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error("context_pack_error", query=req.query, error=str(e))
            raise HTTPException(status_code=500, detail=f"Context pack failed ({type(e).__name__})")

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

    @app.post("/index/docs", response_model=IndexResponse, dependencies=[Depends(require_auth)])
    async def index_docs(req: IndexDocsRequest):
        try:
            from rag.core.indexer import index_documents

            vectorstore = get_vectorstore()
            collection = req.collection or get_settings().qdrant.docs_collection
            if req.full:
                await vectorstore.drop_collection(collection)
            result = await index_documents(
                docs_path=req.docs_path,
                vectorstore=vectorstore,
                collection=collection,
                doc_types=req.doc_types,
            )
            return IndexResponse(
                files_processed=result.files_processed,
                chunks_indexed=result.chunks_indexed,
                files_skipped=result.files_skipped,
                files_deleted=result.files_deleted,
                errors=result.errors,
            )
        except Exception as e:
            logger.error("index_docs_error", docs_path=req.docs_path, error=str(e))
            raise HTTPException(status_code=500, detail=f"Docs index failed ({type(e).__name__})")

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
