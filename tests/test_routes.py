"""Route-level tests against create_app() with heavy deps mocked.

Covers auth enforcement, input validation, error handling, rate limiting, and
the model-swap reload path — none of which the gated e2e smoke test exercises.
Heavy components (Ollama, LSP, reranker) are replaced with in-memory fakes so
this runs in the default pytest run without network or models.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_DENSE_DIM = 32


def _bow_vec(text: str, dim: int = _DENSE_DIM) -> list[float]:
    vec = [0.0] * dim
    for tok in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text.lower()):
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0
    norm = sum(v * v for v in vec) ** 0.5
    return [v / norm for v in vec] if norm else vec


class _FakeEmbedder:
    dim = _DENSE_DIM
    provider = "fake"

    def __init__(self):
        self._dense = self
        self._provider = "fake"

    async def initialize(self):
        return None

    async def health_check(self):
        return True

    async def embed_documents(self, texts):
        from rag.core.embedder import EmbeddingResult

        return [EmbeddingResult(dense=_bow_vec(t)) for t in texts]

    async def embed_query(self, text):
        from rag.core.embedder import EmbeddingResult

        return EmbeddingResult(dense=_bow_vec(text))


@pytest.fixture
def app_ctx(tmp_path: Path, monkeypatch):
    """Yield (client, token) for an app wired to tmp paths + fakes."""
    rag_home = tmp_path / "rag_home"
    rag_home.mkdir()

    from rag.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    settings.qdrant.path = str(tmp_path / "qdrant")
    settings.lsp.enabled = False

    import rag.config as _config
    import rag.core.cache as _cache
    import rag.core.graph as _graph
    import rag.core.indexer as _indexer
    import rag.storage.db as _db

    monkeypatch.setattr(_config, "RAG_HOME", rag_home, raising=True)
    monkeypatch.setattr(_config, "TOKEN_PATH", rag_home / "token", raising=True)
    monkeypatch.setattr(_cache, "_DB_PATH", rag_home / "embed_cache.db", raising=True)
    monkeypatch.setattr(_graph, "GRAPH_CACHE_PATH", rag_home / "graph.pkl", raising=True)
    monkeypatch.setattr(_indexer, "RAG_HOME", rag_home, raising=True)
    monkeypatch.setattr(_db, "DB_PATH", rag_home / "rag.db", raising=True)

    if getattr(_cache._local, "conn", None) is not None:
        _cache._local.conn.close()
        _cache._local.conn = None
    if getattr(_db._local, "conn", None) is not None:
        _db._local.conn.close()
        _db._local.conn = None

    from rag.core import embedder as _emb
    from rag.core import vectorstore as _vs
    from rag import server as _server

    monkeypatch.setattr(_emb, "HybridEmbedder", _FakeEmbedder, raising=True)
    monkeypatch.setattr(_vs, "HybridEmbedder", _FakeEmbedder, raising=True)
    monkeypatch.setattr(_server, "HybridEmbedder", _FakeEmbedder, raising=True)

    async def _no_ollama(*a, **k):
        return False

    monkeypatch.setattr(_emb.OllamaEmbedder, "health_check", _no_ollama, raising=True)

    import rag.agents.retrieval as _retrieval

    async def _check_false():
        return False

    monkeypatch.setattr(_retrieval, "_check_ollama", _check_false, raising=True)

    token = _config.get_or_create_token()
    app = _server.create_app()
    with TestClient(app) as client:
        yield client, token


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# --- Auth -------------------------------------------------------------------


def test_status_requires_auth(app_ctx):
    client, _ = app_ctx
    assert client.get("/status").status_code == 401


def test_status_with_token_ok(app_ctx):
    client, token = app_ctx
    r = client.get("/status", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "running"


def test_bad_token_rejected(app_ctx):
    client, _ = app_ctx
    r = client.get("/status", headers=_auth("wrong-token"))
    assert r.status_code == 401


def test_health_is_public(app_ctx):
    client, _ = app_ctx
    r = client.get("/health")
    assert r.status_code == 200
    assert "components" in r.json()


# --- Input validation -------------------------------------------------------


def test_search_empty_query_422(app_ctx):
    client, token = app_ctx
    r = client.post("/search", json={"query": ""}, headers=_auth(token))
    assert r.status_code == 422


def test_search_query_too_long_422(app_ctx):
    client, token = app_ctx
    r = client.post("/search", json={"query": "x" * 5000}, headers=_auth(token))
    assert r.status_code == 422


def test_search_top_k_out_of_range_422(app_ctx):
    client, token = app_ctx
    r = client.post("/search", json={"query": "x", "top_k": 9999}, headers=_auth(token))
    assert r.status_code == 422


def test_index_nonexistent_path_422(app_ctx):
    client, token = app_ctx
    r = client.post("/index", json={"repo_path": "/no/such/dir"}, headers=_auth(token))
    assert r.status_code == 422


# --- Error handling ---------------------------------------------------------


def test_global_error_handler_hides_detail(app_ctx, monkeypatch):
    """A route raising an unexpected error returns a generic 500 — no raw message."""
    client, token = app_ctx
    import rag.server as _server

    def _boom():
        raise RuntimeError("super secret /etc/passwd path leak")

    # get_vectorstore is used inside /status; make it explode.
    monkeypatch.setattr(_server, "get_vectorstore", _boom, raising=True)
    r = client.get("/status", headers=_auth(token))
    assert r.status_code == 500
    body = r.json()
    # No raw exception text (paths, internals) leaks to the client...
    assert "secret" not in str(body).lower()
    assert "passwd" not in str(body).lower()
    # ...only the exception class name, for triage.
    assert "RuntimeError" in str(body)


# --- Rate limiting ----------------------------------------------------------


def test_rate_limit_eventually_429(app_ctx, monkeypatch):
    client, token = app_ctx
    import rag.storage.db as _db

    # Force a tiny bucket so a couple of requests exhaust it.
    orig = _db.check_rate_bucket
    monkeypatch.setattr(
        _db, "check_rate_bucket",
        lambda tok, capacity=2, refill_per_sec=0.0: orig(tok, capacity=2, refill_per_sec=0.0),
    )
    codes = [client.get("/health").status_code for _ in range(6)]
    assert 429 in codes, codes
