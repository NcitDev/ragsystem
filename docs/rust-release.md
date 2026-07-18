# Rust Release, Fresh-Machine Setup, and Cutover

## Build

Build the host artifact with Rust 1.88 or newer and no Python dependency:

```sh
scripts/build-rust-release.sh
```

Pass a Rust target triple to build another installed target. The script writes
`dist/<target>/rag-rs` and `SHA256SUMS`, then executes the binary in a clean
environment.

## Fresh machine (no Python, single binary + Docker)

Runtime dependencies are exactly three: the `rag` binary, Docker (hosts
Qdrant), and Ollama (embeddings + optional planner/generation models).

```sh
# 1. Install the binary
install -m 0755 rag-rs ~/.local/bin/rag

# 2. Vector store: Docker-hosted Qdrant (container rag-qdrant,
#    storage ~/.rag/qdrant_server, port from qdrant.url in config)
rag qdrant-up
rag qdrant-status

# 3. Models (names come from ~/.rag/config.toml — created with defaults on
#    first start; edit [embeddings] / [retrieval_agent] to match your pulls)
ollama pull qwen3-embedding:4b        # default embeddings model (dim 2560)
ollama pull qwen3:8b                  # planner + /ask generation (optional)

# 4. Daemon under supervision (systemd user unit on Linux, launchd on macOS)
rag service install

# 5. Index and search
rag index ~/src/my-repo --name myrepo
rag search "how does authentication work" --repo myrepo
```

First start bootstraps `~/.rag` (bearer token with `0600` permissions, default
`config.toml`). The web dashboard is served at `http://127.0.0.1:7890/` with
the token injected; `rag tui` gives the terminal stack dashboard.

The default `config.toml` names `qwen3-embedding:4b` (dim 2560), an exact
official Ollama tag. Set `[embeddings] model/dim` to the model you actually
pulled before the first `rag index`, since the collection is created with that
dimension. Existing user config is not rewritten; users with the former
`Qwen/Qwen3-Embedding-4B` default must change it explicitly.

For remote Qdrant, use an `https://` `qdrant.url` and export the secret named
by `qdrant.api_key_env` (default: `QDRANT_API_KEY`). The daemon rejects remote
plaintext HTTP. Remote `llm.ollama_url` also requires HTTPS. Embedded mode
verifies the pinned official release SHA-256,
bounds download/extraction sizes, and refuses to adopt an unknown process on
the configured port. A legacy managed binary without its `.sha256` sidecar is
replaced from the verified release on the next embedded-mode start.

Use `/live` for supervisor liveness and `/ready` for dependency readiness.
The latter probes Ollama and Qdrant under a two-second overall deadline. All
responses include `x-request-id`, and `server.max_in_flight` controls protected
request backpressure (HTTP 503 plus `Retry-After: 1` when saturated).

## Supervision

`rag service install` writes and activates a per-user launchd agent on macOS
or systemd user service on Linux. Use `--dry-run` to inspect the descriptor
without modifying the supervisor. Qdrant restarts with Docker
(`--restart unless-stopped`); enable Docker at login
(`systemctl --user enable docker-desktop` on Docker Desktop for Linux).

## Shadow Validation

Run the old daemon on port 7890 and the candidate on port 7891 against copied
state, then run:

```sh
rag-rs migration shadow --output shadow-report.json
```

The report is passing only when normalized contracts, first-hit rankings, and
non-LLM p95 latency gates all pass. A custom JSON case list may be supplied with
`--cases`.

## Guarded Cutover

Prepare a checksum-verified backup and manifest:

```sh
rag-rs migration prepare-cutover \
  --rag-home /path/to/copied-rag-home \
  --backup /path/to/backup \
  --rust-binary /path/to/rag-rs \
  --shadow-report shadow-report.json
```

Activation and rollback require `--acknowledge-data-risk`. The tool never
overwrites live state during rollback: it verifies the backup and marks it
`rollback_ready`, after which the operator must stop both daemons and restore
the directory. Keep the last Python release for one full compatibility window.

## Executed cutover record (2026-07-17)

See `docs/rust-migration-plan.md` §11.3–§11.4 for the executed cutover on the
production machine: `rag` is the Rust binary on port 7890 under
`rag-rs.service`, Qdrant runs in the `rag-qdrant` Docker container on 6333
(storage `~/.rag/qdrant_server`, 46,121-point signal index verified), and the
Python venv remains only as the rollback path
(`~/.rag-backup-cutover/README.md`).
