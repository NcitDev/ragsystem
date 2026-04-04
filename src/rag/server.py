"""FastAPI server with search, index, and status routes."""

from __future__ import annotations

import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from rag.config import get_settings
from rag.core.embedder import HybridEmbedder
from rag.core.reranker import Reranker
from rag.core.vectorstore import QdrantVectorStore

logger = structlog.get_logger()

MAX_QUERY_LENGTH = 2000
MAX_TOP_K = 200


# --- Request/Response Models with Validation ---


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=MAX_QUERY_LENGTH)
    top_k: int | None = Field(None, ge=1, le=MAX_TOP_K)
    filters: dict[str, Any] | None = None
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


class HealthResponse(BaseModel):
    status: str
    components: dict[str, str]


class StatusResponse(BaseModel):
    status: str
    embedder_provider: str
    embedder_model: str
    reranker_model: str
    reranker_enabled: bool
    collections: list[dict[str, Any]]
    uptime_seconds: float


class ErrorResponse(BaseModel):
    error: str
    code: str
    detail: str | None = None


# --- Shared State ---

_state: dict[str, Any] = {}
_request_times: deque = deque(maxlen=100)  # Simple rate limiting window


def get_vectorstore() -> QdrantVectorStore:
    return _state["vectorstore"]


def get_reranker() -> Reranker:
    return _state["reranker"]


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
        reranker = Reranker()

        _state["vectorstore"] = vectorstore
        _state["reranker"] = reranker
        _state["embedder"] = embedder
        _state["start_time"] = time.time()

        logger.info("server_ready", embedder_provider=embedder.provider)
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

    # --- Rate limiting middleware ---

    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        now = time.time()
        # Clean old entries (sliding window of 60 seconds)
        while _request_times and _request_times[0] < now - 60:
            _request_times.popleft()
        if len(_request_times) >= 120:  # 120 requests per minute
            return JSONResponse(
                status_code=429,
                content={"error": "Rate limit exceeded", "code": "RATE_LIMITED", "detail": "Max 120 req/min"},
            )
        _request_times.append(now)
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

        # Reranker
        components["reranker"] = "enabled" if get_settings().reranker.enabled else "disabled"

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

    @app.get("/status", response_model=StatusResponse)
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

    @app.post("/search", response_model=SearchResponse)
    async def search(req: SearchRequest):
        start = time.time()
        try:
            settings = get_settings()
            vectorstore = get_vectorstore()
            reranker = get_reranker()

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
                # Traverse graph from seed results
                related_nodes: set[str] = set()
                for sr in seed_results:
                    node_id = f"{sr.payload.get('file_path', '')}:{sr.payload.get('parent_name', '')}.{sr.payload.get('name', '')}".replace(".:",":")
                    connected = graph.traverse(node_id, max_hops=2)
                    related_nodes.update(connected)

                # Fetch chunks for related nodes via file_path filter
                related_files = {n.split(":")[0] for n in related_nodes if ":" in n}
                results = []
                for fp in list(related_files)[:10]:
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

            # Rerank (skip for naive and global modes)
            if req.rerank and results and plan.strategy not in ("naive", "global"):
                try:
                    results = reranker.rerank(req.query, results)
                except Exception as e:
                    logger.warning("rerank_degraded", error=str(e))

            # Apply weighted relevance scoring
            from rag.core.scoring import score_results
            results = score_results(results, req.query)

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

    @app.post("/index", response_model=IndexResponse)
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

    @app.get("/overview")
    async def overview():
        """Aggregate codebase metadata: languages, patterns, complexity stats."""
        try:
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
                    for pat in p.payload.get("patterns", []):
                        patterns[pat] = patterns.get(pat, 0) + 1
                    cc = p.payload.get("complexity_cyclomatic")
                    if cc is not None and isinstance(cc, (int, float)):
                        complexities.append(int(cc))
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

    return app


app = create_app()
