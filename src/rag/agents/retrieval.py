"""Agno retrieval agent for intelligent search strategy decisions.

Uses Gemini LLM to decide search strategy from natural language queries.
Degrades gracefully to simple vector search if Gemini is unavailable.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from typing import Any

import structlog

from rag.config import get_settings, RetrievalAgentSettings
from rag.core.chunker import ChunkType, supported_languages
from rag.core.patterns import (
    DECORATOR_PATTERNS,
    DOMAIN_KEYWORDS,
    LAYER_KEYWORDS,
    NAME_PATTERNS,
)

logger = structlog.get_logger()


# --- Filter value whitelists --------------------------------------------------
#
# Agno LLM and _fallback_plan emit filters as raw strings. A typo or a
# case-mismatched value (e.g. language="kotlinx") would silently match
# zero payloads in Qdrant. We validate enum-like fields against known sets
# and drop unknown values with a warning.
#
# The metadata fields (patterns / decorator_tags / domains / layers) are
# CONTROLLED VOCABULARIES — the chunker only ever tags chunks with the keys
# defined in core/patterns.py. The LLM planner, however, tends to invent
# values (e.g. patterns="FullBackupExporter", patterns="event"). Passed as a
# hard Qdrant filter, an invented value matches zero chunks and silently zeroes
# out recall (measured: it was the main reason the LLM planner scored *below*
# the heuristic fallback). So we validate these against the canonical keys and
# drop anything else. Numeric fields (complexity_cyclomatic, nesting_depth, …)
# stay free-form and pass through untouched.

ALLOWED_FILTER_VALUES: dict[str, set[str]] = {
    "chunk_type": {ct.value for ct in ChunkType},
    "language": set(supported_languages()),
    "patterns": set(NAME_PATTERNS),
    "decorator_tags": set(DECORATOR_PATTERNS),
    "domains": set(DOMAIN_KEYWORDS),
    "layers": set(LAYER_KEYWORDS),
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
_llm_available: bool | None = None


_RETRIEVAL_INSTRUCTIONS = [
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
]


def _build_model(cfg: RetrievalAgentSettings):
    """Instantiate the Agno model for the configured provider."""
    provider = cfg.provider
    if provider == "gemini":
        from agno.models.google import Gemini
        return Gemini(id=cfg.model, api_key=os.environ.get(cfg.api_key_env))
    elif provider == "openai":
        from agno.models.openai import OpenAIChat
        return OpenAIChat(id=cfg.model, api_key=os.environ.get(cfg.api_key_env))
    elif provider == "anthropic":
        from agno.models.anthropic import Claude
        return Claude(id=cfg.model, api_key=os.environ.get(cfg.api_key_env))
    elif provider == "ollama":
        from agno.models.ollama import Ollama
        return Ollama(id=cfg.model, host=cfg.base_url or "http://localhost:11434")
    else:
        raise ValueError(f"Unknown retrieval_agent provider: {provider}")


async def _check_llm_ready() -> bool:
    """Check if the configured LLM provider is available."""
    global _llm_available
    if _llm_available is not None:
        return _llm_available

    cfg = get_settings().retrieval_agent
    if cfg.provider == "ollama":
        # Ollama is always "available" if configured — it's local.
        _llm_available = True
    elif cfg.provider == "agy":
        # Antigravity CLI: available iff the `agy` binary is on PATH.
        _llm_available = shutil.which("agy") is not None
    else:
        _llm_available = bool(os.environ.get(cfg.api_key_env))
    return _llm_available


def _get_agent():
    """Lazy-init the Agno retrieval agent."""
    global _agent
    if _agent is not None:
        return _agent

    from agno.agent import Agent

    cfg = get_settings().retrieval_agent
    model = _build_model(cfg)
    _agent = Agent(
        name="RAG Retrieval Agent",
        model=model,
        instructions=_RETRIEVAL_INSTRUCTIONS,
        markdown=False,
    )
    logger.info("agno_agent_initialized", provider=cfg.provider, model=cfg.model)
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


_AGY_TIMEOUT_S = 90.0


def _plan_from_data(data: dict, query: str) -> SearchPlan:
    """Build a SearchPlan from a parsed LLM JSON object."""
    return SearchPlan(
        queries=data.get("queries", [query]),
        filters=_sanitize_filters(data.get("filters", {}) or {}),
        strategy=data.get("strategy", "lod_drill"),
        top_k=data.get("top_k", 20),
    )


async def _run_agy_planner(query: str, cfg: RetrievalAgentSettings) -> SearchPlan:
    """Plan via the Antigravity ``agy`` CLI (subscription auth, no API key).

    Spawns ``agy -p <prompt>`` as an *async* subprocess so the daemon's single
    event loop is never blocked while the model thinks (~5-10s). Degrades to
    ``_fallback_plan`` on timeout, a missing binary, or non-JSON output.
    """
    prompt = "\n".join(_RETRIEVAL_INSTRUCTIONS) + f"\n\nUser query: {query}\n\nJSON plan:"
    args = ["agy", "-p", prompt]
    if cfg.model:
        args += ["--model", cfg.model]

    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _err = await asyncio.wait_for(proc.communicate(), timeout=_AGY_TIMEOUT_S)
    except (asyncio.TimeoutError, FileNotFoundError, OSError) as exc:
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        logger.warning("agy_planner_failed", error=str(exc), query=query)
        return _fallback_plan(query)

    text = out.decode(errors="replace") if out else ""
    data = _extract_json_object(text)
    if data is None:
        logger.warning("agy_plan_unparseable", query=query, response_preview=text[:200])
        return _fallback_plan(query)
    return _plan_from_data(data, query)


_SYMBOL_PROMPT = (
    "Output a JSON array of up to 5 likely PascalCase class/interface names that "
    "would DEFINE what this question is about (infer them even if not literally "
    "present in the question). Array only, no prose: "
)


async def infer_symbols(question: str, timeout: float = 30.0) -> list[str]:
    """LLM-infer candidate symbol names from a natural-language question.

    This is what makes symbol routing work on vague questions: a regex can't
    turn "sticker pack install event" into ``StickerPackInstallEvent``, but the
    model can — and feeding that to ``/resolve`` finds the exact definition that
    semantic search buries. agy-only (subscription auth, no API key); returns []
    on a non-agy provider, timeout, or non-array output so callers degrade to
    semantic search. Run from ``/tmp`` with a lean prompt — agy's agentic mode
    (which hangs ``-p``) triggers on project-dir + verbose prompts.
    """
    cfg = get_settings().retrieval_agent
    if cfg.provider != "agy" or shutil.which("agy") is None:
        return []

    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await asyncio.create_subprocess_exec(
            "agy", "-p", _SYMBOL_PROMPT + question, "--model", cfg.model,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd="/tmp",
        )
        out, _err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except (asyncio.TimeoutError, FileNotFoundError, OSError) as exc:
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        logger.warning("infer_symbols_failed", error=str(exc), question=question)
        return []

    text = out.decode(errors="replace") if out else ""
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    return [s for s in arr if isinstance(s, str) and s][:5]


async def plan_search(query: str) -> SearchPlan:
    """Use the configured LLM to decide search strategy.

    Falls back to simple query expansion if the LLM is unavailable.
    """
    if not await _check_llm_ready():
        return _fallback_plan(query)

    cfg = get_settings().retrieval_agent
    if cfg.provider == "agy":
        return await _run_agy_planner(query, cfg)

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
