"""Claude Code integration — generate slash commands and install hooks.

Provides two integration approaches:
1. A custom slash command (/rag <query>) via a markdown file in ~/.claude/commands/
2. A hook in .claude/settings.json for automatic RAG lookups
"""

from __future__ import annotations

import json
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

_SLASH_COMMAND_TEMPLATE = """\
Search the indexed codebase using the RAG system.

Usage: /rag <query>

When the user invokes this command, do the following:

1. Run the shell command below, replacing $ARGUMENTS with the user's query:

```bash
rag search "$ARGUMENTS" --top-k 5
```

2. Parse the output. Each result contains:
   - File path and line range
   - Chunk type (function, class, etc.) and name
   - Relevance score
   - A code snippet

3. Use the returned code snippets as context to answer the user's question.
   - Prefer results with higher relevance scores.
   - If no results are found, tell the user and suggest they run `rag index .` first.
   - Cite file paths and line numbers when referencing results.
"""

_HOOK_ENTRY = {
    "type": "command",
    "pattern": "rag search",
    "command": "rag search",
}


def generate_slash_command(output_dir: str | None = None) -> str:
    """Generate a Claude Code custom slash command for RAG search.

    Creates a file at ``~/.claude/commands/rag.md`` (or *output_dir*/rag.md)
    that enables ``/rag <query>`` inside Claude Code.

    Parameters
    ----------
    output_dir:
        Directory to write the command file into.  Defaults to
        ``~/.claude/commands``.

    Returns
    -------
    str
        Absolute path to the created file.
    """
    target_dir = Path(output_dir) if output_dir else Path.home() / ".claude" / "commands"
    target_dir.mkdir(parents=True, exist_ok=True)

    command_file = target_dir / "rag.md"
    command_file.write_text(_SLASH_COMMAND_TEMPLATE)

    log.info(
        "slash_command_created",
        path=str(command_file),
    )
    return str(command_file)


def install_claude_code_hook() -> str:
    """Install a Claude Code hook that enables RAG search integration.

    Adds a hook entry to ``~/.claude/settings.json`` so that Claude Code
    recognises the ``rag search`` command pattern.

    Returns
    -------
    str
        Human-readable status message.
    """
    settings_path = Path.home() / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing settings or start fresh.
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text())
        except (json.JSONDecodeError, OSError):
            log.warning("settings_parse_failed", path=str(settings_path))
            settings = {}
    else:
        settings = {}

    hooks: list[dict] = settings.setdefault("hooks", [])

    # Avoid duplicates — check if we already installed this hook.
    already_installed = any(
        h.get("pattern") == _HOOK_ENTRY["pattern"] for h in hooks
    )
    if already_installed:
        msg = f"RAG hook already present in {settings_path}"
        log.info("hook_already_installed", path=str(settings_path))
        return msg

    hooks.append(_HOOK_ENTRY)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")

    msg = f"RAG hook installed in {settings_path}"
    log.info("hook_installed", path=str(settings_path))
    return msg
