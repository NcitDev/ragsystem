"""Embedding cache backed by SQLite.

Caches dense and sparse embeddings keyed by content hash (SHA256[:16])
so unchanged chunks skip re-embedding.  Entries expire after a
configurable TTL (default 30 days).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

import structlog

from rag.config import RAG_HOME
from rag.core.embedder import EmbeddingResult

logger = structlog.get_logger()

_DB_PATH = RAG_HOME / "embed_cache.db"
_DEFAULT_TTL_DAYS = 30

_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    """Return a thread-local SQLite connection, creating it on first call."""
    if not hasattr(_local, "conn") or _local.conn is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(str(_DB_PATH), timeout=10)
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA busy_timeout=5000")
        _init_table(_local.conn)
    return _local.conn


def _init_table(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS embed_cache (
            content_hash TEXT PRIMARY KEY,
            dense       TEXT NOT NULL,
            sparse_idx  TEXT,
            sparse_val  TEXT,
            created_at  REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS cache_stats (
            id          INTEGER PRIMARY KEY CHECK (id = 1),
            hit_count   INTEGER NOT NULL DEFAULT 0,
            miss_count  INTEGER NOT NULL DEFAULT 0
        );

        INSERT OR IGNORE INTO cache_stats (id, hit_count, miss_count) VALUES (1, 0, 0);
    """)


class EmbeddingCache:
    """Thread-safe, TTL-based embedding cache persisted in SQLite."""

    def __init__(self, ttl_days: int = _DEFAULT_TTL_DAYS) -> None:
        self._ttl_seconds = ttl_days * 86400

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, content_hash: str) -> EmbeddingResult | None:
        """Look up a cached embedding.  Returns *None* on miss or expiry."""
        try:
            conn = _get_conn()
            row = conn.execute(
                "SELECT dense, sparse_idx, sparse_val, created_at "
                "FROM embed_cache WHERE content_hash = ?",
                (content_hash,),
            ).fetchone()

            if row is None:
                self._bump(conn, "miss_count")
                return None

            dense_json, sparse_idx_json, sparse_val_json, created_at = row

            if time.time() - created_at > self._ttl_seconds:
                conn.execute(
                    "DELETE FROM embed_cache WHERE content_hash = ?",
                    (content_hash,),
                )
                conn.commit()
                self._bump(conn, "miss_count")
                logger.debug("cache_expired", content_hash=content_hash)
                return None

            self._bump(conn, "hit_count")
            return EmbeddingResult(
                dense=json.loads(dense_json),
                sparse_indices=json.loads(sparse_idx_json) if sparse_idx_json else None,
                sparse_values=json.loads(sparse_val_json) if sparse_val_json else None,
            )
        except sqlite3.Error:
            logger.warning("cache_get_error", content_hash=content_hash, exc_info=True)
            return None

    def put(self, content_hash: str, result: EmbeddingResult) -> None:
        """Insert or replace a cached embedding."""
        try:
            conn = _get_conn()
            conn.execute(
                "INSERT OR REPLACE INTO embed_cache "
                "(content_hash, dense, sparse_idx, sparse_val, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    content_hash,
                    json.dumps(result.dense),
                    json.dumps(result.sparse_indices) if result.sparse_indices is not None else None,
                    json.dumps(result.sparse_values) if result.sparse_values is not None else None,
                    time.time(),
                ),
            )
            conn.commit()
        except sqlite3.Error:
            logger.warning("cache_put_error", content_hash=content_hash, exc_info=True)

    def clear(self) -> None:
        """Drop all cached embeddings and reset stats."""
        try:
            conn = _get_conn()
            conn.executescript("""
                DELETE FROM embed_cache;
                UPDATE cache_stats SET hit_count = 0, miss_count = 0 WHERE id = 1;
            """)
        except sqlite3.Error:
            logger.warning("cache_clear_error", exc_info=True)

    def stats(self) -> dict:
        """Return cache statistics."""
        try:
            conn = _get_conn()
            row = conn.execute(
                "SELECT hit_count, miss_count FROM cache_stats WHERE id = 1",
            ).fetchone()
            total = conn.execute(
                "SELECT COUNT(*) FROM embed_cache",
            ).fetchone()
            return {
                "hit_count": row[0] if row else 0,
                "miss_count": row[1] if row else 0,
                "total_entries": total[0] if total else 0,
            }
        except sqlite3.Error:
            return {"hit_count": 0, "miss_count": 0, "total_entries": 0}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _bump(conn: sqlite3.Connection, column: str) -> None:
        try:
            conn.execute(
                f"UPDATE cache_stats SET {column} = {column} + 1 WHERE id = 1",  # noqa: S608
            )
            conn.commit()
        except sqlite3.Error:
            pass
