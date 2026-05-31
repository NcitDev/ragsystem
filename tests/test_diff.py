from __future__ import annotations

import subprocess
from pathlib import Path

from rag.core.diff import search_in_diff
from rag.config import get_settings


class _AsyncVectorStore:
    def __init__(self):
        self.calls = []

    async def search(self, collection, query, top_k, filters=None):
        self.calls.append(
            {
                "collection": collection,
                "query": query,
                "top_k": top_k,
                "filters": filters,
            }
        )
        return [{"file_path": filters["file_path"][0], "query": query}]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


async def test_search_in_diff_uses_qdrant_filter(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test User")

    (repo / "a.py").write_text("print('one')\n")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-m", "initial")

    (repo / "a.py").write_text("print('two')\n")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-m", "change")

    store = _AsyncVectorStore()
    results = await search_in_diff(str(repo), "HEAD~1", "print", store, top_k=5)

    assert results == [{"file_path": "a.py", "query": "print"}]
    assert store.calls == [
        {
            "collection": get_settings().qdrant.code_collection,
            "query": "print",
            "top_k": 5,
            "filters": {"file_path": ["a.py"]},
        }
    ]
