"""Agno retrieval agent for intelligent search strategy decisions.

Uses local Ollama LLM to decide search strategy from natural language queries.
Degrades gracefully to simple vector search if Ollama unavailable.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

from rag.config import get_settings
from rag.core.chunker import ChunkType, supported_languages

logger = structlog.get_logger()


# --- Filter value whitelists --------------------------------------------------
#
# Agno LLM and _fallback_plan emit filters as raw strings. A typo or a
# case-mismatched value (e.g. language="kotlinx") would silently match
# zero payloads in Qdrant. We validate enum-like fields against known sets
# and drop unknown values with a warning.
#
# Numeric fields (complexity_cyclomatic, nesting_depth, ...) and
# free-form fields like "patterns" are too dynamic to whitelist and
# pass through untouched.

ALLOWED_FILTER_VALUES: dict[str, set[str]] = {
    "chunk_type": {ct.value for ct in ChunkType},
    "language": set(supported_languages()),
}


def _sanitize_filters(filters: dict[str, Any]) -> dict[str, Any]:
    """Drop filter entries whose value is not in the allowed set.

    Only fields listed in ALLOWED_FILTER_VALUES are validated. All other
    fields (numeric ranges, "patterns", "domains", etc.) pass through.
    Dropped entries are logged at WARNING level.
    """
    if not filters:
        return filters

    cleaned: dict[str, Any] = {}
    for key, value in filters.items():
        allowed = ALLOWED_FILTER_VALUES.get(key)
        if allowed is None:
            # Unvalidated field — pass through.
            cleaned[key] = value
            continue

        # Allow list-of-strings filters too — keep only valid members.
        if isinstance(value, (list, tuple, set)):
            kept = [v for v in value if isinstance(v, str) and v in allowed]
            dropped = [v for v in value if v not in kept]
            if dropped:
                logger.warning(
                    "filter_value_dropped",
                    field=key,
                    dropped=dropped,
                    allowed_count=len(allowed),
                )
            if kept:
                cleaned[key] = kept if len(kept) > 1 else kept[0]
            continue

        if isinstance(value, str) and value in allowed:
            cleaned[key] = value
        else:
            logger.warning(
                "filter_value_dropped",
                field=key,
                value=value,
                allowed_count=len(allowed),
            )
    return cleaned


@dataclass
class SearchPlan:
    """A search plan decided by the retrieval agent."""

    queries: list[str] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)
    # lod_drill = default. Other: hybrid | filtered | graph_walk | aggregate | global | naive
    strategy: str = "lod_drill"
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
            '  - "lod_drill": DEFAULT — hierarchical drill-down (module → file → chunk).',
            '       Best for most queries. Cheaper than flat search; reads ~100-token',
            '       summaries before fetching full code.',
            '  - "hybrid": flat vector search across all chunks (no drill-down).',
            '  - "filtered": when user asks for specific patterns/language/complexity',
            '  - "graph_walk": when user asks about call chains or relationships',
            '  - "aggregate": when user asks about codebase-level stats',
            '  - "global": when user asks for overview/summary of a module or architecture',
            '  - "naive": when user wants simple vector search without reranking',
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


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _extract_json_object(text: str) -> dict | None:
    """Best-effort extraction of a single JSON object from an LLM response.

    Tries, in order: (1) the contents of a ```json fenced block, (2) the raw
    text, (3) the first balanced ``{...}`` span. Returns None if nothing
    parses — the caller logs and falls back. This replaces a fragile
    ``split("```")[1]`` that broke on 0 or 2+ fences.
    """
    candidates: list[str] = []
    m = _FENCE_RE.search(text)
    if m:
        candidates.append(m.group(1).strip())
    candidates.append(text.strip())
    # First balanced object span (greedy from first { to last }).
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])

    for cand in candidates:
        if not cand:
            continue
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None


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

        # Robustly extract a JSON object (handles fenced/unfenced/multi-block).
        data = _extract_json_object(content)
        if data is None:
            logger.warning(
                "agent_plan_unparseable",
                query=query,
                response_preview=content[:200],
            )
            return _fallback_plan(query)

        plan = SearchPlan(
            queries=data.get("queries", [query]),
            filters=_sanitize_filters(data.get("filters", {}) or {}),
            strategy=data.get("strategy", "lod_drill"),
            top_k=data.get("top_k", 20),
        )
        return plan

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

    # Strategy detection — lod_drill is the default; specific signals override.
    strategy = "lod_drill"
    if filters:
        strategy = "filtered"
    if any(w in query_lower for w in ["calls", "uses", "depends", "flow", "chain", "trace"]):
        strategy = "graph_walk"
    if any(w in query_lower for w in ["how many", "count", "all patterns", "statistics"]):
        strategy = "aggregate"
    if any(w in query_lower for w in ["overview", "summary", "what does this", "architecture", "main purpose", "module"]):
        strategy = "global"
    # ``naive`` historically meant "vector search without rerank". Now
    # that rerank is gone it's effectively an alias for ``hybrid``; kept
    # as a distinct value for plan-shape compatibility.
    if any(w in query_lower for w in ["exact", "literal", "raw search"]):
        strategy = "naive"

    return SearchPlan(
        queries=expanded,
        filters=_sanitize_filters(filters),
        strategy=strategy,
    )
