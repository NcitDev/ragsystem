"""Optional adapter for the external ``ast-index`` CLI.

The CLI gives us fast AST-aware exact lookup (symbols/usages) that is better
suited than embeddings for developer navigation. This module is deliberately
best-effort: if the binary is missing, the index is absent, or a command fails,
callers get an empty list and can fall back to SQLite/Qdrant retrieval.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_SYMBOL_LINE_RE = re.compile(
    r"\b(class|interface|object|enum|fun|def|function|val|var)\b|=>|\{"
)
_CALL_TREE_LINE_RE = re.compile(
    r"^(?P<indent>\s*)←\s+(?P<name>.+?)\s+\((?P<path>.+):(?P<line>\d+)\)"
)
_CALLERS_FILE_RE = re.compile(r"^\s*(?P<path>[^:\n].+):\s*$")
_CALLERS_LINE_RE = re.compile(r"^\s*:(?P<line>\d+)\s+(?P<context>.*)$")
_BROAD_PROJECT_TERMS = {
    "processing", "process", "order", "checkout", "service", "manager",
    "presenter", "interactor", "state", "result", "feature", "screen",
}


@dataclass
class AstIndexHit:
    file_path: str
    line: int
    name: str = ""
    kind: str = ""
    signature: str = ""
    context: str = ""
    source: str = ""
    code: str = ""
    start_line: int = 0
    end_line: int = 0
    score: float = 0.0

    def to_context_candidate(self) -> dict[str, Any]:
        lines = f"{self.start_line or self.line}-{self.end_line or self.line}"
        label = self.name or self.signature or self.context or Path(self.file_path).name
        return {
            "chunk_id": f"ast:{self.file_path}:{self.start_line or self.line}:{label}",
            "file_path": self.file_path,
            "name": self.name,
            "parent_name": "",
            "chunk_type": self.kind or self.source or "ast",
            "language": _language_from_path(self.file_path),
            "start_line": self.start_line or self.line,
            "end_line": self.end_line or self.line,
            "lines": lines,
            "code": self.code,
            "token_estimate": max(1, (len(self.code or "") + 3) // 4),
            "score": self.score,
            "citation": f"{self.file_path}:{lines} ({label})",
            "why_included": f"ast_index_{self.source or 'match'}",
        }


def is_available() -> bool:
    return shutil.which("ast-index") is not None


def retrieve_context(repo_path: str, query: str, limit: int = 12, include_usages: bool = True) -> list[dict[str, Any]]:
    """Return AST-derived source candidates for a developer query."""
    root = Path(repo_path)
    if not root.exists() or not is_available():
        return []

    terms = _query_terms(query)
    if not terms:
        return []

    hits: list[AstIndexHit] = []
    per_term_limit = max(3, min(10, limit))
    for term_index, term in enumerate(terms[:6]):
        term_bonus = max(0.0, 6.0 - term_index)
        hits.extend(_with_score_bonus(_symbol_hits(root, term, per_term_limit), term_bonus))
        hits.extend(_with_score_bonus(_search_hits(root, term, per_term_limit), term_bonus))
        if include_usages and len(hits) < limit * 2:
            hits.extend(_with_score_bonus(_usage_hits(root, term, max(3, per_term_limit // 2)), term_bonus))

    deduped: dict[tuple[str, int, str, str], AstIndexHit] = {}
    for hit in hits:
        if not hit.file_path or hit.line <= 0:
            continue
        _attach_code(root, hit)
        if not hit.code.strip():
            continue
        key = (hit.file_path, hit.start_line or hit.line, hit.name, hit.source)
        previous = deduped.get(key)
        if previous is None or hit.score > previous.score:
            deduped[key] = hit

    ranked = _rank_unique_hits(list(deduped.values()), limit)
    return [hit.to_context_candidate() for hit in ranked]


def resolve_symbols(
    repo_path: str,
    symbols: list[str],
    definitions_limit: int = 20,
    usages_limit: int = 20,
) -> dict[str, list[dict[str, Any]]]:
    """Resolve exact symbol definitions and usages using ast-index."""
    root = Path(repo_path)
    if not root.exists() or not is_available():
        return {"definitions": [], "usages": []}

    definitions: list[AstIndexHit] = []
    usages: list[AstIndexHit] = []
    for symbol in symbols:
        clean = symbol.strip()
        if not clean:
            continue
        definitions.extend(_symbol_hits(root, clean, definitions_limit))
        usages.extend(_usage_hits(root, clean, usages_limit))

    for hit in [*definitions, *usages]:
        _attach_code(root, hit)

    resolved_definitions = _rank_unique_hits(
        [hit for hit in definitions if hit.code.strip()],
        definitions_limit,
    )
    resolved_usages = _rank_unique_hits(
        [hit for hit in usages if hit.code.strip()],
        usages_limit,
    )
    return {
        "definitions": [hit.to_context_candidate() for hit in resolved_definitions],
        "usages": [hit.to_context_candidate() for hit in resolved_usages],
    }


def call_tree(repo_path: str, symbol: str, limit: int = 50) -> list[dict[str, Any]]:
    """Return caller tree nodes for ``symbol`` with compact source slices."""
    root = Path(repo_path)
    if not root.exists() or not is_available() or not symbol.strip():
        return []
    text = _run_text(
        root,
        ["call-tree", "--limit", str(limit), symbol.strip()],
        timeout=12.0,
    )
    if not text:
        return []

    hits: list[tuple[int, AstIndexHit]] = []
    for line in text.splitlines():
        match = _CALL_TREE_LINE_RE.match(line)
        if not match:
            continue
        depth = max(0, len(match.group("indent")) // 2)
        hit = AstIndexHit(
            file_path=match.group("path"),
            line=int(match.group("line")),
            name=match.group("name").strip(),
            kind="caller",
            source="call_tree",
            score=max(1.0, 10.0 - depth),
        )
        _attach_code(root, hit)
        if hit.code.strip():
            hits.append((depth, hit))

    ranked: list[dict[str, Any]] = []
    seen: list[AstIndexHit] = []
    for depth, hit in hits:
        if any(_overlaps_existing(hit, existing) for existing in seen):
            continue
        seen.append(hit)
        item = hit.to_context_candidate()
        item["depth"] = depth
        ranked.append(item)
        if len(ranked) >= limit:
            break
    return ranked


def callers(repo_path: str, symbol: str, limit: int = 50) -> list[dict[str, Any]]:
    """Return one-hop callers for ``symbol`` with compact source slices."""
    root = Path(repo_path)
    if not root.exists() or not is_available() or not symbol.strip():
        return []
    text = _run_text(
        root,
        ["callers", "--limit", str(limit), symbol.strip()],
        timeout=12.0,
    )
    if not text:
        return []

    hits: list[AstIndexHit] = []
    current_path = ""
    for line in text.splitlines():
        file_match = _CALLERS_FILE_RE.match(line)
        if file_match:
            current_path = file_match.group("path").strip()
            continue
        line_match = _CALLERS_LINE_RE.match(line)
        if not line_match or not current_path:
            continue
        hit = AstIndexHit(
            file_path=current_path,
            line=int(line_match.group("line")),
            name=symbol.strip(),
            kind="caller",
            context=line_match.group("context").strip(),
            source="callers",
            score=8.0,
        )
        _attach_code(root, hit)
        if hit.code.strip():
            hits.append(hit)

    return [hit.to_context_candidate() for hit in _rank_unique_hits(hits, limit)]


def understand_project(repo_path: str, query: str, max_modules: int = 8, max_slices: int = 8) -> dict[str, Any]:
    """Return a compact project-understanding map for a topic."""
    root = Path(repo_path)
    if not root.exists() or not is_available():
        return {"modules": [], "symbols": [], "slices": []}

    terms = _query_terms(query)
    map_data = _run_json(root, ["map", "--format", "json"], timeout=15.0)
    modules = _rank_modules(map_data.get("groups", []) if isinstance(map_data, dict) else [], terms, max_modules)

    module_prefixes = [str(m.get("path", "")) for m in modules if m.get("path")]
    symbol_candidates: list[tuple[float, dict[str, Any]]] = []
    seen_symbols: set[tuple[str, str, int]] = set()
    search_terms = sorted(
        terms,
        key=lambda t: (t.lower() not in _BROAD_PROJECT_TERMS, any(c.isupper() for c in t[1:]), len(t)),
        reverse=True,
    )
    for term in search_terms[:8]:
        data = _run_json(root, ["search", "--format", "json", "--limit", "10", term])
        if not isinstance(data, dict):
            continue
        for row in data.get("symbols") or []:
            if not isinstance(row, dict):
                continue
            key = (str(row.get("path", "")), str(row.get("name", "")), int(row.get("line") or 0))
            if key in seen_symbols:
                continue
            seen_symbols.add(key)
            symbol = {
                "name": row.get("name", ""),
                "kind": row.get("kind", ""),
                "path": row.get("path", ""),
                "line": row.get("line", 0),
                "signature": row.get("signature", ""),
            }
            symbol_candidates.append((_symbol_topic_score(symbol, terms, module_prefixes), symbol))

    symbol_candidates.sort(key=lambda item: item[0], reverse=True)
    symbols = [symbol for score, symbol in symbol_candidates if score > 0][: max_slices * 2]
    slices = retrieve_context(repo_path, query, limit=max_slices)
    return {"modules": modules, "symbols": symbols, "slices": slices}


def _rank_unique_hits(hits: list[AstIndexHit], limit: int) -> list[AstIndexHit]:
    ranked: list[AstIndexHit] = []
    for hit in sorted(hits, key=_hit_rank_score, reverse=True):
        if any(_overlaps_existing(hit, existing) for existing in ranked):
            continue
        ranked.append(hit)
        if len(ranked) >= limit:
            break
    return ranked


def _query_terms(query: str) -> list[str]:
    raw_terms = _IDENT_RE.findall(query or "")
    seen: set[str] = set()
    specific: list[str] = []
    natural: list[str] = []
    broad: list[str] = []
    for term in raw_terms:
        if len(term) < 4:
            continue
        low = term.lower()
        if low in seen:
            continue
        seen.add(low)
        if low in _BROAD_PROJECT_TERMS:
            broad.append(term)
        elif _looks_like_identifier(term):
            specific.append(term)
        else:
            natural.append(term)
    # Prefer code identifiers but preserve caller-supplied order inside each
    # group. The first identifier is usually the desired navigation anchor.
    return [*specific, *natural, *broad][:10]


def _looks_like_identifier(term: str) -> bool:
    return (
        any(c.isupper() for c in term)
        or "_" in term
        or term.endswith(("Service", "Presenter", "Interactor", "Fragment", "Component"))
    )


def _with_score_bonus(hits: list[AstIndexHit], bonus: float) -> list[AstIndexHit]:
    for hit in hits:
        hit.score += bonus
    return hits


def _hit_rank_score(hit: AstIndexHit) -> float:
    line_count = max(1, (hit.end_line or hit.line) - (hit.start_line or hit.line) + 1)
    score = hit.score + min(2.0, line_count / 20.0)
    signature = hit.signature.strip()
    code = hit.code.strip()
    if signature.startswith("override ") or code.startswith("override "):
        score += 1.5
    if line_count <= 1 and "{" not in code and "=" not in code:
        score -= 1.0
    if "@Deprecated" in code:
        score -= 0.75
    return score


def _run_json(root: Path, args: list[str], timeout: float = 8.0) -> Any | None:
    try:
        proc = subprocess.run(
            ["ast-index", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.debug("ast_index_command_failed", args=args, error=str(e))
        return None
    if proc.returncode != 0:
        logger.debug(
            "ast_index_nonzero",
            args=args,
            returncode=proc.returncode,
            stderr=proc.stderr[-500:],
        )
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        logger.debug("ast_index_json_parse_failed", args=args, stdout=proc.stdout[:500])
        return None


def _run_text(root: Path, args: list[str], timeout: float = 8.0) -> str:
    try:
        proc = subprocess.run(
            ["ast-index", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.debug("ast_index_text_command_failed", args=args, error=str(e))
        return ""
    if proc.returncode != 0:
        logger.debug(
            "ast_index_text_nonzero",
            args=args,
            returncode=proc.returncode,
            stderr=proc.stderr[-500:],
        )
        return ""
    return proc.stdout


def _rank_modules(groups: list[Any], terms: list[str], limit: int) -> list[dict[str, Any]]:
    ranked: list[tuple[float, dict[str, Any]]] = []
    lowered = [t.lower() for t in terms]
    for group in groups:
        if not isinstance(group, dict):
            continue
        path = str(group.get("path", ""))
        path_low = path.lower()
        score = 0.0
        for term in lowered:
            if term in path_low:
                score += 5.0
        # Keep a small prior for important-looking, non-tiny modules.
        file_count = int(group.get("file_count") or 0)
        score += min(file_count, 200) / 200.0
        if score <= 0:
            continue
        ranked.append((
            score,
            {
                "path": path,
                "file_count": file_count,
                "kinds": group.get("kinds", {}) or {},
                "score": round(score, 3),
            },
        ))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [item for _, item in ranked[:limit]]


def _symbol_topic_score(symbol: dict[str, Any], terms: list[str], module_prefixes: list[str]) -> float:
    haystack = " ".join(
        str(symbol.get(k, ""))
        for k in ("name", "signature", "path", "kind")
    ).lower()
    score = 0.0
    for term in terms:
        low = term.lower()
        if low in haystack:
            score += 3.0 if low not in _BROAD_PROJECT_TERMS else 0.8
    path = str(symbol.get("path", ""))
    if module_prefixes and any(path.startswith(prefix) for prefix in module_prefixes):
        score += 2.0
    kind = str(symbol.get("kind", ""))
    if kind in ("class", "interface", "function"):
        score += 0.5
    return score


def _symbol_hits(root: Path, term: str, limit: int) -> list[AstIndexHit]:
    data = _run_json(root, ["symbol", "--format", "json", "--limit", str(limit), term])
    if not isinstance(data, list):
        return []
    hits = []
    for row in data:
        if not isinstance(row, dict):
            continue
        hits.append(AstIndexHit(
            file_path=str(row.get("path", "")),
            line=int(row.get("line") or 0),
            name=str(row.get("name", term)),
            kind=str(row.get("kind", "symbol")),
            signature=str(row.get("signature", "")),
            source="symbol",
            score=12.0 if str(row.get("name", "")).lower() == term.lower() else 9.0,
        ))
    return hits


def _search_hits(root: Path, term: str, limit: int) -> list[AstIndexHit]:
    data = _run_json(root, ["search", "--format", "json", "--limit", str(limit), term])
    if not isinstance(data, dict):
        return []
    hits: list[AstIndexHit] = []
    for row in data.get("symbols") or []:
        if not isinstance(row, dict):
            continue
        hits.append(AstIndexHit(
            file_path=str(row.get("path", "")),
            line=int(row.get("line") or 0),
            name=str(row.get("name", term)),
            kind=str(row.get("kind", "symbol")),
            signature=str(row.get("signature", "")),
            source="search_symbol",
            score=8.0,
        ))
    for row in data.get("content_matches") or []:
        if not isinstance(row, dict):
            continue
        hits.append(AstIndexHit(
            file_path=str(row.get("path", "")),
            line=int(row.get("line") or 0),
            name=term,
            kind="usage",
            context=str(row.get("content", "")),
            source="search_content",
            score=5.0,
        ))
    return hits


def _usage_hits(root: Path, term: str, limit: int) -> list[AstIndexHit]:
    data = _run_json(root, ["usages", "--format", "json", "--limit", str(limit), term])
    if not isinstance(data, list):
        return []
    hits = []
    word_pattern = re.compile(rf"\b{re.escape(term)}\b")
    for row in data:
        if not isinstance(row, dict):
            continue
        context = str(row.get("context", ""))
        if not word_pattern.search(context):
            continue
        hits.append(AstIndexHit(
            file_path=str(row.get("path", "")),
            line=int(row.get("line") or 0),
            name=str(row.get("name", term)),
            kind="usage",
            context=context,
            source="usage",
            score=4.0,
        ))
    return hits



def _attach_code(root: Path, hit: AstIndexHit) -> None:
    path = (root / hit.file_path).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    if not lines:
        return

    if hit.source in ("symbol", "search_symbol") and hit.kind != "property":
        start, end = _symbol_bounds(lines, hit.line)
    else:
        start, end = _usage_bounds(lines, hit.line)
    hit.start_line = start
    hit.end_line = end
    hit.code = "\n".join(lines[start - 1:end])


def _window_bounds(lines: list[str], line: int, radius: int = 8) -> tuple[int, int]:
    start = max(1, line - radius)
    end = min(len(lines), line + radius)
    return start, end


def _usage_bounds(lines: list[str], line: int) -> tuple[int, int]:
    idx = max(0, min(len(lines) - 1, line - 1))
    for pos in range(idx, max(-1, idx - 40), -1):
        stripped = lines[pos].strip()
        if (
            stripped.startswith("fun ")
            or stripped.startswith("def ")
            or stripped.startswith("function ")
            or stripped.startswith("class ")
            or stripped.startswith("interface ")
            or stripped.startswith("object ")
        ):
            return _symbol_bounds(lines, pos + 1, max_lines=80)
    return _window_bounds(lines, line)


def _overlaps_existing(candidate: AstIndexHit, existing: AstIndexHit, threshold: float = 0.5) -> bool:
    if candidate.file_path != existing.file_path:
        return False
    c_start = candidate.start_line or candidate.line
    c_end = candidate.end_line or candidate.line
    e_start = existing.start_line or existing.line
    e_end = existing.end_line or existing.line
    overlap = max(0, min(c_end, e_end) - max(c_start, e_start) + 1)
    shorter = max(1, min(c_end - c_start + 1, e_end - e_start + 1))
    return overlap / shorter >= threshold


def _symbol_bounds(lines: list[str], line: int, max_lines: int = 90) -> tuple[int, int]:
    idx = max(0, min(len(lines) - 1, line - 1))
    start = idx
    while start > 0 and idx - start < 6:
        prev = lines[start - 1].strip()
        if prev.startswith("@") or prev.startswith("//") or prev.startswith("/*") or prev.startswith("*"):
            start -= 1
            continue
        if not prev:
            break
        break

    brace_balance = 0
    saw_open = False
    end_limit = min(len(lines), idx + max_lines)
    for pos in range(idx, end_limit):
        stripped = lines[pos].strip()
        brace_balance += _brace_delta(lines[pos])
        if "{" in lines[pos]:
            saw_open = True
        if saw_open and brace_balance <= 0 and pos > idx:
            return start + 1, pos + 1
        if not saw_open and pos > idx:
            if not stripped:
                return start + 1, pos
            if _SYMBOL_LINE_RE.search(stripped):
                return start + 1, pos
    return start + 1, min(len(lines), end_limit)


def _brace_delta(line: str) -> int:
    # Good enough for bounded slicing; this is only a stop heuristic.
    in_string = False
    quote = ""
    delta = 0
    i = 0
    while i < len(line):
        ch = line[i]
        if in_string:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                in_string = False
        elif ch in ("'", '"'):
            in_string = True
            quote = ch
        elif ch == "{":
            delta += 1
        elif ch == "}":
            delta -= 1
        i += 1
    return delta


def _language_from_path(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return {
        ".kt": "kotlin",
        ".kts": "kotlin",
        ".java": "java",
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".xml": "xml",
    }.get(suffix, suffix.lstrip(".") or "unknown")
