"""SQLite storage for query logs, index state, and config cache."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from rag.config import RAG_HOME


DB_PATH = RAG_HOME / "rag.db"


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Create tables if they don't exist."""
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
    """)
    conn.close()


def log_query(query: str, results_count: int, latency_ms: float) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT INTO query_log (timestamp, query, results_count, latency_ms) VALUES (?, ?, ?, ?)",
        (datetime.now().isoformat(), query, results_count, latency_ms),
    )
    conn.commit()
    conn.close()


def log_index_run(
    repo_path: str, files_processed: int, chunks_indexed: int,
    files_skipped: int, errors_count: int, duration_ms: float,
) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT INTO index_runs (timestamp, repo_path, files_processed, chunks_indexed, files_skipped, errors_count, duration_ms) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (datetime.now().isoformat(), repo_path, files_processed, chunks_indexed, files_skipped, errors_count, duration_ms),
    )
    conn.commit()
    conn.close()


def recent_queries(limit: int = 20) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT timestamp, query, results_count, latency_ms FROM query_log ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [
        {"timestamp": r[0], "query": r[1], "results_count": r[2], "latency_ms": r[3]}
        for r in rows
    ]
