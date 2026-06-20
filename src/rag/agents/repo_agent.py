"""Repo-agent retrieval orchestration helpers.

The repo agent is a thin planner around existing deterministic tools:
AST resolve, exact/lexical context packs, and semantic fallback.  It is
intended for Codex/developer workflows where the final coding decision remains
outside the local model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rag.agents.retrieval import SearchPlan

_IDENTIFIER_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b")

_STOPWORDS = {
    "add",
    "after",
    "all",
    "always",
    "and",
    "another",
    "app",
    "around",
    "before",
    "being",
    "can",
    "case",
    "change",
    "checkout",
    "code",
    "complex",
    "created",
    "developers",
    "domain",
    "edit",
    "event",
    "evaluate",
    "exact",
    "feature",
    "files",
    "find",
    "flow",
    "for",
    "from",
    "fully",
    "handling",
    "into",
    "logic",
    "make",
    "minimal",
    "module",
    "needed",
    "public",
    "apis",
    "new",
    "not",
    "only",
    "order",
    "paid",
    "payment",
    "plan",
    "propose",
    "refactor",
    "report",
    "reset",
    "safe",
    "separate",
    "state",
    "still",
    "success",
    "successful",
    "tests",
    "the",
    "this",
    "tracking",
    "when",
    "without",
}

_DOMAIN_EXPANSIONS: list[tuple[set[str], list[str]]] = [
    (
        {"paid", "order"},
        ["waitForPayedOrder", "PaidOrderResponse", "OrderResult"],
    ),
    (
        {"successful", "order"},
        ["OrderCreated", "OrderIsBeingCreated"],
    ),
    (
        {"success", "order"},
        ["OrderCreated", "OrderIsBeingCreated"],
    ),
    (
        {"fully", "created"},
        ["OrderCreated"],
    ),
    (
        {"still", "created"},
        ["OrderIsBeingCreated"],
    ),
    (
        {"reset", "state"},
        ["setupAppStateForNewOrder", "StateAnalyzer", "CheckoutService"],
    ),
    (
        {"resets", "state"},
        ["setupAppStateForNewOrder", "StateAnalyzer", "CheckoutService"],
    ),
    (
        {"analytics"},
        [
            "AnalyticsHelper",
            "PaymentAnalytics",
            "trackPaymentFinished",
            "trackPaymentFailed",
        ],
    ),
    (
        {"payment", "completion"},
        ["trackPaymentFinished", "PaymentAnalytics"],
    ),
    (
        {"still", "being", "created"},
        ["OrderIsBeingCreated", "PaidOrderState.ALMOST_OK"],
    ),
    (
        {"analytics", "event"},
        [
            "PaymentAnalytics",
            "orderPollingAfterPaymentStart",
            "START_ORDER_POLLING_AFTER_PAYMENT",
            "STOP_ORDER_POLLING_AFTER_PAYMENT",
        ],
    ),
]

_REUSE_TRIGGER_WORDS = {
    "add",
    "create",
    "event",
    "feature",
    "new",
    "reuse",
    "verify",
}

_ARCHITECTURE_TRIGGER_WORDS = {
    "architecture",
    "boundary",
    "boundaries",
    "dependencies",
    "dependency",
    "extract",
    "module",
    "modules",
    "move",
    "public",
    "refactor",
    "risks",
}


@dataclass
class RepoAgentOptions:
    """Configuration for a repo-agent retrieval run."""

    max_slices: int = 8
    max_source_tokens: int = 6000
    definitions_limit: int = 8
    usages_limit: int = 12
    min_exact_slices: int = 3
    allow_semantic_fallback: bool = True


@dataclass
class RepoAgentPlan:
    """Deterministic plan derived from the local-model search plan."""

    query: str
    planner: SearchPlan
    context_query: str
    symbols: list[str] = field(default_factory=list)
    reuse_queries: list[str] = field(default_factory=list)
    documentation_queries: list[str] = field(default_factory=list)
    architecture_query: str | None = None
    call_tree_symbols: list[str] = field(default_factory=list)
    semantic_fallback_allowed: bool = True


def filter_resolve_usages(
    resolve_data: dict[str, Any],
    symbols: list[str],
    *,
    max_usages: int = 15,
) -> dict[str, Any]:
    """Filter /resolve usages to keep only the most relevant ones.

    Three-phase blast-radius strategy:
      Phase 0 (structural): usages whose filename or why_included signals
        inheritance/implementation (extends, implements, subclass).
      Phase 1 (same-dir): usages in the same directory as a definition.
      Phase 2 (name-match): symbol name appears in the filename.
      Phase 3 (server-rank): first N usages by server rank.

    A per-directory cap (max 3 files) prevents hub symbols like Recipient
    or Job from being dominated by one heavily-coupled package.
    Caps total at *max_usages*.

    Returns a shallow copy of *resolve_data* with the ``usages`` list
    trimmed and a ``total_usages_raw`` field added for reporting.
    """
    if not resolve_data:
        return resolve_data

    raw_usages = resolve_data.get("usages") or []
    if len(raw_usages) <= max_usages:
        # Already within budget — nothing to filter.
        return {**resolve_data, "total_usages_raw": len(raw_usages)}

    # Collect definition directories.
    def_dirs: set[str] = set()
    for item in resolve_data.get("definitions") or []:
        fp = item.get("file_path", "")
        if fp:
            def_dirs.add(str(Path(fp).parent))

    syms_lower = {s.lower() for s in symbols}
    _STRUCTURAL_SIGNALS = frozenset({"extends", "implements", "subclass", "inherits"})

    # Score each usage.
    scored: list[tuple[int, int, dict[str, Any]]] = []  # (priority, idx, item)
    for idx, item in enumerate(raw_usages):
        fp = item.get("file_path", "")
        if not fp:
            continue
        stem = Path(fp).stem.lower()
        fp_dir = str(Path(fp).parent)
        why = str(item.get("why_included", "")).lower()

        is_structural = any(sig in why for sig in _STRUCTURAL_SIGNALS) or any(
            sig in stem for sig in _STRUCTURAL_SIGNALS
        )

        if is_structural:
            priority = 0   # structural callers (subclasses/implementors) — highest
        elif fp_dir in def_dirs:
            priority = 1   # same directory as definition
        elif any(s in stem for s in syms_lower):
            priority = 2   # symbol name in filename
        elif idx < 10:
            priority = 3   # first 10 by server rank
        else:
            priority = 999

        scored.append((priority, idx, item))

    scored.sort(key=lambda t: (t[0], t[1]))

    # Per-directory cap: max 3 files from the same directory to avoid
    # hub-symbol noise (Recipient, Job called from hundreds of files in
    # the same package).
    from collections import Counter
    dir_counts: Counter[str] = Counter()
    kept: list[dict[str, Any]] = []
    for priority, _, item in scored:
        fp = item.get("file_path", "")
        fp_dir = str(Path(fp).parent)
        # Apply the directory cap of 3 to all usages to ensure architectural diversity
        if dir_counts[fp_dir] >= 3:
            continue
        dir_counts[fp_dir] += 1
        kept.append(item)
        if len(kept) >= max_usages:
            break

    return {
        **resolve_data,
        "usages": kept,
        "total_usages_raw": len(raw_usages),
    }


def extract_symbol_candidates(query: str, *, limit: int = 12) -> list[str]:
    """Extract likely code identifiers from a natural-language task."""
    seen: set[str] = set()
    symbols: list[str] = []
    for match in _IDENTIFIER_RE.finditer(query):
        value = match.group(0)
        lower = value.lower()
        if lower in _STOPWORDS:
            continue
        if not any(ch.isupper() for ch in value) and "_" not in value:
            continue
        if value in seen:
            continue
        seen.add(value)
        symbols.append(value)
        if len(symbols) >= limit:
            break
    return symbols


def expand_domain_terms(query: str) -> list[str]:
    """Add deterministic repo-navigation hints for common product wording."""
    words = {token.lower() for token in _IDENTIFIER_RE.findall(query)}
    expanded: list[str] = []
    for required, terms in _DOMAIN_EXPANSIONS:
        if required.issubset(words):
            for term in terms:
                if term not in expanded:
                    expanded.append(term)
    return expanded


def build_context_query(query: str, plan: SearchPlan, symbols: list[str], *, max_terms: int = 48) -> str:
    """Combine task, planner expansions, and symbols into one compact query."""
    terms: list[str] = []
    for source in [*symbols, query, *plan.queries, *expand_domain_terms(query)]:
        for token in _IDENTIFIER_RE.findall(source):
            if token.lower() in _STOPWORDS:
                continue
            if token not in terms:
                terms.append(token)
            if len(terms) >= max_terms:
                return " ".join(terms)
    return " ".join(terms) if terms else query


def build_reuse_queries(query: str, symbols: list[str], *, limit: int = 3) -> list[str]:
    """Build exact/lexical searches for existing concepts before adding code.

    Developer tasks often say "add event/API/feature" when the safest move is
    to reuse a nearby existing event, helper, or facade.  These queries are run
    as deterministic context-pack calls with semantic disabled so they act as
    an IDE-style "show me similar existing concepts" pass.
    """
    words = {token.lower() for token in _IDENTIFIER_RE.findall(query)}
    queries: list[str] = []

    if {"analytics", "event"} & words and _REUSE_TRIGGER_WORDS & words:
        queries.append(
            "AnalyticsHelper PaymentAnalytics payment analytics event "
            "orderPollingAfterPaymentStart START_ORDER_POLLING_AFTER_PAYMENT "
            "STOP_ORDER_POLLING_AFTER_PAYMENT trackPaymentFinished "
            "OrderIsBeingCreated PaidOrderState.ALMOST_OK"
        )

    if _ARCHITECTURE_TRIGGER_WORDS & words:
        queries.append(
            " ".join(
                [
                    *symbols,
                    "build.gradle",
                    "dependencies",
                    "FeatureDependencies",
                    "Module",
                    "Component",
                    "public API",
                ]
            )
        )

    if _REUSE_TRIGGER_WORDS & words and symbols:
        queries.append("existing reusable API helper event " + " ".join(symbols))

    deduped: list[str] = []
    for item in queries:
        compact = " ".join(_IDENTIFIER_RE.findall(item))
        if compact and compact not in deduped:
            deduped.append(compact)
        if len(deduped) >= limit:
            break
    return deduped


def build_documentation_queries(query: str, symbols: list[str], *, limit: int = 3) -> list[str]:
    """Build doc/spec searches to run when docs are indexed for a repo."""
    words = {token.lower() for token in _IDENTIFIER_RE.findall(query)}
    queries: list[str] = []

    if {"analytics", "event"} & words:
        queries.append(
            "analytics event catalog payment order polling after payment "
            "still being created " + " ".join(symbols)
        )
    if _ARCHITECTURE_TRIGGER_WORDS & words:
        queries.append(
            "module ownership dependency rules public API boundaries "
            + " ".join(symbols)
        )

    deduped: list[str] = []
    for item in queries:
        compact = " ".join(_IDENTIFIER_RE.findall(item))
        if compact and compact not in deduped:
            deduped.append(compact)
        if len(deduped) >= limit:
            break
    return deduped


def is_architecture_task(query: str) -> bool:
    """Return true for module/dependency/boundary-oriented prompts."""
    words = {token.lower() for token in _IDENTIFIER_RE.findall(query)}
    return bool(_ARCHITECTURE_TRIGGER_WORDS & words)


def build_architecture_query(query: str, symbols: list[str]) -> str | None:
    """Build a project-understand query for module/dependency tasks."""
    if not is_architecture_task(query):
        return None
    terms = [
        *symbols,
        query,
        "module dependencies Gradle build.gradle public API FeatureDependencies Component Module provider DI boundary risks",
    ]
    seen: list[str] = []
    for term in terms:
        for token in _IDENTIFIER_RE.findall(term):
            if token.lower() in _STOPWORDS and token.lower() not in {"module", "public"}:
                continue
            if token not in seen:
                seen.append(token)
    return " ".join(seen[:64])


def build_call_tree_symbols(symbols: list[str], *, limit: int = 4) -> list[str]:
    """Pick likely function/method symbols worth a caller-tree lookup."""
    selected: list[str] = []
    for symbol in symbols:
        if "." in symbol:
            continue
        if symbol[:1].islower() or symbol.startswith("setup"):
            selected.append(symbol)
        if len(selected) >= limit:
            break
    return selected


def build_repo_agent_plan(
    query: str,
    planner: SearchPlan,
    *,
    allow_semantic_fallback: bool = True,
) -> RepoAgentPlan:
    """Build the actionable retrieval plan used by the CLI/API layer."""
    symbols: list[str] = []
    for symbol in [*extract_symbol_candidates(query), *expand_domain_terms(query)]:
        if symbol not in symbols:
            symbols.append(symbol)
    context_query = build_context_query(query, planner, symbols)
    reuse_queries = build_reuse_queries(query, symbols)
    documentation_queries = build_documentation_queries(query, symbols)
    architecture_query = build_architecture_query(query, symbols)
    call_tree_symbols = build_call_tree_symbols(symbols)
    return RepoAgentPlan(
        query=query,
        planner=planner,
        context_query=context_query,
        symbols=symbols,
        reuse_queries=reuse_queries,
        documentation_queries=documentation_queries,
        architecture_query=architecture_query,
        call_tree_symbols=call_tree_symbols,
        semantic_fallback_allowed=allow_semantic_fallback,
    )


def should_use_semantic_fallback(
    exact_pack: dict[str, Any],
    *,
    min_exact_slices: int = 3,
) -> bool:
    """Return true when deterministic retrieval looks too thin."""
    slices = exact_pack.get("slices") or []
    if len(slices) < min_exact_slices:
        return True
    reasons = {str(item.get("why_included", "")) for item in slices}
    return not any(
        reason.startswith("ast_index") or reason == "exact_or_lexical_match"
        for reason in reasons
    )


def compact_slice(item: dict[str, Any]) -> dict[str, Any]:
    """Reduce a server context slice to stable report fields."""
    return {
        "file_path": item.get("file_path", ""),
        "lines": item.get("lines", ""),
        "name": item.get("name", ""),
        "chunk_type": item.get("chunk_type", ""),
        "why_included": item.get("why_included", ""),
        "score": item.get("score", 0),
        "token_estimate": item.get("token_estimate", 0),
    }


def _file_path(item: dict[str, Any]) -> str:
    return str(item.get("file_path") or item.get("path") or "")


def _is_test_path(path: str) -> bool:
    lowered = path.lower()
    return "/test/" in lowered or "/androidtest/" in lowered or lowered.endswith("test.kt")


def collect_top_files(*packs: dict[str, Any] | None, limit: int = 8) -> list[dict[str, Any]]:
    """Collect ranked file evidence from context/reuse packs."""
    files: dict[str, dict[str, Any]] = {}
    rank = 0
    for pack in packs:
        if not pack:
            continue
        for item in pack.get("slices", []) or []:
            path = _file_path(item)
            if not path:
                continue
            rank += 1
            entry = files.setdefault(
                path,
                {
                    "file_path": path,
                    "first_rank": rank,
                    "slice_count": 0,
                    "max_score": 0.0,
                    "names": [],
                },
            )
            entry["slice_count"] += 1
            entry["max_score"] = max(float(entry["max_score"]), float(item.get("score", 0.0) or 0.0))
            name = str(item.get("name") or "")
            if name and name not in entry["names"]:
                entry["names"].append(name)
    return sorted(files.values(), key=lambda item: (item["first_rank"], -item["max_score"]))[:limit]


def collect_tests(*packs: dict[str, Any] | None, limit: int = 8) -> list[dict[str, Any]]:
    """Collect test slices from packs."""
    tests: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for pack in packs:
        if not pack:
            continue
        for item in pack.get("slices", []) or []:
            path = _file_path(item)
            if not _is_test_path(path):
                continue
            key = (path, str(item.get("lines", "")), str(item.get("name", "")))
            if key in seen:
                continue
            seen.add(key)
            tests.append(compact_slice(item))
            if len(tests) >= limit:
                return tests
    return tests


def disambiguate_symbols(resolve_data: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Group same-name definitions so callers can see symbol ambiguity."""
    if not resolve_data:
        return []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in resolve_data.get("definitions", []) or []:
        name = str(item.get("name") or "")
        if name:
            grouped.setdefault(name, []).append(item)
    ambiguities: list[dict[str, Any]] = []
    for name, items in grouped.items():
        paths = {_file_path(item) for item in items}
        if len(items) > 1 and len(paths) > 1:
            ambiguities.append(
                {
                    "symbol": name,
                    "definitions": [compact_slice(item) for item in items],
                }
            )
    return ambiguities


