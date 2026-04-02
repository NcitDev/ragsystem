"""Agno retrieval agent for intelligent search strategy decisions.

Uses local Ollama LLM to decide search strategy from natural language queries.
Degrades gracefully to simple vector search if Ollama unavailable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

from rag.config import get_settings

logger = structlog.get_logger()


@dataclass
class SearchPlan:
    """A search plan decided by the retrieval agent."""

    queries: list[str] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)
    strategy: str = "hybrid"  # hybrid | filtered | graph_walk | aggregate
    top_k: int = 20


_agent = None
_ollama_available: bool | None = None


async def _check_ollama() -> bool:
    """Check if Ollama is running with the agent model."""
    global _ollama_available
    if _ollama_available is not None:
        return _ollama_available

    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{settings.llm.ollama_url}/api/tags")
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                _ollama_available = any(settings.llm.agent_model in m for m in models)
            else:
                _ollama_available = False
    except Exception:
        _ollama_available = False

    return _ollama_available


def _get_agent():
    """Lazy-init the Agno retrieval agent."""
    global _agent
    if _agent is not None:
        return _agent

    from agno.agent import Agent
    from agno.models.ollama import Ollama

    settings = get_settings()

    _agent = Agent(
        name="RAG Retrieval Agent",
        model=Ollama(
            id=settings.llm.agent_model,
            host=settings.llm.ollama_url,
        ),
        instructions=[
            "You are a code search strategy planner.",
            "Given a user query about code, output a JSON search plan.",
            "The plan must have these fields:",
            '  - "queries": list of search queries (expanded with synonyms)',
            '  - "filters": dict of Qdrant payload filters (e.g. {"language": "python", "patterns": "repository"})',
            '  - "strategy": one of "hybrid", "filtered", "graph_walk", "aggregate"',
            '  - "top_k": number of results (default 20)',
            "",
            "Strategy guide:",
            '  - "hybrid": default, uses dense + sparse vector search',
            '  - "filtered": when user asks for specific patterns/language/complexity',
            '  - "graph_walk": when user asks about call chains or relationships',
            '  - "aggregate": when user asks about codebase-level stats',
            "",
            "Available filter fields: language, chunk_type, patterns, domains, layers,",
            "  is_async, complexity_cyclomatic, nesting_depth, has_docstring, decorator_tags",
            "",
            "Output ONLY valid JSON, no markdown, no explanation.",
        ],
        markdown=False,
    )
    logger.info("agno_agent_initialized", model=settings.llm.agent_model)
    return _agent


async def plan_search(query: str) -> SearchPlan:
    """Use Agno agent to decide search strategy.

    Falls back to simple query expansion if Ollama unavailable.
    """
    if not await _check_ollama():
        return _fallback_plan(query)

    try:
        agent = _get_agent()
        response = agent.run(query)

        # Parse JSON from agent response
        content = response.content
        if not content:
            return _fallback_plan(query)

        # Try to extract JSON from response
        text = content.strip()
        # Handle markdown code blocks
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        data = json.loads(text)

        return SearchPlan(
            queries=data.get("queries", [query]),
            filters=data.get("filters", {}),
            strategy=data.get("strategy", "hybrid"),
            top_k=data.get("top_k", 20),
        )

    except Exception as e:
        logger.warning("agent_plan_failed", error=str(e), query=query)
        return _fallback_plan(query)


def _fallback_plan(query: str) -> SearchPlan:
    """Simple fallback when Agno agent is unavailable."""
    from rag.core.query import decompose_query, expand_query

    sub_queries = decompose_query(query)
    expanded = [expand_query(q) for q in sub_queries]

    # Detect if query hints at filters
    filters: dict[str, Any] = {}
    query_lower = query.lower()

    # Language detection
    lang_hints = {
        "python": "python", "py": "python",
        "typescript": "typescript", "ts": "typescript",
        "javascript": "javascript", "js": "javascript",
        "go": "go", "golang": "go",
        "rust": "rust", "rs": "rust",
        "java": "java", "kotlin": "kotlin",
        "c++": "cpp", "cpp": "cpp",
    }
    for hint, lang in lang_hints.items():
        if hint in query_lower.split():
            filters["language"] = lang
            break

    # Pattern detection
    pattern_hints = [
        "singleton", "factory", "repository", "observer", "strategy",
        "adapter", "decorator", "command", "builder", "middleware",
    ]
    for p in pattern_hints:
        if p in query_lower:
            filters["patterns"] = p
            break

    # Complexity detection
    if any(w in query_lower for w in ["complex", "complicated", "deeply nested"]):
        filters["complexity_cyclomatic"] = 10

    # Strategy detection
    strategy = "hybrid"
    if filters:
        strategy = "filtered"
    if any(w in query_lower for w in ["calls", "uses", "depends", "flow", "chain"]):
        strategy = "graph_walk"
    if any(w in query_lower for w in ["how many", "count", "all patterns", "statistics"]):
        strategy = "aggregate"

    return SearchPlan(
        queries=expanded,
        filters=filters,
        strategy=strategy,
    )
