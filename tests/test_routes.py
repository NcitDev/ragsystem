"""Route-level tests against create_app() with heavy deps mocked.

Covers auth enforcement, input validation, error handling, rate limiting, and
the model-swap reload path — none of which the gated e2e smoke test exercises.
Heavy components (Ollama, LSP, reranker) are replaced with in-memory fakes so
this runs in the default pytest run without network or models.
"""

from __future__ import annotations

import hashlib
import re
from types import SimpleNamespace
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


def test_search_unknown_repo_404(app_ctx):
    client, token = app_ctx
    r = client.post(
        "/search",
        json={"query": "x", "repo": "missing"},
        headers=_auth(token),
    )
    assert r.status_code == 404


def test_index_nonexistent_path_422(app_ctx):
    client, token = app_ctx
    r = client.post("/index", json={"repo_path": "/no/such/dir"}, headers=_auth(token))
    assert r.status_code == 422


def test_code_index_exact_symbol_lookup(app_ctx):
    from rag.core.vectorstore import ChunkDocument
    from rag.storage import db as _db

    _db.upsert_code_chunks(
        "repo_demo",
        [
            ChunkDocument(
                content="fun paidOrderResponseToVo(response: PaidOrderResponse) = Unit",
                metadata={
                    "file_path": "checkout/PaidOrderMapper.kt",
                    "language": "kotlin",
                    "chunk_type": "function",
                    "name": "paidOrderResponseToVo",
                    "parent_name": "",
                    "start_line": 12,
                    "end_line": 14,
                },
                chunk_id="chunk-paid-order",
            ),
            ChunkDocument(
                content="fun unrelated() = Unit",
                metadata={
                    "file_path": "checkout/Other.kt",
                    "language": "kotlin",
                    "chunk_type": "function",
                    "name": "unrelated",
                    "parent_name": "",
                    "start_line": 1,
                    "end_line": 1,
                },
                chunk_id="chunk-other",
            ),
        ],
    )

    hits = _db.search_code_chunks(
        "find paidOrderResponseToVo mapper",
        collection="repo_demo",
        limit=3,
    )
    assert hits
    assert hits[0]["file_path"] == "checkout/PaidOrderMapper.kt"
    assert hits[0]["lines"] == "12-14"


