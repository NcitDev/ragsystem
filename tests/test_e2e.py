"""End-to-end smoke test for the FastAPI RAG pipeline.

Exercises the full index -> search loop via FastAPI's TestClient against
``create_app()``. Heavyweight components (Ollama, LSP) are replaced with
deterministic in-memory stand-ins so the test runs without GPUs, network,
or model downloads. (FastEmbed and the cross-encoder reranker were
removed entirely in the post-launch refactor.)

Gated behind the ``RAG_E2E`` env var to keep the default ``pytest`` run fast.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    not os.environ.get("RAG_E2E"),
    reason="set RAG_E2E=1 to run e2e smoke test",
)


# -----------------------------------------------------------------------------
# Deterministic fake embedder
# -----------------------------------------------------------------------------
#
# Real Qwen3 embeddings are out of scope for unit-level CI. We fake the dense
# path with a 64-dim bag-of-words projection so semantically related text
# (e.g. queries containing "auth login" and the auth.py source) end up close
# in cosine space. Sparse/BM25 was removed alongside FastEmbed.

_DENSE_DIM = 64


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text.lower()) if len(t) > 1]


def _bow_vec(text: str, dim: int = _DENSE_DIM) -> list[float]:
    """Hash bag-of-words into a dense vector. Same tokens -> aligned axes."""
    vec = [0.0] * dim
    for tok in _tokens(text):
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0
    # L2 normalize so cosine == dot.
    norm = sum(v * v for v in vec) ** 0.5
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


class _FakeEmbedder:
    """Drop-in replacement for ``HybridEmbedder`` (dense-only)."""

    dim = _DENSE_DIM
    provider = "fake"

    def __init__(self) -> None:
        # Mirror the real HybridEmbedder attributes routes peek at.
        self._dense = self
        self._provider = "fake"

    async def initialize(self) -> None:
        return None

    async def embed_documents(self, texts):
        from rag.core.embedder import EmbeddingResult

        return [EmbeddingResult(dense=_bow_vec(t)) for t in texts]

    async def embed_query(self, text):
        from rag.core.embedder import EmbeddingResult

        return EmbeddingResult(dense=_bow_vec(text))


# -----------------------------------------------------------------------------
# Fixture: build a tiny repo + monkeypatch all heavy components
# -----------------------------------------------------------------------------


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """Create a small synthetic Python repo with recognizable content."""
    repo = tmp_path / "repo"
    repo.mkdir()

    (repo / "auth.py").write_text(
        '''"""Authentication module."""


class AuthService:
    """Handles user authentication and tokens."""

    def login(self, username: str, password: str) -> str:
        """Authenticate user with username and password."""
        return f"token_for_{username}"

    def verify_token(self, token: str) -> bool:
        """Verify that a JWT token is valid for authentication."""
        return token.startswith("token_for_")

    async def refresh_session(self, token: str) -> str:
        """Refresh an expired authentication session token."""
        return token + "_refreshed"
'''
    )

    (repo / "repo.py").write_text(
        '''"""User repository module - CRUD persistence."""


class UserRepository:
    """Repository pattern for user CRUD operations on the database."""

    def create(self, user: dict) -> dict:
        """Create a new user record in the repository."""
        return {**user, "id": 1}

    def read(self, user_id: int) -> dict:
        """Read a user record from the repository by id."""
        return {"id": user_id}

    def update(self, user_id: int, data: dict) -> dict:
        """Update an existing user record in the repository."""
        return {"id": user_id, **data}

    def delete(self, user_id: int) -> bool:
        """Delete a user record from the repository."""
        return True
'''
    )

    (repo / "cache.py").write_text(
        '''"""Singleton in-memory cache."""


class Cache:
    """Singleton cache holding key/value pairs."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._data = {}
        return cls._instance

    def get(self, key: str):
        return self._data.get(key)

    def put(self, key: str, value) -> None:
        self._data[key] = value
