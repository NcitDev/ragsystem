"""Tests for query expansion and decomposition."""

import asyncio
import hashlib
import os
import tempfile
from pathlib import Path

import pytest

from rag.core.query import expand_query, decompose_query
from rag.core.vectorstore import ChunkDocument, QdrantVectorStore


def test_expand_auth():
    result = expand_query("find auth")
    assert "authentication" in result
    assert "jwt" in result


def test_expand_no_match():
    result = expand_query("find xyz")
    assert result == "find xyz"


def test_decompose_and():
    parts = decompose_query("auth and payment")
    assert len(parts) == 2
    assert "auth" in parts[0]
    assert "payment" in parts[1]


def test_decompose_single():
    parts = decompose_query("simple query")
    assert len(parts) == 1
    assert parts[0] == "simple query"


def test_decompose_max():
    parts = decompose_query("a and b and c and d", max_subqueries=2)
    assert len(parts) == 2


# -----------------------------------------------------------------------------
# Filtered search regression test
# -----------------------------------------------------------------------------


class _FakeEmbedder:
    """Deterministic in-memory dense embedder — no Ollama needed.

    Hashes text into a small dense vector. Good enough to exercise
    Qdrant's filter pipeline end-to-end. Sparse path was removed when
    FastEmbed was nuked.
    """

    dim = 16

    async def initialize(self) -> None:  # pragma: no cover - trivial
        return None

    def _vec(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode("utf-8")).digest()
        # Use first `dim` bytes, normalize to roughly unit-ish range
        return [(b - 128) / 128.0 for b in h[: self.dim]]

    async def embed_documents(self, texts):
        from rag.core.embedder import EmbeddingResult
        return [EmbeddingResult(dense=self._vec(t)) for t in texts]

    async def embed_query(self, text):
        from rag.core.embedder import EmbeddingResult
        return EmbeddingResult(dense=self._vec(text))


@pytest.mark.skipif(
    not os.environ.get("RAG_E2E"),
    reason="Requires RAG_E2E=1 (spins up an embedded Qdrant on disk).",
)
def test_search_with_filter_returns_matches():
    """Regression: filtered search must return only payload-matching chunks.

    Previously the embedded Qdrant path post-filtered in Python over a fixed
    candidate window, so matches that ranked outside the window were silently
    dropped. The fix pushes the filter into Qdrant; this test confirms every
    returned hit satisfies the filter.
    """
    async def _run():
        with tempfile.TemporaryDirectory() as tmp:
            store = QdrantVectorStore(embedder=_FakeEmbedder())
            # Inject a temp-path AsyncQdrantClient instead of using ~/.rag.
            from qdrant_client import AsyncQdrantClient
            store._client = AsyncQdrantClient(path=str(Path(tmp) / "qdrant"))

            collection = "test_filtered_search"
            languages = ["python", "javascript", "rust", "go", "ruby"]
            docs = []
            for i in range(50):
                lang = languages[i % len(languages)]
                docs.append(
                    ChunkDocument(
                        content=f"function_{i} written in {lang} doing work {i}",
                        metadata={"language": lang, "name": f"fn_{i}"},
                    )
                )

            await store.upsert(collection, docs, batch_size=25)

            results = await store.search(
                collection,
                query="function doing work",
                top_k=10,
                filters={"language": "python"},
            )

            assert len(results) > 0, "filter dropped all results — recall hole"
            for r in results:
                assert r.payload.get("language") == "python", (
                    f"non-matching language leaked through filter: {r.payload}"
                )

            await store.close()

    asyncio.run(_run())
