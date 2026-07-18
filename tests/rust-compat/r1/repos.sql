CREATE TABLE repos (
    name TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    collection TEXT NOT NULL,
    last_indexed TEXT,
    chunks_count INTEGER DEFAULT 0
);

INSERT INTO repos (name, path, collection, last_indexed, chunks_count)
VALUES (
    'fixture',
    '/tmp/python-created-fixture',
    'repo_fixture',
    '2025-06-10T12:00:00+00:00',
    2
);
