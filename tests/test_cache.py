"""Tests for the SQLite-backed embedding cache."""

from __future__ import annotations

import pytest

import rag.core.cache as cache_mod
from rag.core.cache import EmbeddingCache
from rag.core.embedder import EmbeddingResult


@pytest.fixture
def fresh_cache(tmp_path, monkeypatch):
    """Point the cache DB at a tmp file and reset the thread-local conn."""
    db = tmp_path / "embed_cache.db"
    monkeypatch.setattr(cache_mod, "_DB_PATH", db, raising=True)
    # Drop any thread-local conn so the patched path takes effect.
    if hasattr(cache_mod._local, "conn") and cache_mod._local.conn is not None:
        try:
            cache_mod._local.conn.close()
        except Exception:
            pass
        cache_mod._local.conn = None
    yield EmbeddingCache()
    if hasattr(cache_mod._local, "conn") and cache_mod._local.conn is not None:
        cache_mod._local.conn.close()
        cache_mod._local.conn = None


def test_put_get_roundtrip(fresh_cache):
    vec = [0.1, -0.2, 0.3, 0.4]
    fresh_cache.put("hash1", EmbeddingResult(dense=vec))
    got = fresh_cache.get("hash1")
    assert got is not None
    # Binary struct.pack is float32 — compare with tolerance.
    assert got.dense == pytest.approx(vec, abs=1e-6)
    # Sparse fields are always None after the BM25 nuke.
    assert got.sparse_indices is None
    assert got.sparse_values is None


def test_miss_returns_none(fresh_cache):
    assert fresh_cache.get("never_stored") is None


def test_hit_miss_stats(fresh_cache):
    fresh_cache.put("h", EmbeddingResult(dense=[1.0]))
    fresh_cache.get("h")          # hit
    fresh_cache.get("nope")       # miss
    fresh_cache.get("nope2")      # miss
    stats = fresh_cache.stats()
    assert stats["hit_count"] == 1
    assert stats["miss_count"] == 2
    assert stats["total_entries"] == 1


def test_ttl_expiry_evicts(fresh_cache, monkeypatch):
    """An entry older than the TTL is treated as a miss and deleted."""
    base = 1_000_000.0
    monkeypatch.setattr(cache_mod.time, "time", lambda: base)
    fresh_cache.put("old", EmbeddingResult(dense=[1.0, 2.0]))
    assert fresh_cache.get("old") is not None  # fresh

    # Jump well past the 30-day TTL.
    monkeypatch.setattr(cache_mod.time, "time", lambda: base + 31 * 86400)
    assert fresh_cache.get("old") is None
    # And it was evicted, not just hidden.
    assert fresh_cache.stats()["total_entries"] == 0


def test_clear_drops_entries_and_stats(fresh_cache):
    fresh_cache.put("a", EmbeddingResult(dense=[1.0]))
    fresh_cache.get("a")
    fresh_cache.clear()
    stats = fresh_cache.stats()
    assert stats == {"hit_count": 0, "miss_count": 0, "total_entries": 0}
    assert fresh_cache.get("a") is None


def test_replace_does_not_grow(fresh_cache):
    """INSERT OR REPLACE on the same hash keeps a single row (no unbounded growth)."""
    for i in range(50):
        fresh_cache.put("same", EmbeddingResult(dense=[float(i)]))
    assert fresh_cache.stats()["total_entries"] == 1
    assert fresh_cache.get("same").dense == pytest.approx([49.0], abs=1e-6)


def test_nonpositive_ttl_falls_back():
    """A misconfigured TTL <= 0 must not turn the cache into 100% misses."""
    c = EmbeddingCache(ttl_days=0)
    assert c._ttl_seconds == cache_mod._DEFAULT_TTL_DAYS * 86400
    c2 = EmbeddingCache(ttl_days=-5)
    assert c2._ttl_seconds == cache_mod._DEFAULT_TTL_DAYS * 86400
