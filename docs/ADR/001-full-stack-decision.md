# ADR-001: Full-stack architecture for the local RAG system

Status: accepted (originally 2025; revised 2026-07 to match the shipped system)

## Context

We need local, fast, agent-friendly code retrieval over multiple repositories
(primary benchmark target: Signal-Android, ~10k files) without paying
per-query API costs and without shipping source code to third parties. The
system is consumed three ways: a CLI for humans, HTTP for agents (Claude
Code / Codex skills), and a read-only dashboard.

## Decision

### Process model: headless daemon + thin clients

A single supervised process — `rag start` — runs FastAPI/uvicorn with
embedded-or-server Qdrant, the Agno planner agent, the file watcher, and all
index/query logic in one event loop. Everything else is an HTTP client to
`127.0.0.1:7890`:

- `rag <cmd>` CLI subcommands POST to the daemon (they never load models).
- `rag tui` is a **separate read-only process** polling `/health` + `/status`.
  (ADR originally specified TUI and server in one process; that coupled TUI
  crashes to the HTTP server and was split post-launch.)
- The web dashboard is a single self-contained `index.html` served at `GET /`
  with the bearer token injected at serve time (same-origin auth, no CORS).

launchd (macOS) supervises the daemon via `rag service install`
(`KeepAlive=true`). systemd is deliberately not auto-generated.

### Vector store: Qdrant, server mode by default

`qdrant.mode = "server"` (docker `compose.qdrant.yml`, `127.0.0.1:6333`) is
the default because payload indexes do not work in embedded/local mode and
the structural channels depend on them. `mode = "embedded"` remains supported
for zero-dependency setups and is what tests use.

### Embeddings: dense-only via Ollama

Qwen3 embeddings through a local Ollama daemon. Documents and queries use
**different instruction prefixes** — preserve that asymmetry. BM25/sparse and
the FastEmbed ONNX fallback were removed post-launch; a SQLite FTS "code
index" provides the lexical/exact-match channel instead. The cross-encoder
reranker was removed; scoring is dense similarity + metadata boosts
(`core/scoring.py`).

### Chunking: 3-tier tree-sitter, any language with a grammar

T1 file summary / T2 class summary / T3 function body, with per-language
node-type config in `core/chunker.py:LANGUAGE_CONFIG`. Wrapper nodes
(`decorated_definition`, `export_statement`, `template_declaration`) are
unwrapped so decorated/exported/templated definitions chunk correctly.
Chunks carry a parseable `source_text` for enrichment (patterns, complexity,
imports, calls) separate from the embedded `content` (which is prefixed with
a language-appropriate comment header).

### Index-time-only LSP

LSP servers start for the duration of an index run and are killed afterward —
zero query-time overhead is a hard invariant. Enrichment queries use exact
0-based symbol-name positions recorded by the chunker.

### Retrieval: planned, multi-channel

`plan_search` (LLM planner via `[retrieval_agent]` provider — default `agy`
CLI with keyword-heuristic fallback; both paths must always yield a valid
plan) → strategy dispatch (`core/search_exec.py`) → lexical promotion from
SQLite FTS → symbol sanity filter → weighted scoring. Higher-level agentic
retrieval (`/smart-search`, `core/smart_search.py`) fuses exact symbol
resolution, structural expansion (`core/structural.py`), the vocab
concept→symbol layer (`core/vocab.py`), and semantic search.

### Storage

- Qdrant collections: `code_chunks` / `doc_chunks` / `module_summaries` /
  `lod_l0` / `lod_l1` (+ per-repo collections via `core/repos.py`).
- SQLite (`~/.rag/rag.db`, WAL, thread-local connections in `storage/db.py`):
  query logs, materialized overview counters, the lexical code index, rate
  buckets.
- `~/.rag/embed_cache.db`: embedding cache keyed by `model:content_hash`.
- Per-repo incremental state under `~/.rag/repos/<sha>/state.json`, written
  atomically; file hashes are promoted only after their chunks are confirmed
  upserted.

## Consequences

- One supervised process; clients are stateless and cheap.
- The daemon must be running for nearly every CLI command (`_require_daemon`).
- Localhost-only threat model: bearer token + trusted-host check +
  same-origin dashboard; no TLS. Do not bind non-loopback without a proxy.
- Removed features (reranker, sparse) leave accepted API vestiges
  (`SearchRequest.rerank`, `[reranker]` config section) that parse but no-op.
