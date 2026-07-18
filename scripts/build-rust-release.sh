#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TARGET=${1:-$(rustc -vV | awk '/host:/ {print $2}')}
OUT="$ROOT/dist/$TARGET"

mkdir -p "$OUT"
cargo build --manifest-path "$ROOT/Cargo.toml" --release --locked --target "$TARGET" -p rag-app
cp "$ROOT/target/$TARGET/release/rag-rs" "$OUT/rag-rs"

if command -v shasum >/dev/null 2>&1; then
  (cd "$OUT" && shasum -a 256 rag-rs > SHA256SUMS)
else
  (cd "$OUT" && sha256sum rag-rs > SHA256SUMS)
fi

# The smoke test clears Python-specific environment and only executes the artifact.
env -i PATH="/usr/bin:/bin" "$OUT/rag-rs" --version
printf 'release artifact: %s\n' "$OUT/rag-rs"