def test_context_pack_returns_bounded_exact_slice(app_ctx):
    client, token = app_ctx
    from rag.config import get_settings
    from rag.core.vectorstore import ChunkDocument
    from rag.storage import db as _db

    collection = get_settings().qdrant.code_collection
    _db.upsert_code_chunks(
        collection,
        [
            ChunkDocument(
                content="\n".join([
                    "suspend fun completePayment(orderId: String) {",
                    "    analytics.track(PaymentCompleted(orderId))",
                    "}",
                ]),
                metadata={
                    "file_path": "checkout/PaymentInteractor.kt",
                    "language": "kotlin",
                    "chunk_type": "function",
                    "name": "completePayment",
                    "parent_name": "",
                    "start_line": 40,
                    "end_line": 42,
                },
                chunk_id="chunk-complete-payment",
            )
        ],
    )

    r = client.post(
        "/context-pack",
        json={
            "query": "completePayment analytics PaymentCompleted",
            "max_slices": 2,
            "max_source_tokens": 100,
            "include_semantic": False,
        },
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["total_source_tokens"] <= 100
    assert body["slices"][0]["file_path"] == "checkout/PaymentInteractor.kt"
    assert body["slices"][0]["why_included"] == "exact_or_lexical_match"


def test_context_pack_uses_ast_index_for_named_repo(app_ctx, monkeypatch):
    client, token = app_ctx

    import rag.core.ast_index as _ast_index
    import rag.server as _server

    monkeypatch.setattr(
        _server,
        "_collection_for_repo",
        lambda repo: "repo_demo",
        raising=True,
    )
    monkeypatch.setattr(
        _server,
        "_repo_info_for_name",
        lambda repo: SimpleNamespace(path="/tmp/demo", collection="repo_demo"),
        raising=True,
    )
    monkeypatch.setattr(
        _ast_index,
        "retrieve_context",
        lambda repo_path, query, limit=12: [
            {
                "chunk_id": "ast:Checkout.kt:10:completePayment",
                "file_path": "checkout/Checkout.kt",
                "name": "completePayment",
                "parent_name": "",
                "chunk_type": "function",
                "language": "kotlin",
                "start_line": 10,
                "end_line": 14,
                "lines": "10-14",
                "code": "fun completePayment() {\n    analytics.track(PaymentCompleted)\n}",
                "token_estimate": 20,
                "score": 12.0,
                "citation": "checkout/Checkout.kt:10-14 (completePayment)",
                "why_included": "ast_index_symbol",
            },
            {
                "chunk_id": "ast:Checkout.kt:11:completePaymentUsage",
                "file_path": "checkout/Checkout.kt",
                "name": "completePayment",
                "parent_name": "",
                "chunk_type": "usage",
                "language": "kotlin",
                "start_line": 11,
                "end_line": 14,
                "lines": "11-14",
                "code": "analytics.track(PaymentCompleted)",
                "token_estimate": 10,
                "score": 5.0,
                "citation": "checkout/Checkout.kt:11-14 (completePayment)",
                "why_included": "ast_index_usage",
            }
        ],
        raising=True,
    )

    r = client.post(
        "/context-pack",
        json={
            "query": "completePayment PaymentCompleted",
            "repo": "demo",
            "max_slices": 2,
            "max_source_tokens": 100,
            "include_semantic": False,
        },
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["slices"][0]["why_included"] == "ast_index_symbol"
    assert body["slices"][0]["file_path"] == "checkout/Checkout.kt"


def test_resolve_returns_ast_definitions_and_usages(app_ctx, monkeypatch):
    client, token = app_ctx

    import rag.core.ast_index as _ast_index
    import rag.server as _server

    monkeypatch.setattr(
        _server,
        "_repo_info_for_name",
        lambda repo: SimpleNamespace(path="/tmp/demo", collection="repo_demo"),
        raising=True,
    )
    monkeypatch.setattr(
        _ast_index,
        "resolve_symbols",
        lambda repo_path, symbols, definitions_limit=20, usages_limit=20: {
            "definitions": [
                {
                    "file_path": "checkout/Checkout.kt",
                    "name": "completePayment",
                    "parent_name": "",
                    "chunk_type": "function",
                    "language": "kotlin",
                    "start_line": 10,
                    "end_line": 12,
                    "lines": "10-12",
                    "code": "fun completePayment() = Unit",
                    "token_estimate": 8,
                    "score": 12.0,
                    "citation": "checkout/Checkout.kt:10-12 (completePayment)",
                    "why_included": "ast_index_symbol",
                }
            ],
            "usages": [
                {
                    "file_path": "checkout/CheckoutTest.kt",
                    "name": "completePayment",
                    "parent_name": "",
                    "chunk_type": "usage",
                    "language": "kotlin",
                    "start_line": 20,
                    "end_line": 22,
                    "lines": "20-22",
                    "code": "sut.completePayment()",
                    "token_estimate": 6,
                    "score": 4.0,
                    "citation": "checkout/CheckoutTest.kt:20-22 (completePayment)",
                    "why_included": "ast_index_usage",
                }
            ],
        },
        raising=True,
    )

    r = client.post(
        "/resolve",
        json={"repo": "demo", "symbols": ["completePayment"]},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["symbols"] == ["completePayment"]
    assert body["total_definitions"] == 1
    assert body["total_usages"] == 1
    assert body["definitions"][0]["file_path"] == "checkout/Checkout.kt"
    assert body["usages"][0]["file_path"] == "checkout/CheckoutTest.kt"


def test_call_tree_returns_ast_nodes(app_ctx, monkeypatch):
    client, token = app_ctx

    import rag.core.ast_index as _ast_index
    import rag.server as _server

    monkeypatch.setattr(
        _server,
        "_repo_info_for_name",
        lambda repo: SimpleNamespace(path="/tmp/demo", collection="repo_demo"),
        raising=True,
    )
    monkeypatch.setattr(
        _ast_index,
        "call_tree",
        lambda repo_path, symbol, limit=50: [
            {
                "file_path": "checkout/Presenter.kt",
                "name": "onCheckoutComplete",
                "parent_name": "",
                "chunk_type": "caller",
                "language": "kotlin",
                "start_line": 30,
                "end_line": 36,
                "lines": "30-36",
                "code": "fun onCheckoutComplete() {\n    completePayment()\n}",
                "token_estimate": 14,
                "score": 9.0,
                "citation": "checkout/Presenter.kt:30-36 (onCheckoutComplete)",
                "why_included": "ast_index_call_tree",
                "depth": 1,
            }
        ],
        raising=True,
    )

    r = client.post(
        "/call-tree",
        json={"repo": "demo", "symbol": "completePayment", "limit": 10},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["nodes"][0]["depth"] == 1
    assert body["nodes"][0]["file_path"] == "checkout/Presenter.kt"


def test_project_understand_returns_modules_symbols_and_slices(app_ctx, monkeypatch):
    client, token = app_ctx

    import rag.core.ast_index as _ast_index
    import rag.server as _server

    monkeypatch.setattr(
        _server,
        "_repo_info_for_name",
        lambda repo: SimpleNamespace(path="/tmp/demo", collection="repo_demo"),
        raising=True,
    )
    monkeypatch.setattr(
        _ast_index,
        "understand_project",
        lambda repo_path, query, max_modules=8, max_slices=8: {
            "modules": [
                {
                    "path": "context/order/src/",
                    "file_count": 1184,
                    "kinds": {"class": 1233, "interface": 310},
                    "score": 6.0,
                }
            ],
            "symbols": [
                {
                    "name": "CheckoutPresenter",
                    "kind": "class",
                    "path": "context/order/src/main/CheckoutPresenter.kt",
                    "line": 10,
                    "signature": "class CheckoutPresenter",
                }
            ],
            "slices": [
                {
                    "file_path": "context/order/src/main/CheckoutPresenter.kt",
                    "name": "CheckoutPresenter",
                    "parent_name": "",
                    "chunk_type": "class",
                    "language": "kotlin",
                    "start_line": 10,
                    "end_line": 20,
                    "lines": "10-20",
                    "code": "class CheckoutPresenter",
                    "token_estimate": 6,
                    "score": 8.0,
                    "citation": "context/order/src/main/CheckoutPresenter.kt:10-20",
                    "why_included": "ast_index_symbol",
                }
            ],
        },
        raising=True,
    )

    r = client.post(
        "/project-understand",
        json={"repo": "demo", "query": "checkout payment", "max_slices": 2},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["modules"][0]["path"] == "context/order/src/"
    assert body["symbols"][0]["name"] == "CheckoutPresenter"
    assert body["slices"][0]["file_path"] == "context/order/src/main/CheckoutPresenter.kt"


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
