# rag

## What it is

Standalone code-search RAG, shipped as a **single Rust binary** — no Python
runtime, no virtualenv. A headless HTTP daemon owns a Qdrant vector store and
Qwen3 dense embeddings via Ollama; the CLI and the Ratatui **stack dashboard**
are thin clients to it. Retrieval is dense vector search over code-aware,
tree-sitter chunking (3-tier file/class/function) for Python,
TypeScript/JavaScript, Go, Rust, Java, Kotlin, C/C++, and Dart, plus symbol-
exact navigation via an AST index and graph tools.

The daemon is the supervised component: it stays up if the TUI crashes, and
`rag service install` registers it (systemd user unit on Linux, launchd agent
on macOS) so it auto-starts on login and restarts on crash.

## Runtime dependencies

Three things, nothing else:

1. **`rag`** — the single ~30 MB binary (daemon + CLI + TUI).
2. **Qdrant** — vector database. `qdrant.mode = "server"` connects to a Docker
   container (`rag qdrant-up` manages `rag-qdrant` on `127.0.0.1:6333`);
   `qdrant.mode = "embedded"` makes the daemon host a pinned Qdrant binary
   itself (downloaded to `~/.rag/bin` with a pinned official SHA-256), no
   Docker required. Embedded mode refuses to adopt an unknown process already
   using its port.
3. **Ollama** — local model server for embeddings (`qwen3-embedding`) and,
   optionally, the LLM planner and `/ask` generation (`qwen3:8b`).

## Install

```bash
# Prebuilt binary (see scripts/build-rust-release.sh to build a release):
install -m 0755 dist/<target>/rag-rs ~/.local/bin/rag
```

Building from source needs Rust 1.88 or newer (the workspace MSRV):

```bash
cargo build --release -p rag-app      # produces target/release/rag-rs
```

## 30-second quickstart

```bash
ollama pull qwen3-embedding:4b             # default embeddings model (dim 2560)
ollama pull qwen3:8b                       # planner + /ask generation (optional)

rag qdrant-up                 # start the Qdrant container (or set qdrant.mode=embedded)
rag service install           # supervised daemon (systemd user / launchd)
rag index . --name myrepo     # index the current directory
rag search "auth middleware" --repo myrepo
rag tui                       # open the stack dashboard
```

First `rag start` bootstraps `~/.rag` (auth token with 0600 perms, default
`config.toml`). The web dashboard is served at `http://127.0.0.1:7890/`.

> **Note:** `embeddings.model` must be an exact tag that `ollama list` shows
> (the default is `qwen3-embedding:4b`), and `embeddings.dim` must match that model's
> dimension — collections are created with that size at first index.

For a secured or hosted Qdrant, set `qdrant.url` to an `https://` URL and put
the key in the environment variable named by `qdrant.api_key_env` (default
`QDRANT_API_KEY`). The key is sent as Qdrant's `api-key` header and is never
stored in `config.toml`. Plaintext remote Qdrant URLs are rejected; loopback
HTTP remains supported for local development.
The same transport rule applies to `llm.ollama_url`, because embedding and
generation requests can contain private source context.

## Agent-safe context

`rag context-pack` returns deterministic slices with explicit slice, token,
and byte budgets, SHA-256 content digests, freshness, and per-slice provenance:

```bash
rag context-pack "authentication flow" --repo myrepo \
  --max-slices 8 --max-source-tokens 6000 --max-source-bytes 65536
curl http://127.0.0.1:7890/.well-known/rag-capabilities
```

The discovery document is public but exposes no indexed content or token. It
advertises the native HTTP/OpenAPI capability; this release does not claim MCP
or A2A protocol compatibility.

## AST navigation

Symbol-exact features (`rag resolve`, `rag callers`, `rag impact`,
`rag smart-search` structural links) use the external `ast-index` CLI. Build
its index once per repo:

```bash
cd <repo> && ast-index rebuild
```

Without it, those commands degrade to lexical/dense fallbacks.

## Architecture

A Cargo workspace producing one `rag` binary:

| Crate | Responsibility |
| --- | --- |
| `rag-app` | binary: CLI (Clap), TUI (Ratatui), service + Docker management |
| `rag-server` | Axum HTTP daemon, retrieval pipeline, indexer, web dashboard |
| `rag-retrieval` | scoring, sanity filter, AST index bridge, repo-agent |
| `rag-index` | tree-sitter chunking, enrichment, discovery, lexical index |
| `rag-agent` | search planner (LLM via Rig + heuristic fallback), agy adapter |
| `rag-services` | Ollama + Qdrant HTTP clients |
| `rag-storage` | SQLite (code index, cache, repo registry), migrations |
| `rag-config` | TOML config layering, paths, validation |
| `rag-contracts` | shared DTOs, SearchPlan, error envelope |

State lives in `~/.rag`: SQLite (`rag.db`, `repos.db`, `embed_cache.db`),
per-repo `state.json`, `config.toml`, and the auth token. The web dashboard is
embedded in the binary and served with the token injected.

## Development

```bash
cargo test --workspace                                    # all tests
cargo check --workspace --all-targets                     # compile every target
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo fmt --check                                         # format
```

Operators should use `GET /live` for process liveness and `GET /ready` for the
two-second Ollama/Qdrant readiness probe. `GET /health` remains available for
backward compatibility. Protected work is bounded by `server.max_in_flight`
(default 32); overload is rejected with HTTP 503 and `Retry-After: 1`. Every
response includes `x-request-id`.

Administrative mutations that are not safely implemented—live reload,
automatic repair, payload import, and Qdrant-to-SQLite backfill—return HTTP 501
instead of a success-shaped placeholder. Restart the supervised daemon to
reload settings; use verified reindexing for repair. The current payload JSONL
export omits vectors and is not a backup.
Export is additionally capped at one million records or 1 GiB and reports
truncation; `rag export` resolves relative output paths from the caller's
working directory. Vocabulary JSONL input is capped at 64 MiB. Source indexing
uses the configurable 4 MiB per-file default; AST attachment has a 4 MiB hard
limit.

## Migration note

This project was ported from Python to Rust; the parity audit and benchmark
history are in `docs/python-parity-audit.md`,
`docs/benchmark_full_matrix/summary.md`, and `docs/rust-migration-plan.md`.
Historical migration benchmark snapshots report parity or better retrieval
quality with lower latency and memory than the former Python implementation.
The production audit reran the same ten-scenario matrix against the audited
binary and preserved the saved Rust quality; see
`docs/benchmark_rust_production_audit/summary.md` for raw hashes, current
measurements, and limitations. These local results are not a release-wide
performance guarantee. No Python is required at build or run time.

Production-hardening findings, verified limitations, and migration notes are
in `docs/rust-production-audit.md`; product and deployment priorities are in
`docs/product-and-production-roadmap.md`.
