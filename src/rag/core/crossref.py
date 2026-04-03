"""Cross code-docs relationship detection.

When indexing markdown docs, detects references to code symbols (function names,
class names, file paths) and stores them as metadata for cross-modal retrieval.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

logger = structlog.get_logger()

# Patterns that identify code references in documentation
CODE_REF_PATTERNS = [
    # Backtick-wrapped identifiers: `functionName`, `ClassName`
    re.compile(r"`([A-Za-z_]\w+(?:\.\w+)*)`"),
    # File paths: src/auth/middleware.py, ./config.toml
    re.compile(r"(?:^|\s)((?:\./|src/|lib/|app/)?[\w/]+\.(?:py|ts|js|go|rs|java|kt|c|cpp|h|hpp))\b"),
    # CamelCase words (likely class names)
    re.compile(r"\b([A-Z][a-z]+(?:[A-Z][a-z]+){1,})\b"),
    # snake_case function references in prose
    re.compile(r"\b([a-z_]\w*_\w+)\(\)"),
]


def extract_code_references(text: str) -> list[str]:
    """Extract code symbol references from documentation text."""
    refs: set[str] = set()
    for pattern in CODE_REF_PATTERNS:
        for match in pattern.finditer(text):
            ref = match.group(1)
            # Filter noise: skip very short or very common words
            if len(ref) >= 3 and ref.lower() not in _COMMON_WORDS:
                refs.add(ref)
    return sorted(refs)


def enrich_doc_chunk_with_code_refs(
    chunk_metadata: dict[str, Any],
    content: str,
    known_symbols: set[str] | None = None,
) -> None:
    """Add code_references field to a doc chunk's metadata.

    Args:
        chunk_metadata: Metadata dict to enrich (mutated in place)
        content: The doc chunk text content
        known_symbols: Optional set of known code symbols from the indexed codebase.
                      If provided, only references matching known symbols are kept.
    """
    refs = extract_code_references(content)

    if known_symbols:
        # Filter to only symbols that actually exist in the codebase
        refs = [r for r in refs if r in known_symbols or r.split(".")[-1] in known_symbols]

    if refs:
        chunk_metadata["code_references"] = refs[:20]  # Cap to avoid payload bloat
        logger.debug("code_refs_found", doc=chunk_metadata.get("file_path", ""), count=len(refs))


def collect_known_symbols(chunks: list[dict[str, Any]]) -> set[str]:
    """Build a set of known code symbols from indexed code chunks."""
    symbols: set[str] = set()
    for chunk in chunks:
        name = chunk.get("name", "")
        if name:
            symbols.add(name)
        parent = chunk.get("parent_name", "")
        if parent:
            symbols.add(parent)
            symbols.add(f"{parent}.{name}")
    return symbols


# Common English words to exclude from code reference detection
_COMMON_WORDS = {
    "the", "and", "for", "with", "this", "that", "from", "have", "been",
    "will", "can", "not", "are", "was", "were", "has", "had", "but",
    "all", "any", "each", "other", "some", "such", "than", "too",
    "very", "just", "also", "into", "over", "only", "new", "use",
    "may", "should", "would", "could", "about", "make", "like",
    "time", "way", "more", "these", "when", "which", "their",
    "see", "how", "its", "two", "then", "them", "one", "our",
    "out", "get", "set", "run", "add", "let", "var", "val",
}