'''
    )

    return repo


@pytest.fixture
def patched_app(tmp_path: Path, monkeypatch):
    """Build a TestClient against ``create_app()`` with heavy deps mocked.

    Patches:
      - ``HybridEmbedder``        -> ``_FakeEmbedder`` (dense-only)
      - Ollama health checks      -> always False (forces ``_fallback_plan``)
      - ``settings.qdrant.path``  -> tmp dir (no ~/.rag pollution)
      - ``settings.lsp.enabled``  -> False (no LSP servers spawned)
      - ``RAG_HOME``-derived constants -> tmp dir (state, cache, graph files)

    The cross-encoder reranker no longer exists, so no patches are needed
    for it.
    """
    rag_home = tmp_path / "rag_home"
    qdrant_dir = tmp_path / "qdrant_data"
    rag_home.mkdir()

    # Force settings to use tmp paths and a known provider (so config loads).
    # get_settings is lru_cache'd; clear it then mutate the cached object.
    from rag.config import get_settings
    get_settings.cache_clear()
    settings = get_settings()
    settings.qdrant.path = str(qdrant_dir)
    settings.lsp.enabled = False

    # Redirect every module-level RAG_HOME-derived constant.
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

    # Reset cache thread-local conn so the patched _DB_PATH is used.
    if hasattr(_cache._local, "conn"):
        try:
            _cache._local.conn.close()
        except Exception:
            pass
        _cache._local.conn = None

    # Replace the dense embedder with the fake.
    from rag.core import embedder as _embedder_mod

    monkeypatch.setattr(_embedder_mod, "HybridEmbedder", _FakeEmbedder, raising=True)
    # vectorstore / server import HybridEmbedder by name — patch those too.
    from rag.core import vectorstore as _vs_mod

    monkeypatch.setattr(_vs_mod, "HybridEmbedder", _FakeEmbedder, raising=True)
    from rag import server as _server_mod

    monkeypatch.setattr(_server_mod, "HybridEmbedder", _FakeEmbedder, raising=True)

    # Force Ollama health checks to fail -> plan_search uses _fallback_plan.
    async def _no_ollama(*args, **kwargs):
        return False

    monkeypatch.setattr(_embedder_mod.OllamaEmbedder, "health_check", _no_ollama, raising=True)

    import rag.agents.retrieval as _retrieval

    async def _check_ollama_false():
        return False

    monkeypatch.setattr(_retrieval, "_check_ollama", _check_ollama_false, raising=True)

    # Build the app and yield a live TestClient (triggers lifespan).
    # Pre-mint the bearer token now that TOKEN_PATH is redirected, then
    # bake the Authorization header into the client so every request is
    # authenticated.
    token = _config.get_or_create_token()
    app = _server_mod.create_app()
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield client


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------


def test_index_then_search(patched_app: TestClient, fake_repo: Path):
    """POST /index -> POST /search -> GET /overview round-trip."""
    # 1. Index the synthetic repo.
    resp = patched_app.post("/index", json={"repo_path": str(fake_repo), "full": True})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["files_processed"] > 0, body
    assert body["chunks_indexed"] > 0, body

    # 2. Search for auth-flavored content.
    resp = patched_app.post(
        "/search", json={"query": "user login authentication token", "top_k": 5}
    )
    assert resp.status_code == 200, resp.text
    auth_results = resp.json()["results"]
    assert auth_results, "auth query returned zero hits"
    auth_paths = [r["file_path"] for r in auth_results]
    assert any("auth.py" in p for p in auth_paths), (
        f"auth.py missing from auth-query results: {auth_paths}"
    )
    # Auth file should rank in the top hits.
    assert "auth.py" in auth_results[0]["file_path"], (
        f"auth.py not top hit; got {auth_paths}"
    )

    # 3. Search for repository-flavored content.
    resp = patched_app.post(
        "/search", json={"query": "user repository CRUD create read update delete", "top_k": 5}
    )
    assert resp.status_code == 200, resp.text
    repo_results = resp.json()["results"]
    assert repo_results, "repo query returned zero hits"
    repo_paths = [r["file_path"] for r in repo_results]
    assert "repo.py" in repo_results[0]["file_path"], (
        f"repo.py not top hit; got {repo_paths}"
    )

    # 4. Overview aggregates languages.
    resp = patched_app.get("/overview")
    assert resp.status_code == 200, resp.text
    overview = resp.json()
    assert overview["total_chunks"] > 0
    assert "python" in overview["languages"], overview["languages"]


def test_health_and_status(patched_app: TestClient, fake_repo: Path):
    """Lightweight smoke check on /health and /status endpoints."""
    resp = patched_app.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert "status" in body
    assert "components" in body
    # qdrant must be ok once lifespan brought up the vectorstore.
    assert body["components"].get("qdrant") == "ok", body

    resp = patched_app.get("/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running"
    assert body["embedder_provider"] == "fake"
    assert body["uptime_seconds"] >= 0