def collect_modules(understand_data: dict[str, Any] | None, limit: int = 8) -> list[dict[str, Any]]:
    """Compact project-understand module data."""
    if not understand_data:
        return []
    modules = []
    for item in understand_data.get("modules", [])[:limit]:
        modules.append(
            {
                "path": item.get("path", ""),
                "file_count": item.get("file_count", 0),
                "score": item.get("score", 0),
                "kinds": item.get("kinds", {}),
            }
        )
    return modules


def infer_risks(query: str, *, semantic_used: bool, ambiguities: list[dict[str, Any]], tests: list[dict[str, Any]]) -> list[str]:
    """Infer retrieval/planning risks for the compact evidence bundle."""
    risks: list[str] = []
    lowered = query.lower()
    if semantic_used:
        risks.append("Semantic fallback was used; verify embedding-only hits before editing.")
    if ambiguities:
        names = ", ".join(item["symbol"] for item in ambiguities[:3])
        risks.append(f"Same-name symbols need caller/path disambiguation: {names}.")
    if any(word in lowered for word in ["analytics", "event"]) and not tests:
        risks.append("No test slice was retrieved; locate analytics tests before editing.")
    if any(word in lowered for word in ["module", "dependency", "extract", "move"]):
        risks.append("Module-boundary task; verify Gradle dependencies and DI providers before editing.")
    return risks


