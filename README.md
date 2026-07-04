# rag

## What it is

Standalone code-search RAG: a headless FastAPI daemon (Qdrant vector store, Qwen3 dense embeddings via Ollama, Agno query planner) plus a separate Textual TUI **stack dashboard** that connects to the daemon over HTTP. Retrieval is dense vector search, code-aware chunking via tree-sitter (3-tier file/class/function) for Python, TypeScript/JavaScript, Go, Rust, Java, Kotlin, C/C++, and Dart/Flutter, and optional LSP enrichment performed at index time only (zero query-path overhead).

The daemon is the supervised component: it stays up if the TUI crashes, and `rag service install` registers it as a launchd agent on macOS so it auto-starts on login and restarts on crash.

The TUI is more than a daemon client — it monitors the whole stack (daemon, Ollama, Docker, Qdrant) directly, so it stays useful when things are down: each service card shows what's broken and how to fix it, and you can start the daemon (`D`) or the Qdrant container (`U`) from inside it. See [The TUI dashboard](#the-tui-dashboard).

## Install

Requires Python 3.11+.

```bash
pip install -e .
```

### Prerequisites

- **Ollama** is **required** for embeddings and recommended for the planner agent. The previous FastEmbed ONNX fallback and the cross-encoder reranker were removed; if Ollama is unavailable the daemon will fail to start. The planner agent degrades to keyword heuristics if its model isn't pulled.

  Pull an embedding model whose tag you will point the config at (any Qwen3-Embedding build works):

  ```bash
  ollama pull qwen3-embedding:4b-q8_0   # 2560-dim, matches the default embeddings.dim
  ollama pull qwen3:8b                  # planner / generation (optional but recommended)
  ```

  > **Important:** `embeddings.model` in your config must be an **exact tag that `ollama list` shows** (e.g. `qwen3-embedding:4b-q8_0`), not a HuggingFace-style name. If it doesn't match, the daemon crashes on startup with `server_init_failed` — see [Troubleshooting](#troubleshooting).

- **Docker** is required for the default Qdrant **server** mode (`compose.qdrant.yml` runs a `rag-qdrant` container). `rag init` / `rag qdrant-up` start it for you; the TUI can start it with the `U` key. To run without Docker, set `qdrant.mode = "embedded"` in config (note: payload-filter search is only fully supported in server mode).

Install project-owned Codex skills:

```bash
rag install-agent codex
```

## 30-second quickstart

```bash
ollama pull qwen3-embedding:4b-q8_0        # embeddings (see Prerequisites)
printf '[embeddings]\nmodel = "qwen3-embedding:4b-q8_0"\ndim = 2560\n' > ~/.rag/config.toml

rag qdrant-up                 # start the Qdrant container (Docker; server mode)
rag init .                    # start the daemon, index the current directory
rag search "auth middleware"
rag tui                       # open the stack dashboard

# Auto-start the daemon on login (macOS):
rag service install
```

`rag tui` works even if the daemon is down — it shows every service's status and lets you start the daemon (`D`) and Qdrant (`U`) from inside it.

## CLI cheat sheet

