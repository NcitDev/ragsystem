CREATE TABLE query_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    query TEXT NOT NULL,
    results_count INTEGER NOT NULL,
    latency_ms REAL NOT NULL
);

CREATE TABLE code_index (
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

CREATE VIRTUAL TABLE code_index_fts USING fts5(
    chunk_id UNINDEXED,
    collection UNINDEXED,
    file_path,
    name,
    parent_name,
    chunk_type,
    language,
    code
);

INSERT INTO query_log (timestamp, query, results_count, latency_ms)
VALUES ('2025-06-10T12:00:00.000', 'require_auth token', 1, 2.5);

INSERT INTO code_index (
    chunk_id, collection, file_path, name, parent_name, chunk_type,
    language, start_line, end_line, code, token_estimate, updated_at
) VALUES
    (
        'fixture-require-auth', 'repo_fixture', 'src/rag/server.py',
        'require_auth', '', 'function', 'python', 10, 13,
        'def require_auth(token):\n    return bool(token)', 12, 1749556800.0
    ),
    (
        'fixture-health', 'repo_fixture', 'src/rag/z_health.py',
        'health', '', 'function', 'python', 1, 2,
        'def health():\n    return {"status": "ok"}', 11, 1749556800.0
    );

INSERT INTO code_index_fts (
    chunk_id, collection, file_path, name, parent_name, chunk_type, language, code
)
SELECT chunk_id, collection, file_path, name, parent_name, chunk_type, language, code
FROM code_index;
