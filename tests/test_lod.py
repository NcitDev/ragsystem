"""Tests for hierarchical LOD (L0/L1) summary generation + lod_drill strategy."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rag.agents.retrieval import _fallback_plan
from rag.core.summaries import (
    LOD_L0_COLLECTION,
    LOD_L1_COLLECTION,
    _module_path_of,
    generate_lod_summaries,
)


# --- _module_path_of ---------------------------------------------------------


def test_module_path_repo_root_file():
    assert _module_path_of("README.md") == "."


def test_module_path_nested():
    assert _module_path_of("src/rag/core/embedder.py") == "src/rag/core"


def test_module_path_single_dir():
    assert _module_path_of("tests/test_foo.py") == "tests"


# --- _fallback_plan default strategy is lod_drill ----------------------------


def test_fallback_default_strategy_is_lod_drill():
    plan = asyncio.run(_async_fallback("retry logic for upload"))
    assert plan.strategy == "lod_drill"


def test_fallback_lod_drill_overridden_by_filter():
    # Language filter triggers "filtered" — overrides default lod_drill.
    plan = asyncio.run(_async_fallback("find python singletons"))
    assert plan.strategy == "filtered"


def test_fallback_lod_drill_overridden_by_graph():
    plan = asyncio.run(_async_fallback("what calls login"))
    assert plan.strategy == "graph_walk"


def test_fallback_lod_drill_overridden_by_global():
    plan = asyncio.run(_async_fallback("overview of architecture"))
    assert plan.strategy == "global"


# --- generate_lod_summaries --------------------------------------------------


@pytest.mark.asyncio
async def test_lod_summary_skipped_when_env_set(monkeypatch):
    monkeypatch.setenv("RAG_SKIP_SUMMARIES", "1")
    vs = MagicMock()
    vs.upsert = AsyncMock()
    chunks = [{"file_path": "a/b.py", "name": "foo", "chunk_type": "function"}]
    l0, l1 = await generate_lod_summaries(chunks, vs)
    assert (l0, l1) == (0, 0)
    vs.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_lod_summary_groups_files_by_module(monkeypatch):
    """Verify chunks are grouped by git-dir and the right collections get upserts."""
    monkeypatch.delenv("RAG_SKIP_SUMMARIES", raising=False)

    chunks = [
        {"file_path": "src/rag/core/embedder.py", "name": "embed", "chunk_type": "function", "language": "python"},
        {"file_path": "src/rag/core/embedder.py", "name": "Embedder", "chunk_type": "class", "language": "python"},
        {"file_path": "src/rag/core/vectorstore.py", "name": "search", "chunk_type": "function", "language": "python"},
        {"file_path": "src/rag/agents/retrieval.py", "name": "plan_search", "chunk_type": "function", "language": "python"},
    ]

    upserts: list[tuple[str, list]] = []

    async def fake_upsert(collection, docs, **kw):
        upserts.append((collection, docs))
        return len(docs)

    vs = MagicMock()
    vs.upsert = fake_upsert
    vs._get_client = AsyncMock(return_value=MagicMock())

    async def fake_gen(prompt, url, model):
        return "Test summary."

    with patch("rag.core.summaries._ollama_generate", side_effect=fake_gen):
        l0, l1 = await generate_lod_summaries(chunks, vs)

    # Expect 2 modules (src/rag/core, src/rag/agents) and 3 files
    assert l1 == 3
    assert l0 == 2

    # Inspect upserts: L1 first, then L0
    collections = [c for c, _ in upserts]
    assert LOD_L1_COLLECTION in collections
    assert LOD_L0_COLLECTION in collections

    # Check L1 payload has module_path + lod_level
    l1_batch = next(docs for c, docs in upserts if c == LOD_L1_COLLECTION)
    assert all(d.metadata.get("lod_level") == "L1" for d in l1_batch)
    assert all(d.metadata.get("module_path") in {"src/rag/core", "src/rag/agents"} for d in l1_batch)

    # Check L0 payload
    l0_batch = next(docs for c, docs in upserts if c == LOD_L0_COLLECTION)
    assert all(d.metadata.get("lod_level") == "L0" for d in l0_batch)


@pytest.mark.asyncio
async def test_lod_summary_no_chunks_no_calls(monkeypatch):
    monkeypatch.delenv("RAG_SKIP_SUMMARIES", raising=False)
    vs = MagicMock()
    vs.upsert = AsyncMock()
    l0, l1 = await generate_lod_summaries([], vs)
    assert (l0, l1) == (0, 0)


# --- helpers -----------------------------------------------------------------


async def _async_fallback(query: str):
    return _fallback_plan(query)