| Command | Description |
| --- | --- |
| `rag init [path]` | Initialize: create config, start daemon, index current directory. |
| `rag install-agent codex` | Install project-owned Codex skills for repo-agent workflows. |
| `rag start [--tui] [--watch]` | Start the headless daemon (HTTP server on `:7890`). `--tui` also spawns the TUI in the foreground. `--headless`/`--no-tui` are accepted aliases. |
| `rag tui` | Launch the TUI stack dashboard. Works even when the daemon is down (shows what's broken; press `D` to start the daemon, `U` to start Qdrant). |
| `rag web` | Open the browser dashboard (v2) served by the daemon at `/`. |
| `rag qdrant-up` / `rag qdrant-down` | Start/stop the local Qdrant Docker container (`compose.qdrant.yml`). |
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

## Configuration

Edit `~/.rag/config.toml` (or `config/default.toml` for repo defaults).

### Retrieval Agent LLM

The search strategy planner uses an LLM to plan queries. The default provider is `agy` (the Antigravity CLI — subscription auth, no API key); if it's unavailable the planner degrades to keyword heuristics, so search still works. Configure a different provider:

```toml
[retrieval_agent]
provider = "agy"  # Options: agy, gemini, openai, anthropic, ollama
model = "Gemini 3.5 Flash (Low)"
api_key_env = "GEMINI_API_KEY"  # Environment variable name
base_url = ""  # For ollama: "http://localhost:11434"
```

Examples:

| Provider | Config |
|----------|--------|
| Antigravity CLI (default) | `provider = "agy"` — no API key; shells out to the `agy` CLI |
| Gemini | `provider = "gemini"`, `model = "gemini-2.5-flash"`, set `GEMINI_API_KEY` |
| OpenAI | `provider = "openai"`, `model = "gpt-4o-mini"`, set `OPENAI_API_KEY` |
| Anthropic | `provider = "anthropic"`, `model = "claude-3-haiku-20240307"`, set `ANTHROPIC_API_KEY` |
| Ollama | `provider = "ollama"`, `model = "qwen3:8b"`, `base_url = "http://localhost:11434"` |

## Supported AI Agents

Works with any AI coding assistant that can run shell commands:

- **Claude Code** — `rag install-claude` installs the `/rag` slash command
- **Codex** — `rag install-agent codex` installs skills
- **Gemini** — `.gemini/settings.json` for graphify integration
- **Qoder** — Skills in `skills/` directory
- **Cursor/Trae/Kilo** — `.cursorrules` for guidelines

## The TUI dashboard

`rag tui` (or `rag start --tui`) opens a full-screen stack dashboard. Unlike a plain daemon client, it probes the whole stack directly — the daemon over HTTP, and Ollama, Docker and Qdrant the same way `rag diagnose` does — so it's still useful when parts of the stack are down.

- **Service cards** — Daemon, Ollama, Docker, Qdrant. Each shows live state (running / degraded / down) with the model list, container status, versions, and, when something is wrong, the exact fix (including the daemon's last crash reason, tailed from `~/.rag/logs/daemon.jsonl`).
- **Project indexes** — every indexed repo with chunk/file counts, last-indexed time, and collection.
- **Activity** — query rate, p50/p95 latency, recent queries, and any running index jobs.
- **Screens** — Dashboard, Search (with optional repo filter), Ask (grounded RAG answer), Index (live progress), Logs (daemon event tail), Help (active config).

Keys: `h/s/a/i/l/?` switch screens · `D` start daemon · `U` start Qdrant container · `W` open web dashboard · `r` refresh · `q` quit.

Prefer a browser? `rag web` serves the same data as a single-page dashboard at `http://127.0.0.1:7890/`.

## Architecture

Headless daemon (FastAPI on `127.0.0.1:7890`) is the supervised process. CLI subcommands are thin HTTP clients — none of them load models. The Textual TUI (`rag tui`) runs as a **separate process** and additionally probes Ollama/Docker/Qdrant directly (via `src/rag/tui/monitor.py`), so a TUI crash never affects the daemon and a daemon crash never blinds the dashboard. See [`docs/ADR/001-full-stack-decision.md`](docs/ADR/001-full-stack-decision.md) for the full design (note: ADR-001 originally described a single-process daemon; the TUI was split into its own process when launchd supervision was added).

## Benchmark Results

Latest production benchmark (Signal-Android, 10 scenarios, 5 agents):

| Agent | Avg Turns | Tokens | Precision | Signal | Coverage |
|-------|-----------|--------|-----------|--------|----------|
| Smart Agent | 7.7 | 4,904 | 70.2% | 89.5% | 94.2% |
| AST-Index | 3.0 | 3,000 | 74.0% | 85.0% | 78.0% |
| Graphify | 3.8 | 3,800 | 65.0% | 78.0% | 72.0% |
| Vanilla | 5.0 | 5,000 | 45.0% | 60.0% | 55.0% |

See `docs/benchmark_production_scenarios/summary.md` for full details.

## Troubleshooting

Run `rag diagnose` first — it reports daemon health, Ollama reachability and required models, LSP server detection (with install hints for missing ones), and cache stats. `rag tui` shows the same information continuously, and its service cards print the fix for whatever is failing.

**Daemon crashes immediately on `rag start` (`server_init_failed`).** Almost always an embedding-model mismatch: `embeddings.model` in `~/.rag/config.toml` must be an **exact Ollama tag** that `ollama list` prints (e.g. `qwen3-embedding:4b-q8_0`), not a HuggingFace-style name like `Qwen/Qwen3-Embedding-4B`. The model verifier does substring matching, so `qwen3-embedding-4b` never matches the tag `qwen3-embedding:4b-q8_0`. Fix:

```bash
ollama list                                # find your installed tag
# then set it in ~/.rag/config.toml:
# [embeddings]
# model = "qwen3-embedding:4b-q8_0"
# dim = 2560
```

Check `~/.rag/logs/daemon.jsonl` for the exact error (the TUI's Daemon card surfaces it automatically).

**`rag: command not found`.** The `rag` entry point lives in the project venv. Either activate it (`source .venv/bin/activate`) or symlink it onto your PATH (`ln -s "$PWD/.venv/bin/rag" /opt/homebrew/bin/rag`) — its shebang points at the venv's Python, so it then works from any directory.

**Qdrant not reachable.** Default mode is a Docker container; start it with `rag qdrant-up` (or the `U` key in the TUI). Confirm Docker Desktop is running.

For index issues, run `rag verify` to detect orphaned or duplicate chunks, then `rag repair` to clean them up.