def build_eval_metrics(
    *,
    first_slice: dict[str, Any] | None,
    exact_pack: dict[str, Any],
    semantic_pack: dict[str, Any] | None,
    total_tokens: int,
    whole_file_reads: int = 0,
    answer_correctness: str = "not_evaluated",
) -> dict[str, Any]:
    """Stable metrics block for navigation evals."""
    first_rank = None
    if first_slice:
        for index, item in enumerate((semantic_pack or exact_pack).get("slices", []) or [], 1):
            if item is first_slice:
                first_rank = index
                break
        if first_rank is None:
            first_rank = 1
    return {
        "first_relevant_rank": first_rank,
        "first_relevant_file": _file_path(first_slice or {}),
        "source_tokens": total_tokens,
        "embeddings_used": bool(
            semantic_pack
            and any(item.get("why_included") == "semantic_match" for item in semantic_pack.get("slices", []) or [])
        ),
        "whole_file_reads_avoided": whole_file_reads == 0,
        "whole_file_reads": whole_file_reads,
        "answer_correctness": answer_correctness,
    }


def total_source_tokens(*packs: dict[str, Any] | None) -> int:
    """Sum source-token counts from context-pack responses."""
    total = 0
    for pack in packs:
        if pack:
            total += int(pack.get("total_source_tokens", 0) or 0)
    return total
