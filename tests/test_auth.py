"""Auth tests: bearer token enforcement on protected routes.

Reuses the heavyweight component mocks from ``test_e2e.py`` so the test
runs without GPUs/network. Unlike the e2e suite this one is *not* gated
by ``RAG_E2E`` — auth is in the request path of every protected route
and must be verified on every CI run.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def patched_unauth_app(tmp_path: Path, monkeypatch):
    """Same heavy-component patches as test_e2e but without auth headers.

    Yields a tuple of (client_without_auth, expected_token).
    """
    rag_home = tmp_path / "rag_home"
    qdrant_dir = tmp_path / "qdrant_data"
    rag_home.mkdir()

    # Force settings to use tmp paths.
    from rag.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    settings.qdrant.path = str(qdrant_dir)
    settings.lsp.enabled = False

    import rag.config as _config
    import rag.core.cache as _cache
    import rag.core.graph as _graph
    import rag.core.indexer as _indexer
    import rag.storage.db as _db

    monkeypatch.setattr(_config, "RAG_HOME", rag_home, raising=True)
    monkeypatch.setattr(_config, "TOKEN_PATH", rag_home / "token", raising=True)
    monkeypatch.setattr(_cache, "_DB_PATH", rag_home / "embed_cache.db", raising=True)
    monkeypatch.setattr(_graph, "GRAPH_CACHE_PATH", rag_home / "code_graph.pkl", raising=True)
    monkeypatch.setattr(_indexer, "RAG_HOME", rag_home, raising=True)
    monkeypatch.setattr(_db, "DB_PATH", rag_home / "rag.db", raising=True)

    # Reset cache thread-local so the patched _DB_PATH is used.
    if hasattr(_cache._local, "conn"):
        try:
            _cache._local.conn.close()
        except Exception:
            pass
        _cache._local.conn = None

    # Borrow the e2e helper — same fake dense-only embedder.
    from tests.test_e2e import _FakeEmbedder

    from rag.core import embedder as _embedder_mod
    from rag.core import vectorstore as _vs_mod
    from rag import server as _server_mod

    monkeypatch.setattr(_embedder_mod, "HybridEmbedder", _FakeEmbedder, raising=True)
    monkeypatch.setattr(_vs_mod, "HybridEmbedder", _FakeEmbedder, raising=True)
    monkeypatch.setattr(_server_mod, "HybridEmbedder", _FakeEmbedder, raising=True)

    async def _no_ollama(*args, **kwargs):
        return False

    monkeypatch.setattr(_embedder_mod.OllamaEmbedder, "health_check", _no_ollama, raising=True)

    import rag.agents.retrieval as _retrieval

    async def _check_llm_ready_false():
        return False

    monkeypatch.setattr(_retrieval, "_check_llm_ready", _check_llm_ready_false, raising=True)

    token = _config.get_or_create_token()
    app = _server_mod.create_app()
    with TestClient(app) as client:
        yield client, token


def test_search_requires_bearer_token(patched_unauth_app):
    """/search returns 401 without a token, 200 with the correct one.

    /health stays public so daemon supervisors can probe it.
    """
    client, token = patched_unauth_app

    # /health should always work — no auth required.
    resp = client.get("/health")
    assert resp.status_code == 200, resp.text

    # /search without auth -> 401.
    resp = client.post("/search", json={"query": "anything", "top_k": 1})
    assert resp.status_code == 401, resp.text
    assert "unauthor" in resp.json().get("error", "").lower()

    # /search with bogus auth -> 401.
    resp = client.post(
        "/search",
        json={"query": "anything", "top_k": 1},
        headers={"Authorization": "Bearer not-the-token"},
    )
    assert resp.status_code == 401, resp.text

    # /search with the correct token -> reaches the handler. We never
    # indexed a collection in this fixture so the handler 500s, but the
    # important assertion is that auth no longer rejected the call.
    # Confirm a 200 happens after a successful index.
    from tests.test_e2e import fake_repo  # noqa: F401  (registered fixture)

    # Re-create a tiny synthetic repo inline so we don't take a fixture dep.
    import tempfile
    from pathlib import Path as _Path

    with tempfile.TemporaryDirectory() as td:
        repo = _Path(td)
        (repo / "tiny.py").write_text("def hello():\n    return 'world'\n")
        idx = client.post(
            "/index",
            json={"repo_path": str(repo), "full": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert idx.status_code == 200, idx.text

        resp = client.post(
            "/search",
            json={"query": "hello", "top_k": 1},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
