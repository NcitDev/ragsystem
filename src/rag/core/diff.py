"""Diff-aware search – search within recent git changes."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class DiffChunk:
    """A single file-level diff entry."""

    file_path: str
    change_type: str  # added, modified, deleted
    added_lines: list[str] = field(default_factory=list)
    removed_lines: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_git(repo_path: str, args: list[str]) -> str | None:
    """Run a git command and return stdout, or *None* on failure."""
    cmd = ["git", "-C", repo_path] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning(
                "git_command_failed",
                cmd=cmd,
                returncode=result.returncode,
                stderr=result.stderr.strip(),
            )
            return None
        return result.stdout
    except FileNotFoundError:
        logger.warning("git_not_found", repo_path=repo_path)
        return None
    except subprocess.TimeoutExpired:
        logger.warning("git_command_timeout", cmd=cmd)
        return None


def _is_git_repo(repo_path: str) -> bool:
    """Return True if *repo_path* is inside a git work tree."""
    out = _run_git(repo_path, ["rev-parse", "--is-inside-work-tree"])
    return out is not None and out.strip() == "true"


def _parse_since(since: str) -> list[str]:
    """Translate the human-friendly *since* value into git-log/diff args.

    Supports commit-ish refs (``HEAD~5``, a sha, a branch name) as well as
    relative date strings like ``"3 days ago"``.
    """
    # Heuristic: if the value contains spaces and looks like a relative date,
    # use --since; otherwise treat it as a commit ref.
    date_keywords = {"day", "days", "week", "weeks", "hour", "hours", "minute", "minutes", "month", "months", "ago"}
    tokens = set(since.lower().split())
    if tokens & date_keywords:
        return ["--since", since]
    return [since + "..HEAD"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_changed_files_since(repo_path: str, since: str) -> list[str]:
    """Return a list of file paths that changed since *since*.

    Parameters
    ----------
    repo_path:
        Root of the git repository.
    since:
        A commit-ish (``HEAD~5``, sha, branch name) **or** a relative date
        string understood by ``git log --since`` (e.g. ``"3 days ago"``).

    Returns an empty list when *repo_path* is not a git repository.
    """
    if not _is_git_repo(repo_path):
        logger.info("not_a_git_repo", repo_path=repo_path)
        return []

    since_args = _parse_since(since)

    if "--since" in since_args:
        # Date-based: ask git-log for the affected files.
        out = _run_git(repo_path, ["log", *since_args, "--name-only", "--pretty=format:"])
    else:
        # Ref-based: use diff directly.
        out = _run_git(repo_path, ["diff", "--name-only", *since_args])

    if out is None:
        return []

    files = sorted({line for line in out.splitlines() if line.strip()})
    logger.debug("changed_files", count=len(files), since=since)
    return files


def get_diff_content(repo_path: str, since: str) -> list[DiffChunk]:
    """Return :class:`DiffChunk` objects for every file in the diff.

    Parameters
    ----------
    repo_path:
        Root of the git repository.
    since:
        Same semantics as :func:`get_changed_files_since`.
    """
    if not _is_git_repo(repo_path):
        logger.info("not_a_git_repo", repo_path=repo_path)
        return []

    since_args = _parse_since(since)

    if "--since" in since_args:
        # For date-based ranges we need the earliest commit in the range.
        hash_out = _run_git(
            repo_path,
            ["log", *since_args, "--reverse", "--pretty=format:%H"],
        )
        if not hash_out or not hash_out.strip():
            return []
        first_commit = hash_out.strip().splitlines()[0]
        diff_args = [first_commit + "..HEAD"]
    else:
        diff_args = since_args

    out = _run_git(repo_path, ["diff", *diff_args])
    if out is None:
        return []

    return _parse_unified_diff(out)


def _parse_unified_diff(diff_text: str) -> list[DiffChunk]:
    """Parse unified diff output into :class:`DiffChunk` objects."""
    chunks: list[DiffChunk] = []
    current_file: str | None = None
    added: list[str] = []
    removed: list[str] = []
    has_added = False
    has_removed = False

    def _flush() -> None:
        nonlocal current_file, added, removed, has_added, has_removed
        if current_file is not None:
            if has_added and not has_removed:
                change_type = "added"
            elif has_removed and not has_added:
                change_type = "deleted"
            else:
                change_type = "modified"
            chunks.append(
                DiffChunk(
                    file_path=current_file,
                    change_type=change_type,
                    added_lines=added,
                    removed_lines=removed,
                )
            )
        current_file = None
        added = []
        removed = []
        has_added = False
        has_removed = False

    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            _flush()
            # Extract path from "diff --git a/foo b/foo"
            parts = line.split(" b/", 1)
            current_file = parts[1] if len(parts) == 2 else None
        elif line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
            has_added = True
        elif line.startswith("-") and not line.startswith("---"):
            removed.append(line[1:])
            has_removed = True

    _flush()
    logger.debug("diff_chunks_parsed", count=len(chunks))
    return chunks


async def search_in_diff(
    repo_path: str,
    since: str,
    query: str,
    vectorstore: Any,
    top_k: int = 10,
) -> list[Any]:
    """Search the indexed codebase but restrict results to recently changed files.

    Parameters
    ----------
    repo_path:
        Root of the git repository.
    since:
        Same semantics as :func:`get_changed_files_since`.
    query:
        Natural-language or keyword search query.
    vectorstore:
        A :class:`rag.core.vectorstore.QdrantVectorStore`-compatible object.
    top_k:
        Maximum number of results to return.

    Returns an empty list when *repo_path* is not a git repo or no files
    changed.
    """
    changed_files = get_changed_files_since(repo_path, since)
    if not changed_files:
        logger.info("search_in_diff_no_changes", since=since)
        return []

    logger.info(
        "search_in_diff",
        query=query,
        changed_files_count=len(changed_files),
        top_k=top_k,
    )

    from rag.config import get_settings

    settings = get_settings()
    results = await vectorstore.search(
        collection=settings.qdrant.code_collection,
        query=query,
        top_k=top_k,
        filters={"file_path": changed_files},
    )

    logger.info("search_in_diff_results", total=len(results), filtered=len(results))
    return results


def _extract_file_path(result: Any) -> str | None:
    """Best-effort extraction of a file path from a search result."""
    # dict with "file_path" key
    if isinstance(result, dict):
        return result.get("file_path") or result.get("metadata", {}).get("file_path")
    # object with .file_path
    if hasattr(result, "file_path"):
        return result.file_path  # type: ignore[union-attr]
    # object with .payload / .metadata  (Qdrant-style)
    payload = getattr(result, "payload", None) or getattr(result, "metadata", None)
    if isinstance(payload, dict):
        return payload.get("file_path")
    return None
