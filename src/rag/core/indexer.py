"""Ingestion pipeline with incremental git-based indexing."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from rag.config import RAG_HOME, get_settings
from rag.core.chunker import chunk_code, chunk_document, detect_language, supported_extensions
from rag.core.vectorstore import ChunkDocument, QdrantVectorStore

logger = structlog.get_logger()

# Legacy in-repo marker — kept for migration only. New state lives under
# ~/.rag/repos/<sha256(abs_path)[:16]>/state.json so we don't pollute
# user repositories.
STATE_FILE = ".rag_index_state.json"

ProgressCallback = Callable[[str, int, int], None] | None


def _state_dir_for(path: Path) -> Path:
    """Return the per-repo state directory under RAG_HOME.

    Uses the first 16 hex chars of sha256(absolute_path) so that two
    different repos never collide while the result stays filesystem-friendly.
    """
    abs_str = str(Path(path).resolve())
    digest = hashlib.sha256(abs_str.encode("utf-8")).hexdigest()[:16]
    return RAG_HOME / "repos" / digest


def _state_file_for(path: Path) -> Path:
    return _state_dir_for(path) / "state.json"


def _lock_file_for(path: Path) -> Path:
    return _state_dir_for(path) / "index.lock"


class IndexLockError(Exception):
    """Raised when another index run already holds the per-repo lock."""


class _RepoIndexLock:
    """Non-blocking advisory file lock serializing index runs for one repo.

    Two concurrent ``index_repository`` calls on the same repo would race the
    shared ``state.json`` (interleaved hash maps, one overwriting the other).
    An exclusive ``flock`` makes the second caller fail fast instead of
    corrupting state. Best-effort: if locking is unsupported, we proceed.
    """

    def __init__(self, repo_path: Path) -> None:
        self._lock_path = _lock_file_for(repo_path)
        self._fd: int | None = None

    def __enter__(self) -> "_RepoIndexLock":
        import os as _os

        try:
            import fcntl
        except ImportError:  # pragma: no cover - non-POSIX
            return self
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = _os.open(str(self._lock_path), _os.O_CREAT | _os.O_RDWR, 0o600)
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            _os.close(self._fd)
            self._fd = None
            raise IndexLockError(
                f"Another index run is in progress for {self._lock_path.parent.name}; "
                "refusing to run concurrently."
            )
        return self

    def __exit__(self, *exc) -> None:
        import os as _os

        if self._fd is not None:
            try:
                import fcntl

                fcntl.flock(self._fd, fcntl.LOCK_UN)
            except Exception:
                pass
            _os.close(self._fd)
            self._fd = None


@dataclass
class IndexState:
    last_commit: str = ""
    file_hashes: dict[str, str] = field(default_factory=dict)

    def save(self, path: Path) -> None:
        state_path = _state_file_for(path)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = state_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps({
            "last_commit": self.last_commit,
            "file_hashes": self.file_hashes,
        }, indent=2))
        tmp_path.replace(state_path)  # Atomic on POSIX

    @classmethod
    def load(cls, path: Path) -> IndexState:
        state_path = _state_file_for(path)
        legacy_path = path / STATE_FILE

        # Migration: pull data out of any in-repo legacy file, write to the
        # new location, then remove the stale file from the user's repo.
        if not state_path.exists() and legacy_path.exists():
            try:
                data = json.loads(legacy_path.read_text())
                migrated = cls(
                    last_commit=data.get("last_commit", ""),
                    file_hashes=data.get("file_hashes", {}),
                )
                migrated.save(path)
                try:
                    legacy_path.unlink()
                except OSError as e:
                    logger.warning(
                        "legacy_state_unlink_failed",
                        path=str(legacy_path),
                        error=str(e),
                    )
                logger.info(
                    "index_state_migrated",
                    legacy=str(legacy_path),
                    new=str(state_path),
                )
                return migrated
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(
                    "legacy_state_migration_failed",
                    path=str(legacy_path),
                    error=str(e),
                )

        if not state_path.exists():
            return cls()
        data = json.loads(state_path.read_text())
        return cls(
            last_commit=data.get("last_commit", ""),
            file_hashes=data.get("file_hashes", {}),
        )


@dataclass
class IndexResult:
    files_processed: int = 0
    chunks_indexed: int = 0
    files_skipped: int = 0
    files_deleted: int = 0
    errors: list[str] = field(default_factory=list)


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _get_head_commit(repo_path: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except subprocess.TimeoutExpired:
        logger.warning("git_head_commit_timeout", repo_path=str(repo_path))
        return ""
    except Exception:
        return ""


def _get_changed_files(repo_path: Path, since_commit: str) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", since_commit, "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return [f for f in result.stdout.strip().split("\n") if f]
    except subprocess.TimeoutExpired:
        logger.warning(
            "git_changed_files_timeout",
            repo_path=str(repo_path),
            since_commit=since_commit,
        )
        return []
    except Exception:
        pass
    return []


def _discover_files(repo_path: Path, extensions: list[str] | None = None) -> list[Path]:
    settings = get_settings()
    if extensions is None:
        extensions = supported_extensions()

    skip_dirs = set(settings.index.skip_dirs)

    files: list[Path] = []
    for ext in extensions:
        files.extend(repo_path.rglob(f"*{ext}"))

    return [
        f for f in files
        if not any(part in skip_dirs for part in f.parts)
    ]


def _discover_test_files(repo_path: Path) -> set[str]:
    """Find all test file names for has_unit_test detection."""
    test_files: set[str] = set()
    for f in repo_path.rglob("test_*.py"):
        test_files.add(f.stem)
    for f in repo_path.rglob("*_test.py"):
        test_files.add(f.stem)
    return test_files


async def index_repository(
    repo_path: str,
    vectorstore: QdrantVectorStore,
    collection: str | None = None,
    full: bool = False,
    languages: list[str] | None = None,
    on_progress: ProgressCallback = None,
) -> IndexResult:
    """Index a git repository into the vector store.

    Supports incremental indexing — only re-indexes files that changed since last run.

    Serialized per-repo via an advisory file lock so two concurrent runs can't
    race the shared state.json.
    """
    path = Path(repo_path).resolve()
    if not path.exists():
        result = IndexResult()
        result.errors.append(f"Repository path does not exist: {repo_path}")
        return result
    with _RepoIndexLock(path):
        return await _index_repository_locked(
            path, vectorstore, collection, full, languages, on_progress
        )


async def _index_repository_locked(
    path: Path,
    vectorstore: QdrantVectorStore,
    collection: str | None = None,
    full: bool = False,
    languages: list[str] | None = None,
    on_progress: ProgressCallback = None,
) -> IndexResult:
    settings = get_settings()
    collection = collection or settings.qdrant.code_collection
    result = IndexResult()

    previous_state = IndexState.load(path)
    state = IndexState() if full else previous_state
    if full:
        # Wipe the materialized overview counters — incremental upserts
        # below will rebuild them from scratch.
        try:
            from rag.storage import db as _db
            _db.reset_overview()
        except Exception as e:  # pragma: no cover - non-critical
            logger.warning("overview_reset_failed", error=str(e))
    current_commit = _get_head_commit(path)

    # Determine extensions to scan
    extensions = None
    if languages:
        from rag.core.chunker import LANGUAGE_CONFIG
        extensions = []
        for lang in languages:
            if lang in LANGUAGE_CONFIG:
                extensions.extend(LANGUAGE_CONFIG[lang]["extensions"])

    all_files = _discover_files(path, extensions)
    test_files = _discover_test_files(path)

    if not full and state.last_commit and current_commit:
        changed = set(_get_changed_files(path, state.last_commit))
        files_to_process = [f for f in all_files if str(f.relative_to(path)) in changed]

        for f in all_files:
            rel = str(f.relative_to(path))
            current_hash = _file_hash(f)
            if rel not in changed and state.file_hashes.get(rel) != current_hash:
                files_to_process.append(f)
    else:
        files_to_process = all_files

    total_files = len(files_to_process)
    logger.info(
        "indexing_start",
        repo=str(path),
        total_files=len(all_files),
        to_process=total_files,
        incremental=not full,
    )

    # NOTE: TODO: stream to SQLite via storage.db.file_hashes table when repos
    # exceed ~100k files. Current in-memory approach OK for typical repos.
    new_hashes: dict[str, str] = dict(state.file_hashes)
    processed_files: set[str] = set()  # rel_paths actually re-chunked this run (for LOD scoping)
    batch: list[ChunkDocument] = []
    batch_size = 64  # aligns with embedder sub-batch for one-HTTP-call-per-flush
    detected_langs: set[str] = set()
    pending_upsert: asyncio.Task | None = None

    # Crash-consistency: a file's hash is only promoted into ``new_hashes`` once
    # the batch carrying its chunks has been confirmed upserted to Qdrant. Until
    # then it sits in ``staged_hashes`` (this run) / ``pending_hashes`` (the
    # batch currently being upserted). If indexing crashes mid-flush, the file's
    # hash never gets saved, so the next run re-processes it instead of skipping
    # it and leaving its chunks permanently missing.
    staged_hashes: dict[str, str] = {}
    pending_hashes: dict[str, str] = {}

    # Initialize embedding cache
    from rag.core.cache import EmbeddingCache
    embed_cache = EmbeddingCache()

    async def _flush_batch(docs: list[ChunkDocument]) -> int:
        if settings.lsp.enabled:
            await _lsp_enrich_batch(docs, str(path), list(detected_langs))
        # Upsert overwrites matching point IDs but does not remove points for
        # chunks that disappeared or shifted line ranges. Clear each changed
        # file first so the collection mirrors the current file contents.
        file_paths = sorted({
            doc.metadata.get("file_path", "")
            for doc in docs
            if doc.metadata.get("file_path")
        })
        for file_path in file_paths:
            await vectorstore.delete_by_filter(collection, "file_path", file_path)
        count = await vectorstore.upsert(collection, docs, cache=embed_cache)
        _update_overview_stats(docs)
        return count

    def _process_file(fp: Path, rel: str) -> list[ChunkDocument]:
        """CPU-bound: chunk + enrich a single file. Runs in thread pool."""
        content = fp.read_text(encoding="utf-8", errors="replace")
        language = detect_language(rel)
        if language:
            detected_langs.add(language)
        chunks = chunk_code(content, rel, language)
        if language == "python":
            for chunk in chunks:
                chunk.enrich_metadata(test_files=test_files)
        return [
            ChunkDocument(content=c.content, metadata=c.to_index_metadata(), chunk_id=c.chunk_id)
            for c in chunks
        ]

    for idx, file_path in enumerate(files_to_process):
        rel_path = str(file_path.relative_to(path))
        try:
            # Run CPU-bound chunking in thread pool to avoid blocking event loop
            docs = await asyncio.to_thread(_process_file, file_path, rel_path)
            batch.extend(docs)

            # Stage this file's hash; it is only promoted to new_hashes once the
            # batch carrying its chunks is confirmed flushed.
            staged_hashes[rel_path] = _file_hash(file_path)
            processed_files.add(rel_path)
            result.files_processed += 1

            # Pipeline: await previous upsert (committing its hashes), start new one
            if len(batch) >= batch_size:
                if pending_upsert is not None:
                    result.chunks_indexed += await pending_upsert
                    new_hashes.update(pending_hashes)
                pending_upsert = asyncio.create_task(_flush_batch(list(batch)))
                pending_hashes = staged_hashes
                staged_hashes = {}
                batch = []

            if on_progress:
                on_progress(rel_path, idx + 1, total_files)

        except Exception as e:
            logger.warning("file_index_error", file=rel_path, error=str(e))
            result.errors.append(f"{rel_path}: {e}")

    # Await pending + flush remaining. Each confirmed upsert promotes its
    # staged hashes; the trailing partial batch (still in ``staged_hashes``)
    # is committed only after its own upsert returns.
    if pending_upsert is not None:
        result.chunks_indexed += await pending_upsert
        new_hashes.update(pending_hashes)
    if batch:
        result.chunks_indexed += await _flush_batch(batch)
    new_hashes.update(staged_hashes)

    # Delete chunks for removed files. Delete the vectors BEFORE dropping the
    # file from new_hashes so a crash between the two leaves the file still
    # tracked (next run retries the delete) rather than orphaning its chunks.
    indexed_files = set(previous_state.file_hashes.keys()) if full else set(new_hashes.keys())
    current_files = {str(f.relative_to(path)) for f in all_files}
    removed = indexed_files - current_files
    for removed_file in removed:
        await vectorstore.delete_by_filter(collection, "file_path", removed_file)
        new_hashes.pop(removed_file, None)
        result.files_deleted += 1

    # Incremental runs replace changed files in-place. Rebuild materialized
    # counters after deletes/upserts so /overview does not double-count old
    # chunks. Full runs already reset at the start and rebuild while upserting.
    if not full and (processed_files or removed):
        await _rebuild_overview_stats(vectorstore, collection)

    # Build code graph + communities + summaries.
    # Set RAG_SKIP_SUMMARIES=1 to skip the (slow, Ollama-bound) module summary
    # generation step — useful for first-pass indexing or when no fast LLM is
    # available. Graph + communities still get built unless RAG_SKIP_GRAPH=1.
    import os
    if os.environ.get("RAG_SKIP_GRAPH") == "1":
        logger.info("graph_build_skipped", reason="RAG_SKIP_GRAPH=1")
    else:
        try:
            # Pass changed-file set so LOD regen scopes to affected dirs/files.
            # On --full runs we pass None to force a full rebuild.
            lod_scope = None if full else processed_files
            await _build_graph_and_summaries(vectorstore, collection, lod_scope)
        except Exception as e:
            logger.warning("graph_build_error", error=str(e))

    # Save state
    state = IndexState(last_commit=current_commit, file_hashes=new_hashes)
    state.save(path)

    result.files_skipped = len(all_files) - total_files

    logger.info(
        "indexing_complete",
        files_processed=result.files_processed,
        chunks_indexed=result.chunks_indexed,
        files_skipped=result.files_skipped,
        files_deleted=result.files_deleted,
    )

    return result


async def _build_graph_and_summaries(
    vectorstore: QdrantVectorStore,
    collection: str,
    changed_files: set[str] | None = None,
) -> None:
    """Build knowledge graph, detect communities, generate community + LOD summaries.

    Args:
        changed_files: relative file paths that changed in this run. Used to
            scope L0/L1 regeneration to only the affected dirs/files.
    """
    from rag.core.graph import get_graph
    from rag.core.summaries import generate_community_summaries, generate_lod_summaries

    # Collect all chunk payloads from Qdrant
    client = await vectorstore._get_client()
    all_chunks: list[dict] = []
    offset = None
    while True:
        points, offset = await client.scroll(
            collection_name=collection,
            limit=200,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        if not points:
            break
        for p in points:
            if p.payload:
                all_chunks.append(dict(p.payload))
        if offset is None:
            break

    if not all_chunks:
        return

    # Build graph from chunk metadata
    graph = get_graph()
    graph.build_from_chunks(all_chunks)

    # Detect communities
    graph.detect_communities()

    # Generate summaries for each community
    await generate_community_summaries(graph, vectorstore, all_chunks)

    # Hierarchical LOD summaries (L0 = module/dir, L1 = file). Scoped to
    # changed files when incremental; full pass otherwise. Skipped when
    # RAG_SKIP_SUMMARIES=1 (checked inside generate_lod_summaries).
    try:
        await generate_lod_summaries(all_chunks, vectorstore, changed_files)
    except Exception as e:
        logger.warning("lod_summaries_error", error=str(e))

    # Save graph to disk for query-time use
    graph.save()


def _update_overview_stats(docs: list[ChunkDocument]) -> None:
    """Increment materialized overview counters for each successfully indexed
    chunk. Called after upsert; failures are non-fatal — /overview falls back
    to a scroll-based aggregate when counters are missing.
    """
    try:
        from rag.storage import db as _db
        for doc in docs:
            meta = doc.metadata or {}
            lang = meta.get("language", "unknown")
            patterns = meta.get("patterns", []) or []
            cc = meta.get("complexity_cyclomatic")
            _db.incr_overview(lang, list(patterns), cc)
    except Exception as e:  # pragma: no cover - non-critical
        logger.warning("overview_incr_failed", error=str(e))


async def _rebuild_overview_stats(vectorstore: QdrantVectorStore, collection: str) -> None:
    """Recompute materialized overview counters from the current collection."""
    try:
        from rag.storage import db as _db

        _db.reset_overview()
        client = await vectorstore._get_client()
        offset = None
        while True:
            points, offset = await client.scroll(
                collection_name=collection,
                limit=200,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            if not points:
                break
            for point in points:
                payload = point.payload or {}
                _db.incr_overview(
                    payload.get("language", "unknown"),
                    list(payload.get("patterns", []) or []),
                    payload.get("complexity_cyclomatic"),
                )
            if offset is None:
                break
    except Exception as e:  # pragma: no cover - non-critical
        logger.warning("overview_rebuild_failed", error=str(e))


async def _lsp_enrich_batch(batch: list[ChunkDocument], repo_path: str, languages: list[str]) -> None:
    """Run LSP enrichment on a batch of documents."""
    try:
        from rag.core.lsp import enrich_chunks_with_lsp

        chunk_metas = [doc.metadata for doc in batch]
        await enrich_chunks_with_lsp(repo_path, chunk_metas, languages)
        for doc, meta in zip(batch, chunk_metas):
            doc.metadata = meta
    except Exception as e:
        logger.warning("lsp_enrich_batch_error", error=str(e))


async def index_documents(
    docs_path: str,
    vectorstore: QdrantVectorStore,
    collection: str | None = None,
    doc_types: list[str] | None = None,
) -> IndexResult:
    """Index documentation files (markdown, text) into the vector store."""
    settings = get_settings()
    collection = collection or settings.qdrant.docs_collection
    path = Path(docs_path).resolve()
    result = IndexResult()

    if not path.exists():
        result.errors.append(f"Docs path does not exist: {docs_path}")
        return result

    doc_types = doc_types or ["markdown", "text"]
    extensions = []
    if "markdown" in doc_types:
        extensions.extend([".md", ".mdx"])
    if "text" in doc_types:
        extensions.extend([".txt", ".rst"])

    files = []
    for ext in extensions:
        files.extend(path.rglob(f"*{ext}"))

    documents: list[ChunkDocument] = []
    for file_path in files:
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            rel_path = str(file_path.relative_to(path))
            doc_type = "markdown" if file_path.suffix in (".md", ".mdx") else "text"

            chunks = chunk_document(content, rel_path, doc_type)

            for chunk in chunks:
                meta = chunk.to_index_metadata()
                # Enrich docs with cross-references to code symbols
                from rag.core.crossref import enrich_doc_chunk_with_code_refs
                enrich_doc_chunk_with_code_refs(meta, chunk.content)
                documents.append(ChunkDocument(
                    content=chunk.content,
                    metadata=meta,
                    chunk_id=chunk.chunk_id,
                ))

            result.files_processed += 1
        except Exception as e:
            logger.warning("doc_index_error", file=str(file_path), error=str(e))
            result.errors.append(f"{file_path}: {e}")

    if documents:
        result.chunks_indexed = await vectorstore.upsert(collection, documents)

    return result
