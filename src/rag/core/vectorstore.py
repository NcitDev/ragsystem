"""Qdrant embedded vector store with dense vector search.

Sparse BM25 vectors and RRF fusion were removed when FastEmbed was nuked.
Search is now a single dense ``query_points`` call.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog
from qdrant_client import AsyncQdrantClient, models

from rag.config import get_settings
from rag.core.embedder import HybridEmbedder
from rag.core.errors import VectorStoreError

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
    ("is_suspend", models.PayloadSchemaType.KEYWORD),
    ("uses_coroutines", models.PayloadSchemaType.KEYWORD),
    ("uses_flow", models.PayloadSchemaType.KEYWORD),
    ("uses_async_java", models.PayloadSchemaType.KEYWORD),
    ("is_singleton", models.PayloadSchemaType.KEYWORD),
    ("is_singleton_pattern", models.PayloadSchemaType.KEYWORD),
    ("is_kotlin_object", models.PayloadSchemaType.KEYWORD),
    ("is_sealed", models.PayloadSchemaType.KEYWORD),
    ("is_data_class", models.PayloadSchemaType.KEYWORD),
    ("is_interface", models.PayloadSchemaType.KEYWORD),
    ("is_composable", models.PayloadSchemaType.KEYWORD),
    ("is_di_component", models.PayloadSchemaType.KEYWORD),
    ("is_enum", models.PayloadSchemaType.KEYWORD),
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
    # LOD (hierarchical drill-down)
    ("module_path", models.PayloadSchemaType.KEYWORD),
    ("lod_level", models.PayloadSchemaType.KEYWORD),
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
            "citation": self._make_citation(),
        }

    def _make_citation(self) -> str:
        """Generate human-readable source citation."""
        fp = self.payload.get("file_path", "?")
        name = self.payload.get("name", "")
        parent = self.payload.get("parent_name", "")
        start = self.payload.get("start_line", "?")
        end = self.payload.get("end_line", "?")
        symbol = f"{parent}.{name}" if parent else name
        return f"{fp}:{start}-{end} ({symbol})" if symbol else f"{fp}:{start}-{end}"


@dataclass
class ChunkDocument:
    """A document chunk to be indexed."""

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    chunk_id: str | None = None


def _build_qdrant_filter(filters: dict[str, Any]) -> models.Filter:
    """Translate a {field: value} dict into a Qdrant ``models.Filter``.

    Embedded Qdrant supports filters at query time even without payload indexes
    (they just run unindexed/slower). For list-typed payload fields (e.g.
    ``patterns``, ``domains``, ``layers``, ``decorator_tags``), Qdrant's
    ``MatchValue`` automatically matches list-membership server-side.
    """
    conditions: list[models.FieldCondition] = []
    for key, value in filters.items():
        if isinstance(value, bool):
            conditions.append(
                models.FieldCondition(key=key, match=models.MatchValue(value=value))
            )
        elif isinstance(value, (int, float)):
            conditions.append(
                models.FieldCondition(key=key, range=models.Range(gte=float(value)))
            )
        elif isinstance(value, list):
            # Agno often emits filters like {"language": ["dart"]}. Treat as
            # "any of these values" via MatchAny — also handles list-typed
            # payload fields (patterns, domains, layers, decorator_tags) since
            # Qdrant matches list-membership for each candidate value.
            if len(value) == 0:
                continue
            if len(value) == 1:
                conditions.append(
                    models.FieldCondition(key=key, match=models.MatchValue(value=value[0]))
                )
            else:
                conditions.append(
                    models.FieldCondition(key=key, match=models.MatchAny(any=value))
                )
        else:
            conditions.append(
                models.FieldCondition(key=key, match=models.MatchValue(value=value))
            )
    return models.Filter(must=conditions)


def _apply_filters(results: list[SearchResult], filters: dict[str, Any]) -> list[SearchResult]:
    """Apply payload filters in Python.

    NOTE: Kept for backward compatibility only. Filtering now happens
    server-side in Qdrant via ``_build_qdrant_filter`` — see
    ``QdrantVectorStore.search``. This function is no longer called from
    the search path.
    """
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
    """Qdrant embedded vector store, dense-only.

    Sparse + RRF fusion was removed alongside FastEmbed. Search is a
    single dense ``query_points`` call.
    """

    def __init__(self, embedder: HybridEmbedder | None = None) -> None:
        self._embedder = embedder or HybridEmbedder()
        self._client: AsyncQdrantClient | None = None
        self._is_embedded = True  # Using path-based local mode

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

        await self._embedder.initialize()

        if collection in existing:
            # Guard against silent corruption: if the embedder's dimension no
            # longer matches the dimension the collection was created with
            # (e.g. the embedding model was swapped), upserts would push
            # wrong-sized vectors and search would return garbage. Fail loud.
            try:
                info = await client.get_collection(collection)
                params = info.config.params.vectors
                dense = params["dense"] if isinstance(params, dict) else params
                existing_dim = getattr(dense, "size", None)
            except Exception as e:  # pragma: no cover - defensive
                logger.warning("collection_dim_check_failed", collection=collection, error=str(e))
                existing_dim = None
            if existing_dim is not None and existing_dim != self._embedder.dim:
                raise VectorStoreError(
                    f"Collection '{collection}' was built with dim {existing_dim} but the "
                    f"current embedder produces dim {self._embedder.dim}. The embedding model "
                    f"likely changed — re-index with --full to rebuild the collection."
                )
            return

        await client.create_collection(
            collection_name=collection,
            vectors_config={
                "dense": models.VectorParams(
                    size=self._embedder.dim,
                    distance=models.Distance.COSINE,
                ),
            },
        )

        # Payload indexes only work in server mode, skip for embedded
        if not self._is_embedded:
            for field_name, field_type in PAYLOAD_INDEXES:
                await client.create_payload_index(
                    collection_name=collection,
                    field_name=field_name,
                    field_schema=field_type,
                )
        else:
            logger.debug("payload_indexes_skipped", reason="embedded mode")

        logger.info("collection_created", collection=collection)

    async def upsert(
        self,
        collection: str,
        documents: list[ChunkDocument],
        batch_size: int = 50,
        cache: Any = None,
    ) -> int:
        """Embed and upsert documents into Qdrant.

        Args:
            cache: Optional EmbeddingCache to skip re-embedding unchanged chunks.
        """
        await self.ensure_collection(collection)
        client = await self._get_client()

        total = 0
        for i in range(0, len(documents), batch_size):
            batch = documents[i : i + batch_size]

            # Check cache for existing embeddings
            embeddings = []
            to_embed_indices: list[int] = []
            to_embed_texts: list[str] = []

            for j, doc in enumerate(batch):
                cached_emb = None
                if cache is not None:
                    content_hash = doc.metadata.get("content_hash", "")
                    if content_hash:
                        cached_emb = cache.get(content_hash)

                if cached_emb is not None:
                    embeddings.append(cached_emb)
                else:
                    embeddings.append(None)
                    to_embed_indices.append(j)
                    to_embed_texts.append(doc.content)

            # Embed only uncached
            if to_embed_texts:
                new_embeddings = await self._embedder.embed_documents(to_embed_texts)
                for idx, emb in zip(to_embed_indices, new_embeddings):
                    embeddings[idx] = emb
                    # Store in cache
                    if cache is not None:
                        content_hash = batch[idx].metadata.get("content_hash", "")
                        if content_hash:
                            cache.put(content_hash, emb)

            if to_embed_texts:
                logger.debug("embed_cache_stats", total=len(batch), cached=len(batch) - len(to_embed_texts), embedded=len(to_embed_texts))

            expected_dim = self._embedder.dim
            points = []
            for doc, emb in zip(batch, embeddings):
                # A None here means an embedding slot was never filled (cache
                # miss not backfilled, or a partial embed failure). Upserting
                # would crash on emb.dense; skip + log loudly instead.
                if emb is None:
                    logger.error(
                        "upsert_missing_embedding",
                        collection=collection,
                        chunk_id=doc.chunk_id,
                        file_path=doc.metadata.get("file_path"),
                    )
                    continue
                # Dimension mismatch between produced vector and collection is a
                # silent-corruption hazard; refuse rather than write garbage.
                if len(emb.dense) != expected_dim:
                    raise VectorStoreError(
                        f"Embedding dim {len(emb.dense)} != expected {expected_dim} "
                        f"for chunk {doc.chunk_id} ({doc.metadata.get('file_path')}). "
                        f"Embedder/collection mismatch — re-index with --full."
                    )
                # Qdrant local mode requires valid UUIDs
                raw_id = doc.chunk_id or str(uuid.uuid4())
                try:
                    uuid.UUID(raw_id)
                    point_id = raw_id
                except ValueError:
                    # Convert short hash to deterministic UUID
                    point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, raw_id))
                vectors: dict[str, Any] = {"dense": emb.dense}

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
        """Dense vector search.

        Filters are pushed into Qdrant via ``query_filter`` (works in
        embedded mode too — payload indexes only affect speed, not
        correctness). This avoids silent recall holes from post-filtering
        a fixed-size candidate window. The previous sparse + RRF prefetch
        was removed when FastEmbed was nuked.
        """
        settings = get_settings()
        top_k = top_k or settings.index.retrieval_top_k
        client = await self._get_client()

        query_embedding = await self._embedder.embed_query(query)

        qdrant_filter = _build_qdrant_filter(filters) if filters else None

        results = await client.query_points(
            collection_name=collection,
            query=query_embedding.dense,
            using="dense",
            query_filter=qdrant_filter,
            limit=top_k,
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
        collections = await client.get_collections()
        if collection not in [c.name for c in collections.collections]:
            logger.debug("delete_filter_collection_missing", collection=collection)
            return
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
