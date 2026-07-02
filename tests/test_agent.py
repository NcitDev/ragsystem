"""Tests for retrieval agent fallback logic."""

import asyncio

from rag.agents.retrieval import (
    _fallback_plan,
    _sanitize_filters,
    SearchPlan,
)


def test_fallback_detects_language():
    plan = asyncio.run(async_fallback("find python singletons"))
    assert plan.filters.get("language") == "python"


def test_fallback_detects_pattern():
    plan = asyncio.run(async_fallback("find all repository classes"))
    assert plan.filters.get("patterns") == "repository"


def test_fallback_detects_complexity():
    plan = asyncio.run(async_fallback("show complex functions"))
    assert plan.filters.get("complexity_cyclomatic") == 10


def test_fallback_strategy_filters_use_hybrid():
    plan = asyncio.run(async_fallback("find python factories"))
    assert plan.strategy == "hybrid"


def test_fallback_strategy_graph():
    plan = asyncio.run(async_fallback("what calls the login function"))
    assert plan.strategy == "graph_walk"


def test_fallback_strategy_stats_use_hybrid():
    plan = asyncio.run(async_fallback("how many patterns exist"))
    assert plan.strategy == "hybrid"


def test_fallback_expands_query():
    plan = asyncio.run(async_fallback("find auth code"))
    assert any("authentication" in q for q in plan.queries)


async def async_fallback(query: str) -> SearchPlan:
    return _fallback_plan(query)


def test_sanitize_drops_unknown_language():
    # "kotlinx" is not a real supported language — must be dropped.
    cleaned = _sanitize_filters({"language": "kotlinx"})
    assert "language" not in cleaned


def test_sanitize_keeps_known_language():
    cleaned = _sanitize_filters({"language": "python"})
    assert cleaned.get("language") == "python"


def test_sanitize_keeps_unvalidated_fields():
    # patterns + numeric fields are pass-through.
    cleaned = _sanitize_filters(
        {"patterns": "repository", "complexity_cyclomatic": 10}
    )
    assert cleaned.get("patterns") == "repository"
    assert cleaned.get("complexity_cyclomatic") == 10


def test_sanitize_drops_unknown_chunk_type():
    cleaned = _sanitize_filters({"chunk_type": "not_a_real_type"})
    assert "chunk_type" not in cleaned


def test_fallback_plan_drops_bogus_filter_when_no_lang_hint():
    # Sanity: fallback never emits a bogus language on its own — but if a
    # malicious/typo'd filter ever sneaked in, sanitation strips it.
    bogus = {"language": "kotlinx", "patterns": "repository"}
    cleaned = _sanitize_filters(bogus)
    assert "language" not in cleaned
    assert cleaned.get("patterns") == "repository"
