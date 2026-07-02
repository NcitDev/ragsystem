"""Embedding cache backed by SQLite with binary vector storage.

Caches dense and sparse embeddings keyed by content hash (SHA256[:16])
so unchanged chunks skip re-embedding. Uses struct.pack for 10x smaller
+ faster storage compared to JSON.

Entries expire after a configurable TTL (default 30 days).
"""

from __future__ import annotations

import sqlite3
import struct
import threading
import time

import structlog

from rag.config import RAG_HOME
from rag.core.embedder import EmbeddingResult

logger = structlog.get_logger()

_DB_PATH = RAG_HOME / "embed_cache.db"
_DEFAULT_TTL_DAYS = 30

_local = threading.local()


def _pack_floats(values: list[float]) -> bytes:
    """Pack list of floats into compact binary (4 bytes per float)."""
    return struct.pack(f"{len(values)}f", *values)


def _unpack_floats(data: bytes) -> list[float]:
    """Unpack binary back to list of floats."""
    count = len(data) // 4
    return list(struct.unpack(f"{count}f", data))


def _pack_ints(values: list[int]) -> bytes:
    """Pack list of ints into compact binary (4 bytes per int)."""
    return struct.pack(f"{len(values)}i", *values)


def _unpack_ints(data: bytes) -> list[int]:
    """Unpack binary back to list of ints."""
    count = len(data) // 4
    return list(struct.unpack(f"{count}i", data))


def _get_conn() -> sqlite3.Connection:
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
            dense       BLOB NOT NULL,
            sparse_idx  BLOB,
            sparse_val  BLOB,
            created_at  REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS cache_stats (
            id          INTEGER PRIMARY KEY CHECK (id = 1),
            hit_count   INTEGER NOT NULL DEFAULT 0,
            miss_count  INTEGER NOT NULL DEFAULT 0
        );

        INSERT OR IGNORE INTO cache_stats (id, hit_count, miss_count) VALUES (1, 0, 0);
    """)
    # Migrate from old JSON-text schema to BLOB if needed
    try:
        info = conn.execute("PRAGMA table_info(embed_cache)").fetchall()
        type_map = {row[1]: row[2] for row in info}
        if type_map.get("dense") == "TEXT":
            logger.info("cache_migrating", reason="JSON to binary format")
            conn.execute("DROP TABLE embed_cache")
            conn.execute("""
                CREATE TABLE embed_cache (
                    content_hash TEXT PRIMARY KEY,
                    dense       BLOB NOT NULL,
                    sparse_idx  BLOB,
                    sparse_val  BLOB,
                    created_at  REAL NOT NULL
                )
            """)
            conn.commit()
    except sqlite3.Error:
        pass


class EmbeddingCache:
    """Thread-safe, TTL-based embedding cache with binary storage.

    Keys are namespaced by embedding model: a cached vector produced by one
    model must never be served for another (mixing models yields garbage
    cosine similarity). When no model is given, the current configured
    embedding model is used.
    """

    def __init__(self, ttl_days: int = _DEFAULT_TTL_DAYS, model: str | None = None) -> None:
        # A non-positive TTL would treat every entry as expired -> 100% miss
        # rate (every chunk re-embedded every run). Guard against misconfig.
        if ttl_days <= 0:
            logger.warning("cache_ttl_invalid", ttl_days=ttl_days, fallback=_DEFAULT_TTL_DAYS)
            ttl_days = _DEFAULT_TTL_DAYS
        self._ttl_seconds = ttl_days * 86400
        if model is None:
            from rag.config import get_settings

            model = get_settings().embeddings.model
        self._model = model

    def _key(self, content_hash: str) -> str:
        return f"{self._model}:{content_hash}"

    def get(self, content_hash: str) -> EmbeddingResult | None:
        """Look up a cached embedding. Returns None on miss or expiry."""
        try:
            conn = _get_conn()
            row = conn.execute(
                "SELECT dense, sparse_idx, sparse_val, created_at "
                "FROM embed_cache WHERE content_hash = ?",
                (self._key(content_hash),),
            ).fetchone()

            if row is None:
                self._bump(conn, "miss_count")
                return None

            dense_blob, sparse_idx_blob, sparse_val_blob, created_at = row

            if time.time() - created_at > self._ttl_seconds:
                conn.execute("DELETE FROM embed_cache WHERE content_hash = ?", (self._key(content_hash),))
                conn.commit()
                self._bump(conn, "miss_count")
                return None

            self._bump(conn, "hit_count")
            return EmbeddingResult(
                dense=_unpack_floats(dense_blob),
                sparse_indices=_unpack_ints(sparse_idx_blob) if sparse_idx_blob else None,
                sparse_values=_unpack_floats(sparse_val_blob) if sparse_val_blob else None,
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
                    self._key(content_hash),
                    _pack_floats(result.dense),
                    _pack_ints(result.sparse_indices) if result.sparse_indices else None,
                    _pack_floats(result.sparse_values) if result.sparse_values else None,
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
        try:
            conn = _get_conn()
            row = conn.execute("SELECT hit_count, miss_count FROM cache_stats WHERE id = 1").fetchone()
            total = conn.execute("SELECT COUNT(*) FROM embed_cache").fetchone()
            return {
                "hit_count": row[0] if row else 0,
                "miss_count": row[1] if row else 0,
                "total_entries": total[0] if total else 0,
            }
        except sqlite3.Error:
            return {"hit_count": 0, "miss_count": 0, "total_entries": 0}

    @staticmethod
    def _bump(conn: sqlite3.Connection, column: str) -> None:
        try:
            conn.execute(f"UPDATE cache_stats SET {column} = {column} + 1 WHERE id = 1")
            conn.commit()
        except sqlite3.Error:
            pass
