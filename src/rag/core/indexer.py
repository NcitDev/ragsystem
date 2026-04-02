"""Ingestion pipeline with incremental git-based indexing."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from rag.config import get_settings
from rag.core.chunker import (
    Chunk,
    chunk_code,
    chunk_document,
    detect_language,
    supported_extensions,
)
from rag.core.vectorstore import ChunkDocument, QdrantVectorStore

logger = structlog.get_logger()

STATE_FILE = ".rag_index_state.json"

ProgressCallback = Callable[[str, int, int], None] | None


@dataclass
class IndexState:
    last_commit: str = ""
    file_hashes: dict[str, str] = field(default_factory=dict)

    def save(self, path: Path) -> None:
        state_path = path / STATE_FILE
        tmp_path = state_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps({
            "last_commit": self.last_commit,
            "file_hashes": self.file_hashes,
        }, indent=2))
        tmp_path.replace(state_path)  # Atomic on POSIX

    @classmethod
    def load(cls, path: Path) -> IndexState:
        state_path = path / STATE_FILE
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
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _get_changed_files(repo_path: Path, since_commit: str) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", since_commit, "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return [f for f in result.stdout.strip().split("\n") if f]
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
    """
    settings = get_settings()
    collection = collection or settings.qdrant.code_collection
    path = Path(repo_path).resolve()
    result = IndexResult()

    if not path.exists():
        result.errors.append(f"Repository path does not exist: {repo_path}")
        return result

    state = IndexState() if full else IndexState.load(path)
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

    new_hashes: dict[str, str] = dict(state.file_hashes)
    batch: list[ChunkDocument] = []
    batch_size = 50
    detected_langs: set[str] = set()

    for idx, file_path in enumerate(files_to_process):
        rel_path = str(file_path.relative_to(path))
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            language = detect_language(rel_path)
            if language:
                detected_langs.add(language)

            chunks = chunk_code(content, rel_path, language)

            # Enrich Python chunks with pattern metadata
            if language == "python":
                for chunk in chunks:
                    chunk.enrich_metadata(test_files=test_files)

            for chunk in chunks:
                batch.append(ChunkDocument(
                    content=chunk.content,
                    metadata=chunk.to_index_metadata(),
                    chunk_id=chunk.chunk_id,
                ))

            # Flush batch when it reaches threshold — avoids OOM on large repos
            if len(batch) >= batch_size:
                # LSP enrichment on batch
                if settings.lsp.enabled:
                    await _lsp_enrich_batch(batch, str(path), list(detected_langs))
                result.chunks_indexed += await vectorstore.upsert(collection, batch)
                batch = []

            new_hashes[rel_path] = _file_hash(file_path)
            result.files_processed += 1

            if on_progress:
                on_progress(rel_path, idx + 1, total_files)

        except Exception as e:
            logger.warning("file_index_error", file=rel_path, error=str(e))
            result.errors.append(f"{rel_path}: {e}")

    # Flush remaining batch
    if batch:
        if settings.lsp.enabled:
            await _lsp_enrich_batch(batch, str(path), list(detected_langs))
        result.chunks_indexed += await vectorstore.upsert(collection, batch)

    # Delete chunks for removed files
    indexed_files = set(new_hashes.keys())
    current_files = {str(f.relative_to(path)) for f in all_files}
    removed = indexed_files - current_files
    for removed_file in removed:
        await vectorstore.delete_by_filter(collection, "file_path", removed_file)
        del new_hashes[removed_file]
        result.files_deleted += 1

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
                documents.append(ChunkDocument(
                    content=chunk.content,
                    metadata=chunk.to_index_metadata(),
                    chunk_id=chunk.chunk_id,
                ))

            result.files_processed += 1
        except Exception as e:
            logger.warning("doc_index_error", file=str(file_path), error=str(e))
            result.errors.append(f"{file_path}: {e}")

    if documents:
        result.chunks_indexed = await vectorstore.upsert(collection, documents)

    return result
