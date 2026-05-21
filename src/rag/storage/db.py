"""SQLite storage for query logs, index state, and config cache.

Uses a single connection with WAL mode for concurrent read/write.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

from rag.config import RAG_HOME

DB_PATH = RAG_HOME / "rag.db"

_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    """Get a thread-local connection (reused within same thread)."""
    if not hasattr(_local, "conn") or _local.conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(str(DB_PATH), timeout=10)
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA busy_timeout=5000")
    return _local.conn


def close_connection() -> None:
    """Close the thread-local connection."""
    if hasattr(_local, "conn") and _local.conn is not None:
        _local.conn.close()
        _local.conn = None


def init_db() -> None:
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS query_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            query TEXT NOT NULL,
            results_count INTEGER,
            latency_ms REAL,
            filters TEXT
        );

        CREATE TABLE IF NOT EXISTS index_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            repo_path TEXT NOT NULL,
            files_processed INTEGER,
            chunks_indexed INTEGER,
            files_skipped INTEGER,
            errors_count INTEGER,
            duration_ms REAL
        );

        CREATE TABLE IF NOT EXISTS overview_stats (
            language TEXT NOT NULL,
            pattern TEXT NOT NULL,
            complexity_bucket TEXT NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (language, pattern, complexity_bucket)
        );

        CREATE TABLE IF NOT EXISTS rate_buckets (
            token TEXT PRIMARY KEY,
            tokens_remaining INTEGER NOT NULL,
            refill_at REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_query_log_ts ON query_log(timestamp);
        CREATE INDEX IF NOT EXISTS idx_index_runs_ts ON index_runs(timestamp);
    """)
    conn.commit()


def _ensure_table(table_sql: str) -> None:
    """Create a table on demand. Cheap and idempotent."""
    conn = _get_conn()
    conn.execute(table_sql)
    conn.commit()


def log_query(query: str, results_count: int, latency_ms: float) -> None:
    try:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO query_log (timestamp, query, results_count, latency_ms) VALUES (?, ?, ?, ?)",
            (datetime.now().isoformat(), query, results_count, latency_ms),
        )
        conn.commit()
    except sqlite3.Error:
        pass  # Non-critical — don't crash on log failure


def log_index_run(
    repo_path: str, files_processed: int, chunks_indexed: int,
    files_skipped: int, errors_count: int, duration_ms: float,
) -> None:
    try:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO index_runs (timestamp, repo_path, files_processed, chunks_indexed, files_skipped, errors_count, duration_ms) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (datetime.now().isoformat(), repo_path, files_processed, chunks_indexed, files_skipped, errors_count, duration_ms),
        )
        conn.commit()
    except sqlite3.Error:
        pass


def recent_queries(limit: int = 20) -> list[dict]:
    try:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT timestamp, query, results_count, latency_ms FROM query_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {"timestamp": r[0], "query": r[1], "results_count": r[2], "latency_ms": r[3]}
            for r in rows
        ]
    except sqlite3.Error:
        return []


# ---------------------------------------------------------------------------
# Overview stats — materialized counters keyed by (language, pattern, bucket)
# ---------------------------------------------------------------------------


_OVERVIEW_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS overview_stats ("
    "language TEXT NOT NULL,"
    "pattern TEXT NOT NULL,"
    "complexity_bucket TEXT NOT NULL,"
    "count INTEGER NOT NULL DEFAULT 0,"
    "PRIMARY KEY (language, pattern, complexity_bucket))"
)


def _complexity_bucket(complexity: int | float | None) -> str:
    """Bucket cyclomatic complexity into low/medium/high/unknown."""
    if complexity is None:
        return "unknown"
    try:
        c = int(complexity)
    except (TypeError, ValueError):
        return "unknown"
    if c <= 0:
        return "unknown"
    if c <= 5:
        return "low"
    if c <= 10:
        return "medium"
    return "high"


def incr_overview(language: str, patterns: list[str], complexity: int | float | None) -> None:
    """Increment counters for a single chunk's metadata.

    Writes one canonical row per chunk under pattern ``"_total"`` so the
    language/bucket counters stay accurate, plus one row per pattern so
    pattern frequency is countable too.
    """
    try:
        _ensure_table(_OVERVIEW_TABLE_SQL)
        conn = _get_conn()
        bucket = _complexity_bucket(complexity)
        lang = language or "unknown"
        # Canonical per-chunk row.
        rows = [(lang, "_total", bucket)]
        # Plus one row per pattern for pattern frequency.
        for pat in patterns or ():
            rows.append((lang, pat, bucket))
        for r in rows:
            conn.execute(
                "INSERT INTO overview_stats (language, pattern, complexity_bucket, count) "
                "VALUES (?, ?, ?, 1) "
                "ON CONFLICT(language, pattern, complexity_bucket) DO UPDATE SET count = count + 1",
                r,
            )
        conn.commit()
    except sqlite3.Error:
        pass  # Non-critical — overview will fall back to scroll-based aggregation.


