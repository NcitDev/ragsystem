"""FastAPI server with search, index, and status routes."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI
from pydantic import BaseModel

from rag.config import get_settings
from rag.core.embedder import HybridEmbedder
from rag.core.reranker import Reranker
from rag.core.vectorstore import QdrantVectorStore

logger = structlog.get_logger()


class SearchRequest(BaseModel):
    query: str
    top_k: int | None = None
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


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    query: str
    total: int
    latency_ms: float


class IndexRequest(BaseModel):
    repo_path: str
    full: bool = False
    languages: list[str] | None = None


class IndexResponse(BaseModel):
    files_processed: int
    chunks_indexed: int
    files_skipped: int
    files_deleted: int
    errors: list[str]


class StatusResponse(BaseModel):
    status: str
    embedder_provider: str
    embedder_model: str
    reranker_model: str
    reranker_enabled: bool
    collections: list[dict[str, Any]]
    uptime_seconds: float


# Shared state
_state: dict[str, Any] = {}


def get_vectorstore() -> QdrantVectorStore:
    return _state["vectorstore"]


def get_reranker() -> Reranker:
    return _state["reranker"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and tear down shared resources."""
    settings = get_settings()
    logger.info("server_starting", host=settings.server.host, port=settings.server.port)

    embedder = HybridEmbedder()
    await embedder.initialize()

    vectorstore = QdrantVectorStore(embedder=embedder)
    # Eagerly open Qdrant client so it's ready for all requests
    await vectorstore._get_client()
    reranker = Reranker()

    _state["vectorstore"] = vectorstore
    _state["reranker"] = reranker
    _state["embedder"] = embedder
    _state["start_time"] = time.time()

    logger.info("server_ready", embedder_provider=embedder.provider)
    yield

    await vectorstore.close()
    logger.info("server_stopped")


def create_app() -> FastAPI:
    app = FastAPI(title="RAG System", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/status", response_model=StatusResponse)
    async def status():
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

    @app.post("/search", response_model=SearchResponse)
    async def search(req: SearchRequest):
        start = time.time()
        settings = get_settings()
        vectorstore = get_vectorstore()
        reranker = get_reranker()

        # Use agent to plan search strategy
        from rag.agents.retrieval import plan_search

        plan = await plan_search(req.query)

        # Execute search plan
        all_results = []
        for q in plan.queries:
            merged_filters = {**(plan.filters or {}), **(req.filters or {})}
            results = await vectorstore.search(
                collection=settings.qdrant.code_collection,
                query=q,
                top_k=req.top_k or plan.top_k,
                filters=merged_filters if merged_filters else None,
            )
            all_results.extend(results)

        # Deduplicate by point_id
        seen = set()
        results = []
        for r in all_results:
            if r.point_id not in seen:
                seen.add(r.point_id)
                results.append(r)

        # Rerank
        if req.rerank and results:
            results = reranker.rerank(req.query, results)

        latency = (time.time() - start) * 1000

        # Log for TUI
        logger.info(
            "query_executed",
            query=req.query,
            results=len(results),
            latency_ms=round(latency, 1),
        )

        return SearchResponse(
            results=[SearchResultItem(**r.slim()) for r in results],
            query=req.query,
            total=len(results),
            latency_ms=round(latency, 1),
        )

    @app.post("/index", response_model=IndexResponse)
    async def index(req: IndexRequest):
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

    return app


app = create_app()
