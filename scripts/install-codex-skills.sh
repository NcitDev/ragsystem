#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS_DIR="$ROOT/skills"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
TARGET_DIR="$CODEX_HOME/skills"

if [[ ! -d "$SKILLS_DIR" ]]; then
  echo "No skills directory found at $SKILLS_DIR" >&2
  exit 1
fi

mkdir -p "$TARGET_DIR"

installed=0
for skill in "$SKILLS_DIR"/*; do
  [[ -d "$skill" ]] || continue
  [[ -f "$skill/SKILL.md" ]] || continue
  name="$(basename "$skill")"
  rm -rf "$TARGET_DIR/$name"
  cp -R "$skill" "$TARGET_DIR/$name"
  installed=$((installed + 1))
  echo "Installed $name -> $TARGET_DIR/$name"
done

echo "Installed $installed Codex skill(s)."
