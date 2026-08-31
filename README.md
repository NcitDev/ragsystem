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

Three required, one required for symbol navigation:

1. **`rag`** — the single ~30 MB binary (daemon + CLI + TUI).
2. **Qdrant** — vector database. `qdrant.mode = "server"` connects to a Docker
   container (`rag qdrant-up` manages `rag-qdrant` on `127.0.0.1:6333`);
   `qdrant.mode = "embedded"` makes the daemon host a pinned Qdrant binary
   itself (auto-downloaded to `~/.rag/bin`), no Docker required.
3. **Ollama** — local model server for embeddings (`qwen3-embedding`) and,
   optionally, the LLM planner and `/ask` generation (`qwen3:8b`).
4. **`ast-index`** — an external CLI the daemon shells out to for every
   symbol-exact answer (`npm install -g @ast-index/cli`; a native binary
   behind a Node launcher, so Node.js must be on `PATH`). It backs `/resolve`,
   `/graph/node|callers|callees|impact`, `/call-tree`, `/context-pack` and the
   structural stage of `/smart-search`. **Without it those routes return empty
   results rather than an error** — dense and lexical search are unaffected,
   but navigation answers silently go blank, which looks like a broken index.
   The daemon's `/stack` endpoint reports whether it is present, via its
   `ast_index` service card — that is what `rag tui` and the web dashboard
   render. (`rag diagnose` is *not* a working check: the route still returns a
   static `{"status": "degraded", "checks": []}` stub.)

## Install

```bash
# Prebuilt binary (see scripts/build-rust-release.sh to build a release):
install -m 0755 dist/<target>/rag-rs ~/.local/bin/rag
```

Building from source needs a Rust toolchain only:

```bash
cargo build --release -p rag-app      # produces target/release/rag-rs
```

## 30-second quickstart

```bash
ollama pull qwen3-embedding                # embeddings — this is the packaged default
ollama pull qwen3:8b                       # planner + /ask generation (optional)

rag qdrant-up                 # start the Qdrant container (or set qdrant.mode=embedded)
rag service install           # supervised daemon (systemd user / launchd)
rag index . --name myrepo     # index the current directory
rag search "auth middleware" --repo myrepo
rag tui                       # open the stack dashboard
```

First `rag start` bootstraps `~/.rag` (auth token with 0600 perms, default
`config.toml`). The web dashboard is served at `http://127.0.0.1:7890/`.

> **Shared machines:** `GET /` cannot be authenticated — a browser has no way
> to present a bearer token on its first request — so the page embeds a
> credential that any local process able to reach the loopback port can read.
> It is a per-process token that dies with the daemon, never the durable
> `~/.rag/token`, but on a multi-user host set `server.dashboard = false` and
> use the CLI (over an SSH tunnel if remote) instead.

> **Embedding model:** the packaged default is
> `embeddings.model = "qwen3-embedding:latest"` with `embeddings.dim = 4096`,
> so pulling `qwen3-embedding` is all a fresh install needs. If you change the
> model, it must stay an exact tag that `ollama list` shows — a HuggingFace
> repo path (`Qwen/Qwen3-Embedding-4B`) will never be matched, and the daemon
> reports `ollama: unavailable` even though Ollama is fine. `dim` must equal
> the width that model returns (`qwen3-embedding` is 4096 for the default/8b
> tag, 2560 for `:4b`, 1024 for `:0.6b`) — collections are created with that
> size at first index, so a mismatch corrupts an index rather than erroring.
> `GET /health/detail` lists the tags Ollama is actually serving.

## AST navigation

Symbol-exact features (`rag resolve`, `rag callers`, `rag callees`,
`rag impact`, `rag call-tree`, `rag context-pack`, `rag smart-search`
structural links) shell out to the external `ast-index` CLI — see runtime
dependency 4 above. Install it and build its index once per repo:

```bash
npm install -g @ast-index/cli     # requires Node.js on PATH
cd <repo> && ast-index rebuild
```

Without it, `rag resolve` / `callers` / `callees` / `impact` return **empty
results, not an error**, and `smart-search` falls back to its dense/lexical
stages only. Check `/stack` (or the `AST-INDEX` card in `rag tui` / the web
dashboard) before concluding the index is broken.

## Architecture

A Cargo workspace producing one `rag` binary:

| Crate | Responsibility |
| --- | --- |
| `rag-app` | binary: CLI (Clap), TUI (Ratatui), service + Docker management |
| `rag-server` | Axum HTTP daemon, retrieval pipeline, indexer, web dashboard |
| `rag-retrieval` | scoring, sanity filter, AST index bridge, repo-agent |
| `rag-index` | tree-sitter chunking, enrichment, discovery, lexical index |
| `rag-agent` | search planner (LLM via Rig + heuristic fallback), agy and Codex CLI adapters |
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
cargo clippy --workspace --all-targets -- -D warnings     # lint
cargo fmt --check                                         # format
```

## Migration note

This project was ported from Python to Rust; the parity audit and benchmark
history are in `docs/python-parity-audit.md`,
`docs/benchmark_full_matrix/summary.md`, and `docs/rust-migration-plan.md`. The
Rust daemon matches or beats the former Python implementation on every
retrieval mode at 1.5–3× lower latency, ~5× less memory, and a 16× faster cold
start. No Python is required at build or run time.
