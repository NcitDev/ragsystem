"""SQLite storage for query logs, index state, and config cache.

Uses a single connection with WAL mode for concurrent read/write.
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
from collections.abc import Sequence
from datetime import datetime
from typing import Any

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
    ensure_code_index()


def _ensure_table(table_sql: str) -> None:
    """Create a table on demand. Cheap and idempotent."""
    conn = _get_conn()
    conn.execute(table_sql)
    conn.commit()


# ---------------------------------------------------------------------------
# Code chunk lexical index
# ---------------------------------------------------------------------------


_CODE_INDEX_SQL = """
    CREATE TABLE IF NOT EXISTS code_index (
        chunk_id TEXT PRIMARY KEY,
        collection TEXT NOT NULL,
        file_path TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        parent_name TEXT NOT NULL DEFAULT '',
        chunk_type TEXT NOT NULL DEFAULT '',
        language TEXT NOT NULL DEFAULT '',
        start_line INTEGER NOT NULL DEFAULT 0,
        end_line INTEGER NOT NULL DEFAULT 0,
        code TEXT NOT NULL,
        token_estimate INTEGER NOT NULL DEFAULT 0,
        updated_at REAL NOT NULL
    );
"""

_CODE_FTS_SQL = """
    CREATE VIRTUAL TABLE IF NOT EXISTS code_index_fts USING fts5(
        chunk_id UNINDEXED,
        collection UNINDEXED,
        file_path,
        name,
        parent_name,
        chunk_type,
        language,
        code,
        tokenize = 'unicode61 tokenchars ''_$'''
    );
