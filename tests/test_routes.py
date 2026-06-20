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

    monkeypatch.setattr(_retrieval, "_check_llm_ready", _check_false, raising=True)

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


def test_index_docs_and_docs_search(app_ctx, tmp_path: Path):
    client, token = app_ctx
    doc = tmp_path / "event-catalog.md"
    doc.write_text(
        "# Event Catalog\n\n"
        "START_ORDER_POLLING_AFTER_PAYMENT means order polling after successful payment.",
        encoding="utf-8",
    )

    index_resp = client.post(
        "/index/docs",
        json={"docs_path": str(doc), "doc_types": ["markdown"], "full": True},
        headers=_auth(token),
    )
    assert index_resp.status_code == 200, index_resp.text
    assert index_resp.json()["chunks_indexed"] >= 1

    search_resp = client.post(
        "/docs-search",
        json={"query": "still being created payment polling event", "top_k": 3},
        headers=_auth(token),
    )
    assert search_resp.status_code == 200, search_resp.text
    body = search_resp.json()
    assert body["total"] >= 1
    assert "START_ORDER_POLLING_AFTER_PAYMENT" in body["results"][0]["code"]


def test_search_sanity_filter_removes_noise_for_symbol_queries(app_ctx, monkeypatch):
    client, token = app_ctx
    from rag.core.vectorstore import SearchResult
    import rag.server as _server

    monkeypatch.setattr(
        _server,
        "_collection_for_repo",
        lambda repo: "repo_demo",
        raising=True,
    )

    # Mock vectorstore search to return a target and a noise result
    async def mock_search(collection, query, top_k, filters=None):
        return [
            SearchResult(
                content="class TargetSymbol { void process() {} }",
                score=0.9,
                payload={
                    "file_path": "checkout/TargetSymbol.kt",
                    "name": "TargetSymbol",
                    "chunk_type": "class",
                },
                point_id="1"
            ),
            SearchResult(
                content="class NoiseClass { void verify() {} }",
                score=0.8,
                payload={
                    "file_path": "checkout/NoiseClass.kt",
                    "name": "NoiseClass",
                    "chunk_type": "class",
                },
                point_id="2"
            )
        ]

    vectorstore = _server.get_vectorstore()
    monkeypatch.setattr(vectorstore, "search", mock_search)

    # Search query has CamelCase TargetSymbol. NoiseClass should be pruned.
    r = client.post(
        "/search",
        json={"query": "Explain how TargetSymbol works", "repo": "demo"},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert len(body["results"]) == 1
    assert body["results"][0]["file_path"] == "checkout/TargetSymbol.kt"


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
        lambda repo_path, query, limit=12, include_usages=True: [
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


def test_resolve_returns_structural_usages_from_qdrant(app_ctx, monkeypatch):
    client, token = app_ctx
    from unittest.mock import AsyncMock
    from types import SimpleNamespace
    import rag.server as _server

    monkeypatch.setattr(
        _server,
        "_repo_info_for_name",
        lambda repo: SimpleNamespace(path="/tmp/demo", collection="repo_demo"),
        raising=True,
    )

    # Mock Qdrant client scroll method
    # 1st call resolves symbol definitions FQN
    # 2nd call retrieves inherits/references FQN callers
    mock_scroll = AsyncMock()
    mock_scroll.side_effect = [
        (
            [
                SimpleNamespace(
                    id="id-1",
                    payload={"defines_fqn": "org.test.MyClass"}
                )
            ],
            None
        ),
        (
            [
                SimpleNamespace(
                    id="id-2",
                    payload={
                        "file_path": "Caller.kt",
                        "start_line": 5,
                        "end_line": 8,
                        "content": "class Caller : MyClass()",
                        "name": "Caller",
                        "chunk_type": "class",
                        "language": "kotlin",
                        "inherits_from": ["org.test.MyClass"]
                    }
                )
            ],
            None
        )
    ]

    import rag.core.ast_index as _ast_index
    monkeypatch.setattr(
        _ast_index,
        "resolve_symbols",
        lambda repo_path, symbols, definitions_limit=20, usages_limit=20: {
            "definitions": [],
            "usages": []
        },
        raising=True,
    )

    vectorstore = _server.get_vectorstore()
    monkeypatch.setattr(vectorstore, "_get_client", AsyncMock(return_value=SimpleNamespace(scroll=mock_scroll)))

    r = client.post(
        "/resolve",
        json={"repo": "demo", "symbols": ["MyClass"], "definitions_limit": 1, "usages_limit": 5},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["total_usages"] >= 1
    assert body["usages"][0]["file_path"] == "Caller.kt"
    assert body["usages"][0]["why_included"] == "inherits_from_relationship"


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


def test_graph_files_lists_indexed_files(app_ctx, monkeypatch):
    client, token = app_ctx
    from rag.core.vectorstore import ChunkDocument
    from rag.storage import db as _db
    import rag.server as _server

    monkeypatch.setattr(
        _server,
        "_repo_info_for_name",
        lambda repo: SimpleNamespace(path="/tmp/demo", collection="repo_demo"),
        raising=True,
    )
    _db.upsert_code_chunks(
        "repo_demo",
        [
            ChunkDocument(
                content="class PaymentPresenter",
                metadata={
                    "file_path": "checkout/PaymentPresenter.kt",
                    "language": "kotlin",
                    "chunk_type": "class",
                    "name": "PaymentPresenter",
                    "parent_name": "",
                    "start_line": 1,
                    "end_line": 3,
                },
                chunk_id="payment-presenter",
            ),
            ChunkDocument(
                content="class PaymentPresenterTest",
                metadata={
                    "file_path": "checkout/PaymentPresenterTest.kt",
                    "language": "kotlin",
                    "chunk_type": "class",
                    "name": "PaymentPresenterTest",
                    "parent_name": "",
                    "start_line": 1,
                    "end_line": 3,
                },
                chunk_id="payment-presenter-test",
            ),
        ],
    )

    r = client.post(
        "/graph/files",
        json={"repo": "demo", "query": "PaymentPresenter", "limit": 10},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    assert body["files"][0]["file_path"] in {
        "checkout/PaymentPresenter.kt",
        "checkout/PaymentPresenterTest.kt",
    }


def test_graph_node_and_relations_return_context_slices(app_ctx, monkeypatch):
    client, token = app_ctx
    import rag.core.graph_tools as _graph_tools
    import rag.server as _server

    candidate = {
        "file_path": "checkout/PaymentPresenter.kt",
        "name": "completePayment",
        "parent_name": "PaymentPresenter",
        "chunk_type": "function",
        "language": "kotlin",
        "start_line": 10,
        "end_line": 14,
        "lines": "10-14",
        "code": "fun completePayment() = analytics.track()",
        "token_estimate": 11,
        "score": 9.0,
        "citation": "checkout/PaymentPresenter.kt:10-14 (completePayment)",
        "why_included": "ast_index_symbol",
    }

    monkeypatch.setattr(
        _server,
        "_repo_info_for_name",
        lambda repo: SimpleNamespace(path="/tmp/demo", collection="repo_demo"),
        raising=True,
    )
    monkeypatch.setattr(
        _graph_tools,
        "node",
        lambda repo_path, collection, symbol, definitions_limit=20, usages_limit=20: {
            "symbol": symbol,
            "definitions": [candidate],
            "usages": [],
            "provenance": "ast_index",
        },
        raising=True,
    )
    monkeypatch.setattr(
        _graph_tools,
        "callers",
        lambda repo_path, symbol, limit=50: [candidate],
        raising=True,
    )
    monkeypatch.setattr(
        _graph_tools,
        "callees",
        lambda repo_path, collection, symbol, limit=50: [{**candidate, "relation_source": "heuristic_source_scan"}],
        raising=True,
    )

    node_resp = client.post(
        "/graph/node",
        json={"repo": "demo", "symbol": "completePayment", "limit": 10},
        headers=_auth(token),
    )
    assert node_resp.status_code == 200, node_resp.text
    assert node_resp.json()["definitions"][0]["file_path"] == "checkout/PaymentPresenter.kt"

    callers_resp = client.post(
        "/graph/callers",
        json={"repo": "demo", "symbol": "completePayment", "limit": 10},
        headers=_auth(token),
    )
    assert callers_resp.status_code == 200, callers_resp.text
    assert callers_resp.json()["relation"] == "callers"

    callees_resp = client.post(
        "/graph/callees",
        json={"repo": "demo", "symbol": "completePayment", "limit": 10},
        headers=_auth(token),
    )
    assert callees_resp.status_code == 200, callees_resp.text
    assert callees_resp.json()["relation_source"] == "heuristic_source_scan"


def test_graph_impact_and_affected_return_metrics(app_ctx, monkeypatch):
    client, token = app_ctx
    import rag.core.graph_tools as _graph_tools
    import rag.server as _server

    monkeypatch.setattr(
        _server,
        "_repo_info_for_name",
        lambda repo: SimpleNamespace(path="/tmp/demo", collection="repo_demo"),
        raising=True,
    )
    monkeypatch.setattr(
        _graph_tools,
        "impact",
        lambda repo_path, collection, symbol, limit=50: {
            "symbol": symbol,
            "definitions": [],
            "usages": [],
            "callers": [],
            "affected_files": ["checkout/PaymentPresenter.kt"],
            "tests": [
                {
                    "file_path": "checkout/PaymentPresenterTest.kt",
                    "language": "kotlin",
                    "chunk_count": 1,
                    "symbol_count": 1,
                    "symbols": ["PaymentPresenterTest"],
                    "updated_at": 0.0,
                    "score": 5.0,
                }
            ],
            "risks": [],
            "metrics": {"affected_file_count": 1, "test_count": 1, "whole_file_reads_avoided": True},
        },
        raising=True,
    )
    monkeypatch.setattr(
        _graph_tools,
        "affected",
        lambda repo_path, collection, files=None, since="HEAD", limit=100: {
            "changed_files": files or ["checkout/PaymentPresenter.kt"],
            "affected_files": ["checkout/PaymentPresenter.kt"],
            "tests": [
                {
                    "file_path": "checkout/PaymentPresenterTest.kt",
                    "language": "kotlin",
                    "chunk_count": 1,
                    "symbol_count": 1,
                    "symbols": ["PaymentPresenterTest"],
                    "updated_at": 0.0,
                    "score": 5.0,
                }
            ],
            "modules": [{"path": "checkout", "file_count": 1}],
            "risks": [],
            "metrics": {"changed_file_count": 1, "test_count": 1, "whole_file_reads_avoided": True},
        },
        raising=True,
    )

    impact_resp = client.post(
        "/graph/impact",
        json={"repo": "demo", "symbol": "completePayment", "limit": 10},
        headers=_auth(token),
    )
    assert impact_resp.status_code == 200, impact_resp.text
    assert impact_resp.json()["metrics"]["whole_file_reads_avoided"] is True
    assert impact_resp.json()["tests"][0]["file_path"] == "checkout/PaymentPresenterTest.kt"

    affected_resp = client.post(
        "/graph/affected",
        json={"repo": "demo", "files": ["checkout/PaymentPresenter.kt"], "limit": 10},
        headers=_auth(token),
    )
    assert affected_resp.status_code == 200, affected_resp.text
    assert affected_resp.json()["affected_files"] == ["checkout/PaymentPresenter.kt"]


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
