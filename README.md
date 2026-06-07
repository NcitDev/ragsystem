# rag

## What it is

Standalone code-search RAG: a headless FastAPI daemon (embedded Qdrant vector store, Qwen3 dense embeddings via Ollama, Agno query planner) plus a separate read-only Textual TUI dashboard that connects to the daemon over HTTP. Retrieval is dense vector search, code-aware chunking via tree-sitter (3-tier file/class/function) for Python, TypeScript/JavaScript, Go, Rust, Java, Kotlin, C/C++, and Dart/Flutter, and optional LSP enrichment performed at index time only (zero query-path overhead).

The daemon is the supervised component: it stays up if the TUI crashes, and `rag service install` registers it as a launchd agent on macOS so it auto-starts on login and restarts on crash.

## Install

Requires Python 3.11+.

```bash
pip install -e .
```

Ollama is **required** for embeddings (Qwen3-Embedding) and recommended for the planner agent (`qwen3:8b`). The previous FastEmbed ONNX fallback and the cross-encoder reranker were removed; if Ollama is unavailable the daemon will fail to start. The planner agent degrades to keyword heuristics if its model isn't pulled.

Install project-owned Codex skills:

```bash
rag install-agent codex
```

## 30-second quickstart

```bash
ollama pull qwen3-embedding   # optional but recommended
rag init .                    # copy default config, start daemon, index cwd
rag search "auth middleware"
rag tui                       # open the dashboard (read-only, optional)

# Auto-start the daemon on login (macOS):
rag service install
```

## CLI cheat sheet

| Command | Description |
| --- | --- |
| `rag init [path]` | Initialize: create config, start daemon, index current directory. |
| `rag install-agent codex` | Install project-owned Codex skills for repo-agent workflows. |
| `rag start [--tui] [--watch]` | Start the headless daemon (HTTP server on `:7890`). `--tui` also spawns the TUI in the foreground. `--headless`/`--no-tui` are accepted aliases. |
| `rag tui` | Launch the read-only TUI dashboard against a running daemon. |
| `rag service install` / `rag service uninstall` / `rag service status` | Register the daemon as a launchd agent (macOS) so it auto-starts on login and restarts on crash. |
| `rag search QUERY [--top-k N] [--repo NAME]` | Search the indexed codebase. (`--no-rerank` is accepted but ignored — the reranker was removed.) |
| `rag files --repo NAME [QUERY]` | List indexed files from the exact local code index. |
| `rag node SYMBOL --repo NAME` | Show exact definitions and usages for a symbol. |
| `rag callers SYMBOL --repo NAME` / `rag callees SYMBOL --repo NAME` | Show caller edges and heuristic callee candidates. |
| `rag impact SYMBOL --repo NAME` | Estimate affected files, callers, usages, tests, and risks for a symbol change. |
| `rag affected --repo NAME [--since REF]` | Estimate affected indexed files/tests from a git diff or explicit files. |
| `rag index [path] [--full] [--lang L] [--name NAME]` | Index a repository (incremental by default). |
| `rag status` | Show daemon, embedder, and collection status. |
| `rag overview` | Codebase overview: language distribution, patterns, complexity. |
| `rag diff QUERY [--since REF] [--path P]` | Search within recent git changes. |
| `rag diagnose` | Full health check: daemon, Ollama, LSP servers, cache. |
| `rag verify [path]` | Check index integrity (orphans, duplicates). |
| `rag repair [path]` | Remove orphaned chunks from the index. |
| `rag repos` | List registered repositories. |
| `rag export OUTPUT [--collection C]` | Export indexed data to JSONL. |
| `rag import INPUT [--collection C]` | Import data from JSONL. |
| `rag install-claude` | Install the `/rag` Claude Code slash command. |
| `rag plugins` | List installed YAML plugin manifests. |
| `rag collections list\|delete [name]` | Manage Qdrant collections. |
| `rag config` | Open the config file in `$EDITOR`. |

## Architecture

Headless daemon (FastAPI on `127.0.0.1:7890`) is the supervised process. CLI subcommands and the Textual TUI (`rag tui`) are thin HTTP clients — a TUI crash never affects the daemon. See [`docs/ADR/001-full-stack-decision.md`](docs/ADR/001-full-stack-decision.md) for the full design (note: ADR-001 originally described a single-process daemon; the TUI was split out as a read-only client when launchd supervision was added).

## Troubleshooting

Run `rag diagnose` first — it reports daemon health, Ollama reachability and required models, LSP server detection (with install hints for missing ones), and cache stats. For index issues, run `rag verify` to detect orphaned or duplicate chunks, then `rag repair` to clean them up.
