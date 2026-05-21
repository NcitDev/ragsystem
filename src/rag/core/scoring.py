"""Weighted relevance scoring for search results.

Adjusts base vector search scores by:
- Git recency (recently modified files boosted)
- Pattern importance (domain-relevant patterns boosted)
- Code quality signals (dead code deprioritized, high complexity flagged)
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger()

# Weights for each scoring dimension (sum to ~1.0 with base score)
RECENCY_WEIGHT = 0.15
PATTERN_WEIGHT = 0.10
QUALITY_WEIGHT = 0.05

# Patterns that indicate higher relevance
HIGH_VALUE_PATTERNS = {"repository", "service", "factory", "middleware", "strategy", "observer"}

# Maximum age in days for recency boost (older = no boost)
MAX_RECENCY_DAYS = 90


def score_results(results: list[Any], query: str = "", reranked: bool = False) -> list[Any]:
    """Apply weighted scoring adjustments to search results.

    Mutates result.score in place and returns sorted results.

    The ``reranked`` flag is retained for backwards-compatible signature
    (the cross-encoder reranker was removed alongside FastEmbed). When
    True the function still returns results untouched — useful if a
    caller has externally calibrated scores it doesn't want disturbed.
    """
    if reranked:
        return results

    for r in results:
        payload = r.payload if hasattr(r, "payload") else {}
        base_score = r.score if hasattr(r, "score") else 0.0

        recency_boost = _recency_score(payload)
        pattern_boost = _pattern_score(payload, query)
        quality_boost = _quality_score(payload)

        # Weighted combination: base score dominates, boosts are additive
        adjusted = base_score + (recency_boost * RECENCY_WEIGHT) + (pattern_boost * PATTERN_WEIGHT) + (quality_boost * QUALITY_WEIGHT)
        r.score = adjusted

    results.sort(key=lambda r: r.score, reverse=True)
    return results


def _recency_score(payload: dict[str, Any]) -> float:
    """Score 0-1 based on git last modified date. Recent = higher."""
    last_modified = payload.get("git_last_modified", "")
    if not last_modified:
        return 0.0

    try:
        modified_date = datetime.fromisoformat(last_modified).replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        days_ago = (now - modified_date).days
        if days_ago <= 0:
            return 1.0
        if days_ago >= MAX_RECENCY_DAYS:
            return 0.0
        # Exponential decay
        return math.exp(-days_ago / (MAX_RECENCY_DAYS / 3))
    except (ValueError, TypeError):
        return 0.0


def _pattern_score(payload: dict[str, Any], query: str) -> float:
    """Score 0-1 based on pattern relevance to query."""
    patterns = payload.get("patterns", [])
    if not patterns:
        return 0.0

    # High-value patterns get a boost
    has_high_value = any(p in HIGH_VALUE_PATTERNS for p in patterns)

    # If query mentions a pattern, boost exact match
    query_lower = query.lower()
    has_query_match = any(p in query_lower for p in patterns)

    if has_query_match:
        return 1.0
    if has_high_value:
        return 0.5
    return 0.2


def _quality_score(payload: dict[str, Any]) -> float:
    """Score -1 to 1 based on code quality signals. Bad quality = negative."""
    score = 0.0

    # Dead code candidate: penalize
    if payload.get("dead_code_candidate", False):
        score -= 0.5

    # Has docstring: small boost
    if payload.get("has_docstring", False):
        score += 0.2

    # Public: slight boost (more likely to be relevant API)
    if payload.get("is_public", True):
        score += 0.1

    # Very high complexity: slight penalty (harder to understand)
    complexity = payload.get("complexity_cyclomatic", 0)
    if isinstance(complexity, (int, float)) and complexity > 20:
        score -= 0.2

    # Has tests: boost (more trustworthy code)
    if payload.get("has_unit_test", False):
        score += 0.3

    return max(-1.0, min(1.0, score))