def get_overview() -> dict:
    """Return aggregated overview stats from the materialized table.

    Shape matches the /overview route:
        {languages: {lang: count}, patterns: {pat: count},
         complexity: {average, max, high_count}, total_chunks: int}
    Returns counters at zero if the table is empty.
    """
    try:
        _ensure_table(_OVERVIEW_TABLE_SQL)
        conn = _get_conn()
        rows = conn.execute(
            "SELECT language, pattern, complexity_bucket, count FROM overview_stats"
        ).fetchall()
    except sqlite3.Error:
        return {"languages": {}, "patterns": {}, "complexity": {"average": 0, "max": 0, "high_count": 0}, "total_chunks": 0}

    languages: dict[str, int] = {}
    patterns: dict[str, int] = {}
    bucket_counts: dict[str, int] = {"low": 0, "medium": 0, "high": 0, "unknown": 0}
    total_chunks = 0

    for lang, pat, bucket, count in rows:
        if pat == "_total":
            languages[lang] = languages.get(lang, 0) + count
            bucket_counts[bucket] = bucket_counts.get(bucket, 0) + count
            total_chunks += count
        else:
            patterns[pat] = patterns.get(pat, 0) + count

    high_count = bucket_counts.get("high", 0)
    # Average complexity — coarse estimate from bucket midpoints (low=3,
    # medium=8, high=15). Unknown bucket is excluded from the denominator.
    weights = {"low": 3, "medium": 8, "high": 15}
    weighted = sum(bucket_counts.get(b, 0) * w for b, w in weights.items())
    denom = sum(bucket_counts.get(b, 0) for b in weights) or 0
    avg = round(weighted / denom, 1) if denom else 0
    # ``max`` is unknowable from buckets alone; report the upper bound of
    # the highest non-empty bucket so the field stays meaningful.
    if bucket_counts.get("high", 0) > 0:
        max_complexity = 15
    elif bucket_counts.get("medium", 0) > 0:
        max_complexity = 10
    elif bucket_counts.get("low", 0) > 0:
        max_complexity = 5
    else:
        max_complexity = 0

    return {
        "languages": dict(sorted(languages.items(), key=lambda x: -x[1])),
        "patterns": dict(sorted(patterns.items(), key=lambda x: -x[1])),
        "complexity": {"average": avg, "max": max_complexity, "high_count": high_count},
        "total_chunks": total_chunks,
    }


def reset_overview() -> None:
    """Clear materialized overview counters (for full re-index)."""
    try:
        _ensure_table(_OVERVIEW_TABLE_SQL)
        conn = _get_conn()
        conn.execute("DELETE FROM overview_stats")
        conn.commit()
    except sqlite3.Error:
        pass


# ---------------------------------------------------------------------------
# Per-token rate buckets
# ---------------------------------------------------------------------------


_RATE_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS rate_buckets ("
    "token TEXT PRIMARY KEY,"
    "tokens_remaining INTEGER NOT NULL,"
    "refill_at REAL NOT NULL)"
)


def check_rate_bucket(token: str, capacity: int = 120, refill_per_sec: float = 2.0) -> bool:
    """Token-bucket rate limit per client.

    Returns True if the request is allowed (and consumes one token);
    False if the bucket is empty. Default settings allow ~120 burst with
    a steady-state of ~120 req/min (2 per second), matching the previous
    deque-based limit.
    """
    try:
        _ensure_table(_RATE_TABLE_SQL)
        conn = _get_conn()
        now = time.time()
        row = conn.execute(
            "SELECT tokens_remaining, refill_at FROM rate_buckets WHERE token = ?",
            (token,),
        ).fetchone()
        if row is None:
            # Fresh bucket — allow and store with one token consumed.
            conn.execute(
                "INSERT INTO rate_buckets (token, tokens_remaining, refill_at) VALUES (?, ?, ?)",
                (token, capacity - 1, now),
            )
            conn.commit()
            return True

        remaining, refill_at = row
        elapsed = max(0.0, now - refill_at)
        refilled = remaining + int(elapsed * refill_per_sec)
        if refilled > capacity:
            refilled = capacity
        if refilled <= 0:
            # Still empty — update timestamp so refill keeps accruing.
            conn.execute(
                "UPDATE rate_buckets SET tokens_remaining = ?, refill_at = ? WHERE token = ?",
                (0, now, token),
            )
            conn.commit()
            return False
        conn.execute(
            "UPDATE rate_buckets SET tokens_remaining = ?, refill_at = ? WHERE token = ?",
            (refilled - 1, now, token),
        )
        conn.commit()
        return True
    except sqlite3.Error:
        # Fail open on storage trouble.
        return True
