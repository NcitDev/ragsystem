"""Query expansion and decomposition for code search."""

from __future__ import annotations

import re

QUERY_EXPANSIONS: dict[str, list[str]] = {
    "auth": ["auth", "authentication", "login", "signin", "security", "oauth", "jwt"],
    "db": ["db", "database", "repository", "dao", "storage", "persistence", "orm"],
    "api": ["api", "endpoint", "route", "handler", "controller", "rest"],
    "test": ["test", "spec", "assertion", "mock", "fixture", "pytest", "junit"],
    "config": ["config", "configuration", "settings", "environment", "env", "properties"],
    "log": ["log", "logging", "logger", "trace", "debug", "structlog"],
    "cache": ["cache", "caching", "redis", "memcached", "ttl", "invalidation"],
    "queue": ["queue", "message", "kafka", "rabbitmq", "event", "pubsub", "broker"],
    "error": ["error", "exception", "failure", "catch", "throw", "raise", "fault"],
    "async": ["async", "await", "coroutine", "future", "promise", "concurrent", "parallel"],
    "deploy": ["deploy", "deployment", "ci", "cd", "pipeline", "release", "docker"],
    "migrate": ["migrate", "migration", "schema", "alembic", "flyway", "upgrade"],
    "validate": ["validate", "validation", "check", "verify", "sanitize", "constraint"],
    "serialize": ["serialize", "serialization", "json", "marshal", "encode", "decode", "parse"],
    "di": ["di", "dependency", "injection", "inject", "provider", "container", "factory"],
    "ui": ["ui", "view", "component", "widget", "screen", "layout", "fragment"],
    "perf": ["perf", "performance", "optimize", "optimization", "latency", "throughput", "profile"],
    "debt": ["debt", "technical debt", "tech debt", "legacy", "refactor", "cleanup", "deprecated"],
    "complexity": ["complexity", "cyclomatic", "cognitive", "nesting", "coupling"],
    "pattern": ["pattern", "singleton", "factory", "repository", "observer", "strategy"],
}


def expand_query(query: str) -> str:
    """Expand query by appending relevant synonyms."""
    query_lower = query.lower()
    extra_terms: list[str] = []

    for key, synonyms in QUERY_EXPANSIONS.items():
        if key in query_lower:
            for syn in synonyms:
                if syn not in query_lower:
                    extra_terms.append(syn)

    if extra_terms:
        return f"{query} {' '.join(extra_terms[:10])}"
    return query


def decompose_query(query: str, max_subqueries: int = 3) -> list[str]:
    """Split a compound query into sub-queries on conjunctions."""
    parts = re.split(r"\b(?:and|or|plus|with|also)\b", query, flags=re.IGNORECASE)
    parts = [p.strip() for p in parts if p.strip()]
    return parts[:max_subqueries] if len(parts) > 1 else [query]
