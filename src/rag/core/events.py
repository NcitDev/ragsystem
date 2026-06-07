"""Generate lightweight event catalogs for documentation indexing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

EVENT_CONSTANT_RE = re.compile(r"\b(?:const\s+val|val)\s+([A-Z][A-Z0-9_]{3,})\s*=\s*\"([^\"]+)\"")
EVENT_METHOD_RE = re.compile(
    r"\bfun\s+([a-z][A-Za-z0-9_]*(?:Event|Analytics|Finished|Failed|Start|Stop|Created|Polling)[A-Za-z0-9_]*)\s*\("
)
TRACK_METHOD_RE = re.compile(r"\bfun\s+(track[A-Z][A-Za-z0-9_]*)\s*\(")


@dataclass(frozen=True)
class EventDocEntry:
    """A discovered analytics/event symbol with location and search text."""

    kind: str
    name: str
    value: str
    file_path: str
    line: int


def _humanize_identifier(value: str) -> str:
    if value.isupper() and "_" in value:
        return " ".join(part.lower() for part in value.split("_") if part)
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", value)
    spaced = spaced.replace("_", " ").replace("-", " ")
    return " ".join(part.lower() for part in spaced.split())


def discover_event_entries(repo_path: str | Path) -> list[EventDocEntry]:
    """Discover event constants and analytics helper/factory methods."""
    root = Path(repo_path).resolve()
    entries: list[EventDocEntry] = []
    if not root.exists():
        return entries

    for path in sorted(root.rglob("*.kt")):
        rel = path.relative_to(root).as_posix()
        lowered = rel.lower()
        if "build/" in lowered or "/generated/" in lowered:
            continue
        if not any(term in lowered for term in ("analytic", "event", "payment", "checkout", "order")):
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for index, line in enumerate(lines, 1):
            for match in EVENT_CONSTANT_RE.finditer(line):
                entries.append(
                    EventDocEntry(
                        kind="constant",
                        name=match.group(1),
                        value=match.group(2),
                        file_path=rel,
                        line=index,
                    )
                )
            for regex in (EVENT_METHOD_RE, TRACK_METHOD_RE):
                for match in regex.finditer(line):
                    name = match.group(1)
                    entries.append(
                        EventDocEntry(
                            kind="method",
                            name=name,
                            value=_humanize_identifier(name),
                            file_path=rel,
                            line=index,
                        )
                    )

    seen: set[tuple[str, str, str, int]] = set()
    deduped: list[EventDocEntry] = []
    for entry in entries:
        key = (entry.kind, entry.name, entry.file_path, entry.line)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


def render_event_catalog(repo_name: str, entries: list[EventDocEntry]) -> str:
    """Render discovered events as Markdown suitable for doc indexing."""
    lines = [
        f"# {repo_name} Analytics And Event Catalog",
        "",
        "This generated catalog helps repo-agent map product wording to analytics/event code.",
        "Use it as documentation context together with exact code slices.",
        "",
    ]
    by_area: dict[str, list[EventDocEntry]] = {}
    for entry in entries:
        area = "payment" if "payment" in entry.file_path.lower() or "payment" in entry.name.lower() else "order"
        if "analytics" in entry.file_path.lower() or "analytic" in entry.name.lower():
            area = "analytics"
        by_area.setdefault(area, []).append(entry)

    for area, area_entries in sorted(by_area.items()):
        lines.extend([f"## {area.title()}", ""])
        for entry in area_entries:
            human = _humanize_identifier(entry.name)
            value_text = f" Event value `{entry.value}`." if entry.value and entry.value != human else ""
            lines.append(
                f"- `{entry.name}` ({entry.kind}) at `{entry.file_path}:{entry.line}`."
                f"{value_text} Search terms: {human}; {entry.value}; {entry.file_path}."
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_event_catalog(repo_path: str | Path, output_path: str | Path, repo_name: str = "repo") -> Path:
    """Discover and write a generated event catalog Markdown file."""
    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    entries = discover_event_entries(repo_path)
    output.write_text(render_event_catalog(repo_name, entries), encoding="utf-8")
    return output
