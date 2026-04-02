"""Tests for retrieval agent fallback logic."""

import asyncio

from rag.agents.retrieval import _fallback_plan, SearchPlan


def test_fallback_detects_language():
    plan = asyncio.run(async_fallback("find python singletons"))
    assert plan.filters.get("language") == "python"


def test_fallback_detects_pattern():
    plan = asyncio.run(async_fallback("find all repository classes"))
    assert plan.filters.get("patterns") == "repository"


def test_fallback_detects_complexity():
    plan = asyncio.run(async_fallback("show complex functions"))
    assert plan.filters.get("complexity_cyclomatic") == 10


def test_fallback_strategy_filtered():
    plan = asyncio.run(async_fallback("find python factories"))
    assert plan.strategy == "filtered"


def test_fallback_strategy_graph():
    plan = asyncio.run(async_fallback("what calls the login function"))
    assert plan.strategy == "graph_walk"


def test_fallback_strategy_aggregate():
    plan = asyncio.run(async_fallback("how many patterns exist"))
    assert plan.strategy == "aggregate"


def test_fallback_expands_query():
    plan = asyncio.run(async_fallback("find auth code"))
    assert any("authentication" in q for q in plan.queries)


async def async_fallback(query: str) -> SearchPlan:
    return _fallback_plan(query)