"""

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_QUOTED_RE = re.compile(r"['\"]([^'\"]{3,120})['\"]")
_MIN_QUERY_TOKEN = 3


def _token_estimate(text: str) -> int:
    return max(1, (len(text or "") + 3) // 4)


def ensure_code_index() -> None:
    """Create the local exact/lexical code index used for high-precision recall."""
    conn = _get_conn()
    conn.execute(_CODE_INDEX_SQL)
    conn.execute(_CODE_FTS_SQL)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_code_collection_file ON code_index(collection, file_path)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_code_symbol ON code_index(collection, name, parent_name)")
    conn.commit()


def _metadata_value(meta: dict[str, Any], key: str, default: Any = "") -> Any:
    value = meta.get(key, default)
    return default if value is None else value


def upsert_code_chunks(collection: str, docs: Sequence[Any]) -> int:
    """Mirror indexed chunks into SQLite for exact symbol and context-pack lookup.

    ``docs`` are intentionally duck-typed so this storage layer does not import
    the vectorstore dataclass and risk an import cycle.
    """
    if not docs:
        return 0
    ensure_code_index()
    now = time.time()
    rows = []
    fts_rows = []
    chunk_ids = []
    for doc in docs:
        meta = getattr(doc, "metadata", {}) or {}
        content = getattr(doc, "content", "") or ""
        chunk_id = getattr(doc, "chunk_id", None) or meta.get("content_hash") or ""
        if not chunk_id:
            continue
        row = (
            str(chunk_id),
            collection,
            str(_metadata_value(meta, "file_path")),
            str(_metadata_value(meta, "name")),
            str(_metadata_value(meta, "parent_name")),
            str(_metadata_value(meta, "chunk_type")),
            str(_metadata_value(meta, "language")),
            int(_metadata_value(meta, "start_line", 0) or 0),
            int(_metadata_value(meta, "end_line", 0) or 0),
            content,
            _token_estimate(content),
            now,
        )
        rows.append(row)
        fts_rows.append((
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
            row[5],
            row[6],
            row[9],
        ))
        chunk_ids.append(row[0])

    if not rows:
        return 0
    conn = _get_conn()
    try:
        conn.executemany("DELETE FROM code_index WHERE chunk_id = ?", [(cid,) for cid in chunk_ids])
        conn.executemany("DELETE FROM code_index_fts WHERE chunk_id = ?", [(cid,) for cid in chunk_ids])
        conn.executemany(
            """
            INSERT INTO code_index (
                chunk_id, collection, file_path, name, parent_name, chunk_type,
                language, start_line, end_line, code, token_estimate, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.executemany(
            """
            INSERT INTO code_index_fts (
                chunk_id, collection, file_path, name, parent_name,
                chunk_type, language, code
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            fts_rows,
        )
        conn.commit()
        return len(rows)
    except sqlite3.Error:
        conn.rollback()
        raise


def delete_code_chunks_by_file(collection: str, file_path: str) -> None:
    ensure_code_index()
    conn = _get_conn()
    ids = conn.execute(
        "SELECT chunk_id FROM code_index WHERE collection = ? AND file_path = ?",
        (collection, file_path),
    ).fetchall()
    if not ids:
        return
    conn.executemany("DELETE FROM code_index_fts WHERE chunk_id = ?", ids)
    conn.execute(
        "DELETE FROM code_index WHERE collection = ? AND file_path = ?",
        (collection, file_path),
    )
    conn.commit()


def delete_code_chunks_by_collection(collection: str) -> None:
    ensure_code_index()
    conn = _get_conn()
    conn.execute("DELETE FROM code_index_fts WHERE collection = ?", (collection,))
    conn.execute("DELETE FROM code_index WHERE collection = ?", (collection,))
    conn.commit()


def _query_terms(query: str) -> list[str]:
    terms: list[str] = []
    for quoted in _QUOTED_RE.findall(query or ""):
        terms.extend(_IDENT_RE.findall(quoted))
    terms.extend(_IDENT_RE.findall(query or ""))
    seen: set[str] = set()
    out: list[str] = []
    for term in terms:
        if len(term) < _MIN_QUERY_TOKEN:
            continue
        key = term.lower()
        if key not in seen:
            seen.add(key)
            out.append(term)
    return out[:12]


def _fts_query(terms: list[str]) -> str:
    quoted = []
    for term in terms:
        safe = term.replace('"', '""')
        quoted.append(f'"{safe}"')
    return " OR ".join(quoted)


def _filter_clause(filters: dict[str, Any] | None, params: list[Any]) -> str:
    if not filters:
        return ""
    clauses: list[str] = []
    allowed = {"file_path", "name", "parent_name", "chunk_type", "language"}
    for key, value in filters.items():
        if key not in allowed:
            continue
        if isinstance(value, list):
            vals = [v for v in value if v is not None]
            if not vals:
                continue
            clauses.append(f"{key} IN ({','.join('?' for _ in vals)})")
            params.extend(vals)
        else:
            clauses.append(f"{key} = ?")
            params.append(value)
    return (" AND " + " AND ".join(clauses)) if clauses else ""


def _score_code_row(row: sqlite3.Row, terms: list[str]) -> float:
    text = f"{row['file_path']} {row['name']} {row['parent_name']} {row['code']}".lower()
    name = (row["name"] or "").lower()
    parent = (row["parent_name"] or "").lower()
    path = (row["file_path"] or "").lower()
    score = 1.0
    for term in terms:
        t = term.lower()
        if t == name:
            score += 4.0
        elif t == parent:
            score += 2.5
        elif t in path:
            score += 1.5
        occurrences = text.count(t)
        score += min(occurrences, 8) * 0.25
    if row["chunk_type"] in ("function", "method"):
        score += 0.6
    return score


def search_code_chunks(
    query: str,
    collection: str | None = None,
    limit: int = 20,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Search exact/lexical code chunks with symbol-aware scoring.

    This complements semantic vector search. It is deliberately optimized for
    developer navigation queries where symbols, file names, and API strings are
    the highest-signal evidence.
    """
    terms = _query_terms(query)
    if not terms:
        return []
    ensure_code_index()
    conn = _get_conn()
    conn.row_factory = sqlite3.Row

    candidates: dict[str, sqlite3.Row] = {}
    params: list[Any] = []
    collection_clause = ""
    if collection:
        collection_clause = " AND collection = ?"
        params.append(collection)
    filter_clause = _filter_clause(filters, params)

    try:
        match = _fts_query(terms)
        fts_rows = conn.execute(
            f"""
            SELECT chunk_id
            FROM code_index_fts
            WHERE code_index_fts MATCH ?{collection_clause}{filter_clause}
            LIMIT ?
            """,
            [match, *params, max(limit * 8, 50)],
        ).fetchall()
        ids = [r["chunk_id"] for r in fts_rows]
        if ids:
            rows = conn.execute(
                f"""
                SELECT * FROM code_index
                WHERE chunk_id IN ({','.join('?' for _ in ids)})
                """,
                ids,
            ).fetchall()
            candidates.update({r["chunk_id"]: r for r in rows})
    except sqlite3.Error:
        pass

    like_clauses: list[str] = []
    like_params: list[Any] = []
    for term in terms[:8]:
        pattern = f"%{term}%"
        like_clauses.append("(name LIKE ? OR parent_name LIKE ? OR file_path LIKE ? OR code LIKE ?)")
        like_params.extend([term, term, pattern, pattern])
    if like_clauses:
        params2: list[Any] = []
        collection_where = ""
        if collection:
            collection_where = "collection = ? AND "
            params2.append(collection)
        filter_clause2 = _filter_clause(filters, params2)
        rows = conn.execute(
            f"""
            SELECT * FROM code_index
            WHERE {collection_where}({" OR ".join(like_clauses)}){filter_clause2}
            LIMIT ?
            """,
            [*params2, *like_params, max(limit * 8, 50)],
        ).fetchall()
        candidates.update({r["chunk_id"]: r for r in rows})

    ranked = sorted(
        candidates.values(),
        key=lambda row: _score_code_row(row, terms),
        reverse=True,
    )[:limit]
    return [
        {
            "chunk_id": row["chunk_id"],
            "collection": row["collection"],
            "file_path": row["file_path"],
            "name": row["name"],
            "parent_name": row["parent_name"],
            "chunk_type": row["chunk_type"],
            "language": row["language"],
            "start_line": row["start_line"],
            "end_line": row["end_line"],
            "lines": f"{row['start_line']}-{row['end_line']}",
            "code": row["code"],
            "token_estimate": row["token_estimate"],
            "score": round(_score_code_row(row, terms), 4),
            "citation": (
                f"{row['file_path']}:{row['start_line']}-{row['end_line']} "
                f"({row['parent_name'] + '.' if row['parent_name'] else ''}{row['name']})"
            ),
        }
        for row in ranked
    ]


def list_code_files(
    collection: str | None = None,
    query: str = "",
    limit: int = 200,
    tests_only: bool = False,
) -> list[dict[str, Any]]:
    """List indexed source files from the exact SQLite mirror."""
    ensure_code_index()
    conn = _get_conn()
    conn.row_factory = sqlite3.Row

    params: list[Any] = []
    clauses: list[str] = []
    if collection:
        clauses.append("collection = ?")
        params.append(collection)
    if tests_only:
        clauses.append("(file_path LIKE ? OR file_path LIKE ? OR file_path LIKE ?)")
        params.extend(["%/test/%", "%/tests/%", "%Test.%"])

    terms = _query_terms(query)
    for term in terms[:6]:
        clauses.append("(file_path LIKE ? OR name LIKE ? OR parent_name LIKE ?)")
        pattern = f"%{term}%"
        params.extend([pattern, pattern, pattern])

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"""
        SELECT
            file_path,
            MAX(language) AS language,
            COUNT(*) AS chunk_count,
            COUNT(NULLIF(name, '')) AS symbol_count,
            MAX(updated_at) AS updated_at,
            GROUP_CONCAT(NULLIF(name, ''), ', ') AS symbols
        FROM code_index
        {where}
        GROUP BY file_path
        ORDER BY chunk_count DESC, file_path ASC
        LIMIT ?
        """,
        [*params, limit],
    ).fetchall()
    lowered_terms = [term.lower() for term in terms]
    out: list[dict[str, Any]] = []
    for row in rows:
        path = str(row["file_path"])
        symbols = [s for s in str(row["symbols"] or "").split(", ") if s][:20]
        score = 1.0
        for term in lowered_terms:
            if term in path.lower():
                score += 3.0
            if any(term in symbol.lower() for symbol in symbols):
                score += 2.0
        out.append(
            {
                "file_path": path,
                "language": row["language"] or "",
                "chunk_count": int(row["chunk_count"] or 0),
                "symbol_count": int(row["symbol_count"] or 0),
                "symbols": symbols,
                "updated_at": float(row["updated_at"] or 0.0),
                "score": round(score, 3),
            }
        )
    return out


def related_test_files(
    collection: str | None,
    file_paths: Sequence[str],
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Heuristically rank tests related to changed or impacted files."""
    test_files = list_code_files(collection=collection, limit=max(limit * 4, 100), tests_only=True)
    if not file_paths:
        return test_files[:limit]

    anchors: set[str] = set()
    modules: set[str] = set()
    for path in file_paths:
        parts = [p for p in path.split("/") if p]
        if parts:
            anchors.add(re.sub(r"(?i)(test|spec)$", "", parts[-1].split(".")[0]).lower())
        if len(parts) > 1:
            modules.add("/".join(parts[: max(1, min(len(parts) - 1, 3))]).lower())

    ranked: list[tuple[float, dict[str, Any]]] = []
    for item in test_files:
        path = item["file_path"].lower()
        base = item["file_path"].split("/")[-1].split(".")[0].lower()
        score = 0.0
        for anchor in anchors:
            if anchor and anchor in base:
                score += 5.0
            elif anchor and anchor in path:
                score += 2.0
        if any(path.startswith(module) for module in modules):
            score += 1.0
        if score > 0:
            ranked.append((score, {**item, "score": round(score, 3)}))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in ranked[:limit]]


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


def check_rate_bucket(token: str, capacity: int = 600, refill_per_sec: float = 20.0) -> bool:
    """Token-bucket rate limit per client.

    Returns True if the request is allowed (and consumes one token);
    False if the bucket is empty. Local single-user daemon — generous limit
    so the TUI's polling loops (events 1s, stats 5s, etc.) don't starve user
    actions. ~1200 req/min sustained, 600 burst.
    """
    try:
        _ensure_table(_RATE_TABLE_SQL)
        conn = _get_conn()
        now = time.time()
        # Acquire the write lock up front so the SELECT..UPDATE read-modify-write
        # is atomic. Without this, two concurrent requests for the same token
        # can both read the same ``remaining`` and each consume a token,
        # over-spending the bucket.
        conn.execute("BEGIN IMMEDIATE")
        try:
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
        except Exception:
            conn.rollback()
            raise
    except sqlite3.Error:
        # Fail open on storage trouble.
        return True
