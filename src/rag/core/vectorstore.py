"""Qdrant embedded vector store with hybrid search (dense + sparse + RRF fusion)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog
from qdrant_client import AsyncQdrantClient, models

from rag.config import get_settings
from rag.core.embedder import HybridEmbedder

logger = structlog.get_logger()

# Payload field indexes for Qdrant filtering
PAYLOAD_INDEXES = [
    # Structural
    ("file_path", models.PayloadSchemaType.KEYWORD),
    ("language", models.PayloadSchemaType.KEYWORD),
    ("chunk_type", models.PayloadSchemaType.KEYWORD),
    ("name", models.PayloadSchemaType.KEYWORD),
    ("parent_name", models.PayloadSchemaType.KEYWORD),
    ("doc_type", models.PayloadSchemaType.KEYWORD),
    # Patterns & architecture
    ("patterns", models.PayloadSchemaType.KEYWORD),
    ("pattern_roles", models.PayloadSchemaType.KEYWORD),
    ("domains", models.PayloadSchemaType.KEYWORD),
    ("layers", models.PayloadSchemaType.KEYWORD),
    # Code quality booleans
    ("is_async", models.PayloadSchemaType.KEYWORD),
    ("is_public", models.PayloadSchemaType.KEYWORD),
    ("is_abstract", models.PayloadSchemaType.KEYWORD),
    ("has_docstring", models.PayloadSchemaType.KEYWORD),
    ("has_unit_test", models.PayloadSchemaType.KEYWORD),
    ("dead_code_candidate", models.PayloadSchemaType.KEYWORD),
    # Code quality integers
    ("nesting_depth", models.PayloadSchemaType.INTEGER),
    ("parameter_count", models.PayloadSchemaType.INTEGER),
    ("line_count", models.PayloadSchemaType.INTEGER),
    ("complexity_cyclomatic", models.PayloadSchemaType.INTEGER),
    ("complexity_cognitive", models.PayloadSchemaType.INTEGER),
    ("fan_in", models.PayloadSchemaType.INTEGER),
    ("fan_out", models.PayloadSchemaType.INTEGER),
    # Dependencies
    ("external_deps", models.PayloadSchemaType.KEYWORD),
    ("inherits_from", models.PayloadSchemaType.KEYWORD),
    ("decorator_tags", models.PayloadSchemaType.KEYWORD),
    ("concurrency_patterns", models.PayloadSchemaType.KEYWORD),
]


@dataclass
class SearchResult:
    """A single search result from vector store."""

    content: str
    score: float
    payload: dict[str, Any] = field(default_factory=dict)
    point_id: str = ""

    def slim(self) -> dict[str, Any]:
        """Return only fields needed by LLM consumers."""
        return {
            "file_path": self.payload.get("file_path", ""),
            "name": self.payload.get("name", ""),
            "parent_name": self.payload.get("parent_name", ""),
            "chunk_type": self.payload.get("chunk_type", ""),
            "language": self.payload.get("language", ""),
            "lines": f"{self.payload.get('start_line', '?')}-{self.payload.get('end_line', '?')}",
            "code": self.content,
            "score": round(self.score, 4),
        }


@dataclass
class ChunkDocument:
    """A document chunk to be indexed."""

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    chunk_id: str | None = None


def _apply_filters(results: list[SearchResult], filters: dict[str, Any]) -> list[SearchResult]:
    """Apply payload filters in Python (for embedded Qdrant without payload indexes)."""
    filtered = []
    for r in results:
        match = True
        for key, value in filters.items():
            payload_val = r.payload.get(key)
            if payload_val is None:
                match = False
                break
            if isinstance(value, (int, float)):
                # Range filter: payload value must be >= filter value
                try:
                    if float(payload_val) < float(value):
                        match = False
                        break
                except (TypeError, ValueError):
                    match = False
                    break
            elif isinstance(payload_val, list):
                # List field: check if filter value is in the list
                if value not in payload_val:
                    match = False
                    break
            else:
                # Exact match
                if str(payload_val) != str(value):
                    match = False
                    break
        if match:
            filtered.append(r)
    return filtered


class QdrantVectorStore:
    """Qdrant embedded vector store with hybrid search capabilities.

    Uses dual-vector search (dense + sparse) with Reciprocal Rank Fusion.
    """

    def __init__(self, embedder: HybridEmbedder | None = None) -> None:
        self._embedder = embedder or HybridEmbedder()
        self._client: AsyncQdrantClient | None = None

    @property
    def embedder(self) -> HybridEmbedder:
        return self._embedder

    async def _get_client(self) -> AsyncQdrantClient:
        if self._client is None:
            settings = get_settings()
            path = settings.qdrant.resolved_path
            path.mkdir(parents=True, exist_ok=True)
            self._client = AsyncQdrantClient(path=str(path))
            logger.info("qdrant_embedded_opened", path=str(path))
        return self._client

    async def ensure_collection(self, collection: str) -> None:
        """Create collection with dual vectors if it doesn't exist."""
        client = await self._get_client()
        collections = await client.get_collections()
        existing = [c.name for c in collections.collections]

        if collection in existing:
            return

        await self._embedder.initialize()

        await client.create_collection(
            collection_name=collection,
            vectors_config={
                "dense": models.VectorParams(
                    size=self._embedder.dim,
                    distance=models.Distance.COSINE,
                ),
            },
            sparse_vectors_config={
                "sparse": models.SparseVectorParams(
                    modifier=models.Modifier.IDF,
                ),
            },
        )

        for field_name, field_type in PAYLOAD_INDEXES:
            await client.create_payload_index(
                collection_name=collection,
                field_name=field_name,
                field_schema=field_type,
            )

        logger.info("collection_created", collection=collection)

    async def upsert(
        self,
        collection: str,
        documents: list[ChunkDocument],
        batch_size: int = 50,
    ) -> int:
        """Embed and upsert documents into Qdrant."""
        await self.ensure_collection(collection)
        client = await self._get_client()

        total = 0
        for i in range(0, len(documents), batch_size):
            batch = documents[i : i + batch_size]
            texts = [doc.content for doc in batch]

            embeddings = await self._embedder.embed_documents(texts)

            points = []
            for doc, emb in zip(batch, embeddings):
                # Qdrant local mode requires valid UUIDs
                raw_id = doc.chunk_id or str(uuid.uuid4())
                try:
                    uuid.UUID(raw_id)
                    point_id = raw_id
                except ValueError:
                    # Convert short hash to deterministic UUID
                    point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, raw_id))
                vectors: dict[str, Any] = {"dense": emb.dense}
                if emb.sparse_indices and emb.sparse_values:
                    vectors["sparse"] = models.SparseVector(
                        indices=emb.sparse_indices,
                        values=emb.sparse_values,
                    )

                points.append(models.PointStruct(
                    id=point_id,
                    vector=vectors,
                    payload={"content": doc.content, **doc.metadata},
                ))

            await client.upsert(collection_name=collection, points=points)
            total += len(points)
            logger.debug("upserted_batch", collection=collection, count=len(points))

        logger.info("upsert_complete", collection=collection, total=total)
        return total

    async def search(
        self,
        collection: str,
        query: str,
        top_k: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """Hybrid search with RRF fusion of dense + sparse results.

        For embedded Qdrant (no payload indexes), filters are applied
        post-retrieval in Python. We fetch more results to compensate.
        """
        settings = get_settings()
        top_k = top_k or settings.index.retrieval_top_k
        client = await self._get_client()

        query_embedding = await self._embedder.embed_query(query)

        # Fetch more if we need to post-filter
        fetch_limit = top_k * 5 if filters else 50

        # Prefetch: dense + sparse, then RRF fusion (no Qdrant-level filters for embedded mode)
        prefetch = [
            models.Prefetch(
                query=query_embedding.dense,
                using="dense",
                limit=fetch_limit,
            ),
        ]

        if query_embedding.sparse_indices and query_embedding.sparse_values:
            prefetch.append(
                models.Prefetch(
                    query=models.SparseVector(
                        indices=query_embedding.sparse_indices,
                        values=query_embedding.sparse_values,
                    ),
                    using="sparse",
                    limit=fetch_limit,
                ),
            )

        results = await client.query_points(
            collection_name=collection,
            prefetch=prefetch,
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=fetch_limit,
        )

        search_results = [
            SearchResult(
                content=point.payload.get("content", "") if point.payload else "",
                score=point.score or 0.0,
                payload=dict(point.payload) if point.payload else {},
                point_id=str(point.id),
            )
            for point in results.points
        ]

        # Post-retrieval filtering (for embedded Qdrant without payload indexes)
        if filters:
            search_results = _apply_filters(search_results, filters)

        return search_results[:top_k]

    async def count(self, collection: str) -> int:
        """Count points in a collection."""
        client = await self._get_client()
        try:
            result = await client.count(collection_name=collection)
            return result.count
        except Exception:
            return 0

    async def delete_by_filter(self, collection: str, field: str, value: str) -> None:
        """Delete points matching a filter."""
        client = await self._get_client()
        await client.delete(
            collection_name=collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key=field,
                            match=models.MatchValue(value=value),
                        )
                    ]
                )
            ),
        )

    async def collection_info(self, collection: str) -> dict[str, Any]:
        """Get collection stats."""
        client = await self._get_client()
        try:
            collections = await client.get_collections()
            existing = [c.name for c in collections.collections]
            if collection not in existing:
                return {"name": collection, "status": "not_found", "points_count": 0}
            info = await client.get_collection(collection)
            return {
                "name": collection,
                "points_count": getattr(info, "points_count", 0) or 0,
                "vectors_count": getattr(info, "vectors_count", getattr(info, "points_count", 0)) or 0,
                "status": str(getattr(info.status, "value", "unknown")) if info.status else "unknown",
            }
        except Exception as e:
            logger.debug("collection_info_error", collection=collection, error=str(e))
            return {"name": collection, "status": "not_found", "points_count": 0}

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None
