"""Crash-consistency tests for the incremental indexer.

The indexer records a per-file content hash in ``state.json`` so the next run
can skip unchanged files. The invariant: a file's hash must be persisted ONLY
if its chunks were actually upserted to the vector store. Otherwise a crash
mid-flush would leave the file marked "indexed" while its chunks are missing,
and the next run would skip it — permanently losing those chunks.

These tests drive ``index_repository`` against an in-memory fake vector store,
inject a failure during one batch upsert, and assert the state file does not
record hashes for files whose chunks never landed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import rag.core.indexer as indexer_mod
from rag.core.indexer import index_repository, _state_file_for, _file_hash


# A class big enough to emit several chunks, repeated across many files so the
# run spans multiple 64-doc batches and the pipeline (await-prev / start-next)
# is actually exercised.
def _file_body(n: int) -> str:
    lines = [f'"""Module {n}."""', "", "", f"class C{n}:", f'    """Class {n}."""', ""]
    for m in range(8):
        lines.append(f"    def method_{m}(self, x):")
        lines.append(f'        """Method {m} of class {n}."""')
        lines.append(f"        return x + {m}")
        lines.append("")
    return "\n".join(lines)


@pytest.fixture
def big_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    # 30 files * ~9 chunks each comfortably crosses several batch_size=64 flushes.
    for i in range(30):
        (repo / f"mod_{i:02d}.py").write_text(_file_body(i))
    return repo


class _CapturingVectorStore:
    """Minimal async stand-in for QdrantVectorStore.

    Records every (file_path) that reaches a successful upsert. ``fail_on_call``
    makes the Nth upsert raise, simulating a crash mid-flush.
    """

    def __init__(self, fail_on_call: int | None = None):
        self.upsert_calls = 0
        self.fail_on_call = fail_on_call
        self.upserted_files: set[str] = set()
        self.deleted: list[tuple[str, str]] = []

    async def upsert(self, collection, docs, cache=None):
        self.upsert_calls += 1
        if self.fail_on_call is not None and self.upsert_calls == self.fail_on_call:
            raise RuntimeError("simulated Qdrant crash mid-flush")
        for d in docs:
            self.upserted_files.add(d.metadata["file_path"])
        return len(docs)

    async def delete_by_filter(self, collection, field, value):
        self.deleted.append((field, value))
        return 0


class _InMemoryVectorStore:
    """Fake vector store that behaves like Qdrant for file-level replacement."""

    def __init__(self):
        self.points: dict[str, dict] = {}
        self.deleted: list[tuple[str, str]] = []

    async def upsert(self, collection, docs, cache=None):
        for doc in docs:
            self.points[doc.chunk_id] = {"content": doc.content, **doc.metadata}
        return len(docs)

    async def delete_by_filter(self, collection, field, value):
        self.deleted.append((field, value))
        for point_id, payload in list(self.points.items()):
            if payload.get(field) == value:
                del self.points[point_id]


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    """Point RAG_HOME (and thus state.json) at a tmp dir; skip graph/summary."""
    rag_home = tmp_path / "rag_home"
    rag_home.mkdir()
    monkeypatch.setattr(indexer_mod, "RAG_HOME", rag_home, raising=True)
    monkeypatch.setenv("RAG_SKIP_GRAPH", "1")

    from rag.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    settings.lsp.enabled = False
    yield rag_home
    get_settings.cache_clear()


def _read_state_hashes(repo: Path) -> dict:
    state_path = _state_file_for(repo)
    if not state_path.exists():
        return {}
    return json.loads(state_path.read_text()).get("file_hashes", {})


async def test_clean_run_records_all_hashes(big_repo, isolated_state):
    """Baseline: a run with no failure persists a hash for every file."""
    vs = _CapturingVectorStore()
    result = await index_repository(str(big_repo), vs, collection="code_chunks", full=True)

    assert not result.errors, result.errors
    hashes = _read_state_hashes(big_repo)
    on_disk = {p.name for p in big_repo.glob("*.py")}
    assert set(hashes.keys()) == on_disk
    # Every recorded hash matches the actual file content.
    for rel, h in hashes.items():
        assert h == _file_hash(big_repo / rel)


async def test_crash_midflush_does_not_record_unflushed_hashes(big_repo, isolated_state):
    """If an upsert raises, no file whose chunks were in a failed/never-run
    batch may appear in the saved state. The whole run should bubble the error
    rather than silently persisting a hash for missing chunks."""
    # Fail the 2nd batch upsert — earlier batches succeed, later never run.
    vs = _CapturingVectorStore(fail_on_call=2)

    with pytest.raises(RuntimeError, match="simulated Qdrant crash"):
        await index_repository(str(big_repo), vs, collection="code_chunks", full=True)

    hashes = _read_state_hashes(big_repo)

    # THE INVARIANT: every file recorded in state must have had its chunks
    # actually upserted. No hash may exist for a file the store never saw.
    recorded = set(hashes.keys())
    flushed = {Path(p).name for p in vs.upserted_files}
    orphans = recorded - flushed
    assert not orphans, (
        f"state.json records hashes for files whose chunks were never "
        f"upserted (orphan state on crash): {sorted(orphans)}"
    )


async def test_partial_state_lets_next_run_reprocess(big_repo, isolated_state):
    """End-to-end of the invariant: after a crash, a clean re-run must re-index
    the files that were lost, ending with a complete state."""
    # First run crashes on batch 2.
    vs1 = _CapturingVectorStore(fail_on_call=2)
    with pytest.raises(RuntimeError):
        await index_repository(str(big_repo), vs1, collection="code_chunks", full=False)

    # Second run, no failure. Incremental: only files NOT in state get processed.
    vs2 = _CapturingVectorStore()
    await index_repository(str(big_repo), vs2, collection="code_chunks", full=False)

    # After the clean run, every on-disk file is tracked...
    hashes = _read_state_hashes(big_repo)
    on_disk = {p.name for p in big_repo.glob("*.py")}
    assert set(hashes.keys()) == on_disk

    # ...and the files lost in run 1 were actually re-upserted in run 2 (i.e.
    # they were NOT wrongly skipped as "already indexed").
    flushed_run1 = {Path(p).name for p in vs1.upserted_files}
    flushed_run2 = {Path(p).name for p in vs2.upserted_files}
    missing_after_run1 = on_disk - flushed_run1
    assert missing_after_run1, "test setup expected some files lost in run 1"
    assert missing_after_run1 <= flushed_run2, (
        f"files lost in run 1 were not re-indexed in run 2: "
        f"{sorted(missing_after_run1 - flushed_run2)}"
    )


async def test_incremental_reindex_removes_stale_chunks(tmp_path, isolated_state):
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "sample.py"
    source.write_text(
        "class C:\n"
        "    def keep(self):\n"
        "        return 'keep'\n\n"
        "    def old_method(self):\n"
        "        return 'old'\n"
    )

    vs = _InMemoryVectorStore()
    await index_repository(str(repo), vs, collection="code_chunks", full=True)
    assert any("old_method" in p["content"] for p in vs.points.values())

    source.write_text(
        "class C:\n"
        "    def keep(self):\n"
        "        return 'keep'\n"
    )

    await index_repository(str(repo), vs, collection="code_chunks", full=False)

    assert ("file_path", "sample.py") in vs.deleted
    assert not any("old_method" in p["content"] for p in vs.points.values())
