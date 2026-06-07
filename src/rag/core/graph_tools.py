"""CodeGraph-like exact navigation helpers built on AST index + SQLite FTS."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from rag.core import ast_index
from rag.storage import db

_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_SKIP_CALLEES = {
    "if",
    "for",
    "while",
    "when",
    "switch",
    "return",
    "throw",
    "catch",
    "super",
    "this",
    "class",
    "interface",
    "object",
    "fun",
    "def",
    "function",
}


def files(collection: str, query: str = "", limit: int = 100, tests_only: bool = False) -> list[dict[str, Any]]:
    return db.list_code_files(
        collection=collection,
        query=query,
        limit=limit,
        tests_only=tests_only,
    )


def node(
    repo_path: str,
    collection: str,
    symbol: str,
    definitions_limit: int = 20,
    usages_limit: int = 20,
) -> dict[str, Any]:
    symbols = [symbol.strip()] if symbol.strip() else []
    resolved = ast_index.resolve_symbols(
        repo_path,
        symbols,
        definitions_limit=definitions_limit,
        usages_limit=usages_limit,
    )
    if not resolved.get("definitions"):
        fallback = db.search_code_chunks(symbol, collection=collection, limit=definitions_limit)
        resolved["definitions"] = fallback
    return {
        "symbol": symbol,
        "definitions": resolved.get("definitions", []),
        "usages": resolved.get("usages", []),
        "provenance": "ast_index",
    }


def callers(repo_path: str, symbol: str, limit: int = 50) -> list[dict[str, Any]]:
    direct = ast_index.callers(repo_path, symbol, limit=limit)
    if direct:
        return direct
    return ast_index.call_tree(repo_path, symbol, limit=limit)


def callees(repo_path: str, collection: str, symbol: str, limit: int = 50) -> list[dict[str, Any]]:
    """Return likely callees from a symbol body.

    Current ast-index exposes callers/call-tree but not a callee edge list, so
    this is deliberately marked heuristic by callers of this helper.
    """
    resolved = node(repo_path, collection, symbol, definitions_limit=3, usages_limit=0)
    names: list[str] = []
    for item in resolved.get("definitions", []):
        for match in _CALL_RE.finditer(str(item.get("code", ""))):
            name = match.group(1)
            if name == symbol or name.lower() in _SKIP_CALLEES:
                continue
            if name not in names:
                names.append(name)
            if len(names) >= limit * 2:
                break
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()
    for name in names:
        resolved_callee = ast_index.resolve_symbols(
            repo_path,
            [name],
            definitions_limit=2,
            usages_limit=0,
        )
        candidates = resolved_callee.get("definitions") or db.search_code_chunks(
            name,
            collection=collection,
            limit=2,
        )
        for candidate in candidates:
            key = (
                str(candidate.get("file_path", "")),
                int(candidate.get("start_line", 0) or 0),
                str(candidate.get("name", "")),
            )
            if key in seen:
                continue
            seen.add(key)
            out.append({**candidate, "callee_name": name, "relation_source": "heuristic_source_scan"})
            if len(out) >= limit:
                return out
    return out


def impact(repo_path: str, collection: str, symbol: str, limit: int = 50) -> dict[str, Any]:
    resolved = node(
        repo_path,
        collection,
        symbol,
        definitions_limit=min(limit, 20),
        usages_limit=limit,
    )
    caller_nodes = callers(repo_path, symbol, limit=limit)
    impacted_files: list[str] = []
    for item in [
        *resolved.get("definitions", []),
        *resolved.get("usages", []),
        *caller_nodes,
    ]:
        path = str(item.get("file_path", ""))
        if path and path not in impacted_files:
            impacted_files.append(path)

    tests = db.related_test_files(collection, impacted_files, limit=limit)
    stale_files = _stale_index_files(repo_path, collection, impacted_files)
    return {
        "symbol": symbol,
        "definitions": resolved.get("definitions", []),
        "usages": resolved.get("usages", []),
        "callers": caller_nodes,
        "affected_files": impacted_files[:limit],
        "tests": tests,
        "risks": [
            *_impact_risks(resolved, caller_nodes, tests),
            *_stale_risks(stale_files),
        ],
        "metrics": {
            "definition_count": len(resolved.get("definitions", [])),
            "usage_count": len(resolved.get("usages", [])),
            "caller_count": len(caller_nodes),
            "affected_file_count": len(impacted_files),
            "test_count": len(tests),
            "stale_file_count": len(stale_files),
            "whole_file_reads_avoided": True,
        },
    }


def affected(
    repo_path: str,
    collection: str,
    files: list[str] | None = None,
    since: str = "HEAD",
    limit: int = 100,
) -> dict[str, Any]:
    changed_files = files or _git_changed_files(repo_path, since)
    indexed = {item["file_path"]: item for item in db.list_code_files(collection=collection, limit=10000)}
    affected_files = [path for path in changed_files if path in indexed]
    tests = db.related_test_files(collection, affected_files or changed_files, limit=limit)
    modules = _modules_for_files(affected_files or changed_files)
    stale_files = _stale_index_files(repo_path, collection, affected_files)
    return {
        "changed_files": changed_files,
        "affected_files": affected_files,
        "tests": tests,
        "modules": modules,
        "risks": [
            *_affected_risks(changed_files, affected_files, tests),
            *_stale_risks(stale_files),
        ],
        "metrics": {
            "changed_file_count": len(changed_files),
            "indexed_changed_file_count": len(affected_files),
            "test_count": len(tests),
            "stale_file_count": len(stale_files),
            "whole_file_reads_avoided": True,
        },
    }


def _git_changed_files(repo_path: str, since: str) -> list[str]:
    root = Path(repo_path)
    if not root.exists():
        return []
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", since],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _modules_for_files(files: list[str]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for path in files:
        parts = [p for p in path.split("/") if p]
        if not parts:
            continue
        module = "/".join(parts[: min(3, max(1, len(parts) - 1))])
        counts[module] = counts.get(module, 0) + 1
    return [
        {"path": path, "file_count": count}
        for path, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
    ]


def _stale_index_files(repo_path: str, collection: str, files: list[str]) -> list[str]:
    if not files:
        return []
    indexed = {item["file_path"]: item for item in db.list_code_files(collection=collection, limit=10000)}
    root = Path(repo_path)
    stale: list[str] = []
    for path in files:
        item = indexed.get(path)
        if not item:
            continue
        try:
            mtime = (root / path).stat().st_mtime
        except OSError:
            continue
        if mtime > float(item.get("updated_at", 0.0) or 0.0) + 2.0:
            stale.append(path)
    return stale


def _stale_risks(stale_files: list[str]) -> list[str]:
    if not stale_files:
        return []
    preview = ", ".join(stale_files[:5])
    suffix = "..." if len(stale_files) > 5 else ""
    return [f"Index may be stale for changed files: {preview}{suffix}. Verify locally before editing."]


def _impact_risks(resolved: dict[str, Any], caller_nodes: list[dict[str, Any]], tests: list[dict[str, Any]]) -> list[str]:
    risks: list[str] = []
    if len(resolved.get("definitions", [])) > 1:
        risks.append("Symbol has multiple definitions; disambiguate by file path before editing.")
    if caller_nodes and not tests:
        risks.append("Callers were found but no related tests were identified.")
    if not resolved.get("definitions"):
        risks.append("No exact definition found; verify symbol spelling or index freshness.")
    return risks


def _affected_risks(changed_files: list[str], affected_files: list[str], tests: list[dict[str, Any]]) -> list[str]:
    risks: list[str] = []
    if changed_files and not affected_files:
        risks.append("Changed files were not found in the exact code index; index may be stale.")
    if affected_files and not tests:
        risks.append("No related tests identified for changed indexed files.")
    return risks
