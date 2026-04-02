"""Multi-repo support with separate Qdrant collections per repository."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from rag.config import RAG_HOME


@dataclass
class RepoInfo:
    name: str
    path: str
    collection: str
    last_indexed: str | None = None
    chunks_count: int = 0


class RepoManager:
    """SQLite-backed registry for managing multiple indexed repositories."""

    def __init__(self, db_path: Path = RAG_HOME / "repos.db") -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS repos (
                    name TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    collection TEXT NOT NULL,
                    last_indexed TEXT,
                    chunks_count INTEGER DEFAULT 0
                )
                """
            )

    def register(self, name: str, path: str) -> RepoInfo:
        """Register a repo. Collection name = f"repo_{name}"."""
        collection = f"repo_{name}"
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO repos (name, path, collection, last_indexed, chunks_count)
                VALUES (?, ?, ?, NULL, 0)
                ON CONFLICT(name) DO UPDATE SET path = excluded.path, collection = excluded.collection
                """,
                (name, path, collection),
            )
        return RepoInfo(name=name, path=path, collection=collection)

    def unregister(self, name: str) -> None:
        """Remove a repo from registry."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM repos WHERE name = ?", (name,))

    def list_repos(self) -> list[RepoInfo]:
        """List all registered repos."""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM repos ORDER BY name").fetchall()
        return [
            RepoInfo(
                name=row["name"],
                path=row["path"],
                collection=row["collection"],
                last_indexed=row["last_indexed"],
                chunks_count=row["chunks_count"],
            )
            for row in rows
        ]

    def get(self, name: str) -> RepoInfo | None:
        """Get repo by name."""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM repos WHERE name = ?", (name,)).fetchone()
        if row is None:
            return None
        return RepoInfo(
            name=row["name"],
            path=row["path"],
            collection=row["collection"],
            last_indexed=row["last_indexed"],
            chunks_count=row["chunks_count"],
        )

    def update_stats(self, name: str, chunks_count: int) -> None:
        """Update after indexing."""
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "UPDATE repos SET chunks_count = ?, last_indexed = ? WHERE name = ?",
                (chunks_count, now, name),
            )
