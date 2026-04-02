"""SQLite storage for query logs, index state, and config cache.

Uses a single connection with WAL mode for concurrent read/write.
"""

from __future__ import annotations

import sqlite3
import threading
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

        CREATE INDEX IF NOT EXISTS idx_query_log_ts ON query_log(timestamp);
        CREATE INDEX IF NOT EXISTS idx_index_runs_ts ON index_runs(timestamp);
    """)


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
