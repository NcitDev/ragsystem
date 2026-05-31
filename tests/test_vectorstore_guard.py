"""Tests for vector-store dimension/None guards in upsert.

These guard against silent index corruption when the embedder produces vectors
of the wrong size (model swap) or fails to fill a slot.
"""

from __future__ import annotations

import pytest

from rag.core.embedder import EmbeddingResult
from rag.core.errors import VectorStoreError
from rag.core.vectorstore import ChunkDocument, QdrantVectorStore


class _FakeEmbedder:
    dim = 4
    provider = "fake"

    def __init__(self, out_dim: int):
        self._out_dim = out_dim

    async def initialize(self):
        return None

    async def embed_documents(self, texts):
        return [EmbeddingResult(dense=[0.1] * self._out_dim) for _ in texts]


class _FakeClient:
    def __init__(self):
        self.upserted = []

    async def upsert(self, collection_name, points):
        self.upserted.extend(points)


@pytest.fixture
def store(monkeypatch):
    emb = _FakeEmbedder(out_dim=4)  # matches dim=4
    vs = QdrantVectorStore(embedder=emb)
    client = _FakeClient()

    async def _no_ensure(collection):
        return None

    async def _get_client():
        return client

    monkeypatch.setattr(vs, "ensure_collection", _no_ensure)
    monkeypatch.setattr(vs, "_get_client", _get_client)
    return vs, client


async def test_upsert_ok_when_dim_matches(store):
    vs, client = store
    docs = [ChunkDocument(content="x", metadata={"file_path": "a.py"}, chunk_id=None)]
    n = await vs.upsert("code_chunks", docs)
    assert n == 1
    assert len(client.upserted) == 1


async def test_upsert_raises_on_dim_mismatch(monkeypatch):
    # Embedder produces dim-8 vectors but the embedder/collection expects dim-4.
    emb = _FakeEmbedder(out_dim=8)
    emb.dim = 4  # what the collection was built with
    vs = QdrantVectorStore(embedder=emb)
    client = _FakeClient()

    async def _no_ensure(collection):
        return None

    async def _get_client():
        return client

    monkeypatch.setattr(vs, "ensure_collection", _no_ensure)
    monkeypatch.setattr(vs, "_get_client", _get_client)

    docs = [ChunkDocument(content="x", metadata={"file_path": "a.py"})]
    with pytest.raises(VectorStoreError, match="dim"):
        await vs.upsert("code_chunks", docs)
    # Nothing written.
    assert client.upserted == []
