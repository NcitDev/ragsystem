# Rust Migration Plan

Status: approved for implementation on branch `rust-migration`.

## 1. Objective

Replace the Python production runtime with a prebuilt Rust application while
preserving the behavior and data contracts of the current RAG system.

The final production installation must:

- Run without Python, pip, uv, or a virtual environment.
- Ship as a prebuilt `rag` executable for each supported platform.
- Preserve the current CLI commands, HTTP request/response schemas, auth model,
  configuration, repository registry, and supervised daemon behavior.
- Read existing `~/.rag` state and existing Qdrant collections without requiring
  users to discard or silently rebuild data.
- Preserve the deterministic retrieval flow. Rig is the typed LLM/provider
  adapter, not the owner of retrieval orchestration.
- Keep Ollama and Qdrant as external services during the initial migration.

Removing Python source from benchmarks and development utilities is a later
cleanup milestone. Production-runtime independence is the first completion
criterion.

## 2. Non-goals

- Do not redesign retrieval ranking while establishing parity.
- Do not replace Qdrant or Ollama in the first migration.
- Do not turn deterministic retrieval into an autonomous tool-calling loop.
- Do not change public endpoint or CLI names merely to make the Rust design
  cleaner.
- Do not delete the Python implementation until the Rust implementation passes
  contract, retrieval, migration, and operational acceptance gates.
- Do not introduce a Rust sidecar called by Python. That would retain Python and
  add an IPC boundary without achieving the objective.

## 3. Existing Behavioral Contract

The migration must preserve this pipeline:

```text
query
  -> typed LLM or heuristic planner
  -> SearchPlan { queries, filters, strategy, top_k }
  -> deterministic AST, lexical, graph, and Qdrant retrieval
  -> symbol grounding and structural expansion
  -> scoring, deduplication, and token budgeting
  -> context data returned to the calling coding agent
```

Important current boundaries:

- `src/rag/agents/retrieval.py` owns LLM planning, symbol inference, plan
  validation, and heuristic fallback.
- `src/rag/core/search_exec.py` owns deterministic strategy execution.
- `src/rag/core/smart_search.py` owns grounding, exact resolution, vocabulary
  anchors, usage trimming, and structural expansion.
- `src/rag/agents/repo_agent.py` builds deterministic repo-agent plans and
  evidence bundles.
- `src/rag/server.py` defines the public HTTP contract.
- `src/rag/cli.py` defines command names and user-facing behavior.
- `src/rag/storage/db.py` and `~/.rag/repos/*/state.json` define durable local
  state.
- Qdrant collection names and payload fields are persisted public data, even if
  they are not formally versioned today.

The Python implementation remains the behavioral oracle until cutover.

## 4. Target Architecture

Create a Cargo workspace. Keep most crates as libraries and produce one final
`rag` binary so users receive a single executable.

```text
Cargo.toml
crates/
  rag-app/          final binary, process lifecycle, command dispatch
  rag-contracts/    HTTP DTOs, SearchPlan, enums, shared serialization
  rag-config/       TOML/env loading, paths, validation, secrets
  rag-storage/      SQLite, repository registry, cache, migrations
  rag-index/        tree-sitter chunking, AST index, crossrefs, LSP enrichment
  rag-retrieval/    lexical/vector/graph search, scoring, context packs
  rag-agent/        Rig providers, typed planning, agy adapter, fallbacks
  rag-server/       Axum routes, auth, middleware, events, web assets
  rag-cli/          thin HTTP client commands and presentation
  rag-tui/          Ratatui dashboard and stack monitoring
```

Initial implementation may start with fewer crates, but dependencies must point
in this direction:

```text
contracts <- config/storage/index/retrieval/agent <- server/cli/tui <- app
```

The server must not depend on CLI presentation code. CLI commands that operate
on daemon-owned state must remain thin HTTP clients.

### Proposed Rust libraries

| Responsibility | Rust library |
| --- | --- |
| Async runtime | Tokio |
| HTTP server/middleware | Axum, Tower, tower-http |
| CLI | Clap |
| TUI | Ratatui, Crossterm |
| JSON/TOML contracts | Serde, serde_json, toml |
| Validation | validator or explicit newtypes |
| HTTP clients | Reqwest |
| LLM abstraction | Rig, pinned in `Cargo.lock` |
| Qdrant | qdrant-client |
| SQLite | Rusqlite initially, with explicit migrations |
| Parsing | tree-sitter and per-language grammar crates |
| Graphs | Petgraph |
| File watching | notify |
| Logging/telemetry | tracing, tracing-subscriber, OpenTelemetry |
| Errors | thiserror in libraries, anyhow only at process boundaries |
| Embedded web assets | rust-embed or include_dir |

## 5. Design Rules

### 5.1 Rig usage

Rig is limited to provider abstraction, typed prompts, streaming where required,
and telemetry hooks. Define an application-owned trait:

```rust
trait Planner {
    async fn plan_search(&self, query: &str) -> Result<SearchPlan, PlannerError>;
    async fn infer_symbols(&self, question: &str) -> Result<Vec<String>, PlannerError>;
}
```

`SearchPlan` uses a Rust enum for the four valid strategies and validates all
filter vocabularies after deserialization. Invalid, unavailable, or timed-out
planner responses fall back to the deterministic heuristic planner.

Do not expose AST, Qdrant, filesystem, or shell tools directly to a general Rig
agent loop. The application owns the sequence, limits, cancellation, and
fallback decisions.

The current default `agy` provider is not a built-in Rig provider. Preserve it
with an async subprocess-backed `Planner` implementation or make an explicit
product decision to change the default. Do not silently change authentication
or provider cost.

### 5.2 Concurrency

Use bounded Tokio concurrency for independent work:

- Symbol inference, semantic search, and vocabulary search.
- Expanded multi-query Qdrant searches.
- Cross-repository smart search.
- Independent repo-agent reuse, documentation, and call-tree requests.
- Qdrant and AST structural expansion.

Preserve ordering after fan-out. Deduplication and ranking must not depend on
hash-map iteration order.

### 5.3 Compatibility

During coexistence, run the Rust daemon on `127.0.0.1:7891`; Python continues on
`127.0.0.1:7890`. The Rust binary is named `rag-rs` until cutover to avoid
shadowing the installed Python `rag` command.

Preserve:

- `~/.rag/config.toml` keys, defaults, and validation behavior.
- `~/.rag/token` and bearer-token authentication.
- Loopback-only binding and Host-header protection.
- Repository state and collection naming.
- SQLite table names, field semantics, and migration safety.
- Qdrant payload field names, vector dimensions, and filter behavior.
- HTTP status codes and error JSON shapes.
- Launchd labels, log paths, and restart semantics at final cutover.

Any durable schema change must be additive, versioned, backed up, and readable by
the previous Python version until the final cutover decision.

## 6. Migration Phases

### Phase R0: Contract capture and Rust bootstrap

Deliverables:

- Record the source commit from which migration starts.
- Export the current FastAPI OpenAPI document as a checked-in fixture.
- Add representative golden JSON fixtures for `/health`, auth errors, `/status`,
  `/search`, `/resolve`, `/context-pack`, and `/smart-search`.
- Create the Cargo workspace, shared lint configuration, and CI commands.
- Add a `rag-rs` binary with `--version` and `start` commands.
- Serve public `GET /health` on port `7891` with the current response shape.
- Add Rust tests for config defaults, loopback validation, auth parsing, and
  health serialization.

Exit gate:

- `cargo fmt --check`, `cargo clippy --workspace --all-targets -- -D warnings`,
  and `cargo test --workspace` pass.
- Python tests remain unchanged and passing.
- No production Python files are modified except where required to export stable
  contract fixtures.

### Phase R1: Configuration, auth, and durable storage

Deliverables:

- Port settings and default TOML loading.
- Port `~/.rag` path resolution, dotenv behavior, token creation, and auth.
- Port repository registry and state-file serialization.
- Port SQLite schema access and add migration/version checks.
- Add read-only compatibility tests against a copy of a real Python-created
  `~/.rag` directory.
- Port structured logging and the in-process event ring.

Exit gate:

- Rust reads Python-created config, token, repo state, and SQLite data.
- Tests prove startup refuses incompatible/newer schemas without modifying data.

### Phase R2: External service clients

Deliverables:

- Ollama health, tag/model verification, embeddings, batching, retry, and cache.
- Qdrant collection management, vector search, filters, scroll, upsert, delete,
  counts, and collection metadata.
- Health-detail and status parity.
- Retry budgets, timeouts, cancellation, and bounded concurrency.

Decision gate: Qdrant embedded mode

The current embedded mode is implemented by Python Qdrant client local mode and
has no assumed drop-in Rust equivalent. Before R2 closes, choose and document
one option:

1. Deprecate embedded mode and require Qdrant server mode.
2. Implement a compatible embedded backend with an explicit data migration.
3. Package/manage a local Qdrant server process while preserving the user-facing
   embedded experience.

Do not silently map embedded data to a different backend.

### Phase R3: Code indexing and structural data

Deliverables:

- Port file discovery, ignore rules, hashing, incremental diff, and watcher.
- Port tree-sitter chunking and metadata for every currently supported language.
- Port SQLite lexical code index.
- Port AST definitions/usages, crossrefs, call trees, and graph persistence.
- Port LSP discovery and optional index-time enrichment.
- Port indexing jobs, progress events, cancellation, repair, and verification.
- Port summary and vocabulary indexing.

Special investigation:

- Confirm a maintained Rust Dart grammar or define a supported fallback before
  claiming language parity.
- Golden-test chunk boundaries, names, parent names, metadata, and stable IDs
  against fixtures produced by Python.

Exit gate:

- Golden fixture output matches for all supported languages.
- Incremental indexing changes only affected files/chunks.
- A Rust index can be queried by Python and a Python index can be queried by
  Rust for all shared storage paths.

### Phase R4: Deterministic retrieval

Port in this order:

1. Exact symbol/file lookup and lexical promotion.
2. Dense Qdrant search and payload filters.
3. Scoring, sanity filtering, deduplication, and token estimation.
4. Search-plan strategy execution.
5. Resolve, call tree, impact, affected files, and graph expansion.
6. Context-pack construction and project understanding.
7. Smart-search grounding, vocabulary fallback, related files, and pagination.
8. Repo-agent evidence bundle construction.

Exit gate:

- Contract fixtures match after normalization of latency and nondeterministic
  identifiers.
- Existing navigation and retrieval evaluation suites meet the acceptance
  thresholds in section 8.

### Phase R5: Planner and generation through Rig

Deliverables:

- Typed `SearchPlan` output with post-deserialization sanitization.
- OpenAI, Anthropic, Gemini, and Ollama planner implementations through Rig.
- Async `agy` subprocess adapter with timeouts and process-tree cleanup.
- Deterministic heuristic fallback matching current behavior.
- Symbol inference with grounded validation.
- Planner/result TTL cache invalidated by indexing completion.
- `/ask` generation parity with citations and insufficient-context handling.
- Cassette or mock-model tests that do not require live provider credentials.

Exit gate:

- Planner failures never prevent deterministic retrieval.
- Provider secrets do not appear in errors, logs, traces, or fixtures.
- Planner comparison benchmark is no worse than the Python baseline within the
  thresholds in section 8.

### Phase R6: HTTP server and CLI surface

Deliverables:

- Port all supported FastAPI routes to Axum.
- Generate or validate OpenAPI against the captured contract.
- Port rate limiting, auth, trusted hosts, error mapping, request logs, and
  websocket/event behavior.
- Port every production CLI command to Clap.
- Ensure stateful commands call the daemon instead of importing core logic.
- Preserve machine-readable JSON and shell exit codes.
- Embed and serve the web dashboard.

Exit gate:

- HTTP contract suite passes against Python and Rust daemons.
- CLI smoke suite passes using only the Rust executable.

### Phase R7: TUI, supervision, packaging, and release

Deliverables:

- Port the Textual dashboard to Ratatui without coupling it to daemon lifetime.
- Preserve direct monitoring of daemon, Ollama, Qdrant, and Docker.
- Port launchd installation/status/uninstallation and Linux service support.
- Build release binaries for supported macOS and Linux architectures.
- Add checksums, signing/notarization where applicable, and upgrade/rollback
  documentation.
- Test installation on a machine without a Python runtime available on `PATH`.

Exit gate:

- A prebuilt artifact can initialize, index, search, open the TUI/web UI, and
  restart under supervision without invoking Python.

### Phase R8: Shadow validation and cutover

Run both daemons against copied production data and replay identical requests.
Compare normalized responses, errors, query plans, ranked files, and latency.

Cutover steps:

1. Back up `~/.rag` and record Qdrant collection metadata.
2. Stop Python daemon writes.
3. Run Rust read-only validation.
4. Enable Rust writes after storage compatibility checks pass.
5. Replace the installed `rag` executable and supervisor command.
6. Retain the last Python release and rollback instructions for one release
   window.
7. Remove Python production code and dependency manifests only after the
   rollback window closes.

## 7. Testing Strategy

### Contract tests

- Snapshot OpenAPI and representative JSON.
- Run the same black-box suite against ports `7890` and `7891`.
- Normalize latency, timestamps, point IDs, and unordered maps only where the
  contract does not guarantee them.

### Storage compatibility tests

- Copy fixtures before every test; never test destructive migration on the only
  real user state.
- Verify Python-created SQLite and state JSON can be read by Rust.
- Verify Rust writes remain readable by the supported Python rollback version.
- Verify Qdrant filters return equivalent point sets.

### Retrieval tests

- Port unit tests for fallback planning, filter sanitization, scoring, chunking,
  AST resolution, context packing, and repo-agent planning.
- Reuse existing evaluation JSONL files and golden file sets.
- Record ranks and source paths, not only response text.

### Operational tests

- Cancellation during indexing and LLM calls.
- Ollama/Qdrant unavailable at startup and during requests.
- Corrupt/unsupported config and storage versions.
- Supervisor restart and stale PID handling.
- Clean install without Python.

## 8. Acceptance Metrics

The Rust implementation is not ready for cutover unless all mandatory gates
pass:

| Area | Required result |
| --- | --- |
| Runtime | No Python executable, library, wheel, venv, or Python subprocess required |
| HTTP | All supported route contract tests pass |
| CLI | Command names, JSON mode, exit codes, and core output fields match |
| Storage | Existing config, token, repo state, SQLite, and Qdrant data are readable |
| Chunking | Golden language fixtures match expected boundaries and metadata |
| Retrieval | Coverage and precision regress by no more than 2 percentage points |
| Ranking | No unexplained expected-file first-hit rank regression |
| Latency | Non-LLM p95 is no worse than Python; LLM time is reported separately |
| Reliability | Planner/provider failure still returns deterministic fallback results |
| Security | Loopback bind, Host protection, auth, secret handling, and rate limits pass |
| Packaging | Prebuilt binary passes a clean-machine smoke test without Python |

Performance claims must distinguish:

- Process startup and resident memory.
- CPU-bound indexing/chunking.
- Qdrant and Ollama network time.
- LLM planner/generation time.

Do not attribute external model latency improvements to Rust.

## 9. Primary Risks

| Risk | Mitigation |
| --- | --- |
| Big-bang rewrite diverges from behavior | Strangler phases, dual daemons, black-box parity tests |
| Rig API churn | Pin versions and `Cargo.lock`; hide Rig behind application traits |
| `agy` not supported by Rig | Maintain a tested subprocess Planner adapter |
| Qdrant embedded mode mismatch | Resolve explicit R2 decision gate before storage cutover |
| Tree-sitter grammar differences | Per-language golden fixtures before indexing parity claim |
| SQLite/Qdrant corruption | Copy fixtures, read-only probes, backups, additive migrations |
| Hash-map/concurrency nondeterminism | Stable sorting and explicit tie-breakers after fan-out |
| TUI consumes migration budget | Defer until data plane and HTTP parity are proven |
| Python removal blocks rollback | Keep last Python release for one compatibility window |

## 10. Work Sequencing Rules

- One phase or one vertically testable endpoint group per commit.
- Keep Python green while Rust is incomplete.
- Never modify real `~/.rag` state in tests.
- Do not mix retrieval-algorithm tuning with language-port changes.
- Record before/after benchmark artifacts for every retrieval behavior change.
- Prefer black-box compatibility tests over line-by-line transliteration.
- Update this plan when a decision gate is resolved.

## 11. Implementation Checkpoint (2026-07-11)

- R0-R5 libraries and compatibility fixtures are implemented in the Cargo workspace.
- R6 exposes every captured FastAPI route in Axum, enforces loopback Host/auth/rate limits,
  embeds the dashboard, and provides live SQLite-backed index/search, AST navigation,
  context, smart-search, graph, enumeration, docs, and deterministic ask paths. Routes
  whose external backend is unavailable fail closed rather than returning fixtures.
- The Clap command surface is a thin HTTP client for the production command families.
- R7 includes a separate Ratatui process with direct daemon/Ollama/Qdrant/Docker probes,
  launchd and systemd user descriptors, checksums, and a Python-free release smoke test.
- R8 includes normalized dual-daemon contract/ranking/p95 comparison, checksum-verified
  copied-state backup preparation, explicit activation acknowledgement, and rollback-ready
  verification. No real `~/.rag` cutover was executed by implementation tests.

The code implementation gates pass locally. Production cutover remains blocked until a
real copied-data shadow report passes the section 8 retrieval/ranking/latency thresholds
and an operator explicitly approves activation.

## 11.1 Verification checkpoint (2026-07-17, fresh Linux machine)

Independent re-verification on a clean machine with real copied `~/.rag` data
(signal repo, 46,121 chunks):

- `cargo fmt --check`, `cargo clippy --workspace --all-targets -- -D warnings`,
  and `cargo test --workspace` (72 tests) pass. Python suite: 148 passed.
- **Integration gap:** `rag-services` (Ollama + Qdrant clients, R2) is not used
  by `rag-server` or `rag-app`. The live `/search` path is SQLite keyword
  scoring over `code_index`; `/smart-search` is a heuristic approximation; the
  planner in the live path is always `fallback_plan` (Rig/agy planners exist in
  `rag-agent` but are not wired in). Several routes still return canned JSON.
- **Shadow benchmark** (`bench/benchmark_rust_vs_python.py`, 10 scenarios × 3
  repeats, top_k=15, identical `~/.rag` state): Python-fallback 50.8% coverage /
  16.2% precision / p95 2.7s; Rust 3.3% coverage / 0.8% precision / p95 0.7s.
  Section 8 retrieval gate **fails** (coverage Δ −47.5pp). Latency and memory
  gates pass (Rust RSS 14 MiB vs Python 8.6 GiB). Exact-symbol queries do hit
  (keyword search finds `FullBackupExporter`); natural-language questions do
  not.
- Full artifacts: `bench/benchmark_rust_vs_python_results.json` and
  `docs/benchmark_rust_vs_python/summary.md`.

Conclusion: R4/R5 are not integrated into the live daemon (R6) despite the
section 11 checkpoint. Cutover remains blocked on wiring dense retrieval
(Ollama embeddings + Qdrant search + strategy execution) and the typed planner
into `rag-server`, then re-running the shadow benchmark.

## 11.2 Dense retrieval integration (2026-07-17)

The gap identified in 11.1 was closed:

- **R2 decision gate resolved as option 3 (managed local server).** The
  embedded (Python local-mode) store was migrated point-for-point into a
  user-owned Qdrant 1.18.2 server (`~/.rag/bin/qdrant`, storage
  `~/.rag/qdrant_server`, loopback `127.0.0.1:6335` — 6333 was occupied by an
  unidentified root-owned Qdrant instance on this machine). 46,121 +
  3,753 points copied with exact counts, payload indexes created, self-search
  parity verified. `~/.rag/config.toml` switched to `mode = "server"`;
  the embedded store is kept at `~/.rag/qdrant_data` for rollback
  (config backup: `~/.rag/config.toml.bak-embedded`). Supervision:
  `systemd --user` unit `rag-qdrant.service`.
- **`rag-server` now executes the Python `/search` pipeline live**
  (`crates/rag-server/src/retrieval.rs`): heuristic plan → repo-scoped
  strategy forcing → per-expanded-query Ollama embedding (query instruction
  prefix) → Qdrant dense search with compiled payload filters → lexical
  promotion from the new SQLite FTS port
  (`rag_storage::search_code_chunks`, score squash `0.75·raw/(raw+3)`) →
  symbol sanity filter → weighted scoring → Python-slim response shape.
  `lod_drill` degrades to flat hybrid without LOD data; `graph_walk`
  degrades to hybrid (the Python pickle graph is not readable from Rust);
  `/smart-search` semantic section uses the dense pipeline; `/health` and
  `/status` report real Ollama/Qdrant component state. The LLM planner is
  still not wired (both planner modes use the deterministic heuristic).
- **Shadow benchmark round 2** (same protocol as 11.1): Rust matches
  python-fallback **exactly** on all 10 scenarios — coverage 50.8% / precision
  16.1% on both, Δ 0.0pp. Latency: Rust mean 82 ms / p50 16 ms / p95 372 ms vs
  Python mean 226 ms / p50 191 ms / p95 343 ms (Rust p95 is 29 ms worse — the
  cold path is dominated by the shared Ollama embedding call; warm queries hit
  the in-process embedding cache). RSS: Rust 18 MiB vs Python 118 MiB.
  Artifacts: `bench/benchmark_rust_vs_python_results.json`,
  `docs/benchmark_rust_vs_python/summary.md`.

Remaining before cutover: LLM/agy planner wiring (R5 into R6), smart-search
vocab/related parity, indexing write-path parity (Rust `/index` does not embed
into Qdrant), and the section 6 cutover steps (rename, supervisor swap).

## 11.3 Cutover executed (2026-07-17)

All 11.2 gaps were closed and the section 6 cutover ran on the production
machine, operator-directed:

- **Indexing write path** (`crates/rag-server/src/indexing.rs`): incremental
  git-state + per-file-hash diffing, tree-sitter chunking with ported
  Kotlin/Java enrichment (`rag-index/src/enrich.rs`), Ollama document
  embeddings through the shared `embed_cache.db` (Python blob format),
  deterministic `uuid5(NAMESPACE_DNS, chunk_id)` point ids, Qdrant upsert with
  the full `PAYLOAD_INDEXES` set, SQLite `code_index`/FTS mirroring, atomic
  `state.json`, per-file stale deletion, `--full` collection reset, registry
  updates. Verified on a synthetic repo (create/edit/delete/full) and on
  signal: a Rust incremental run over the Python-built state processed 0
  changed files (5,652 hashes matched exactly) and kept counts at 46,121.
  Two real bugs were found and fixed along the way: the REST
  `points/delete` body used the gRPC `PointsSelector` shape, and discovery
  respected `.gitignore` while Python does not (a fresh-machine
  Python-produced state.json was the oracle: it includes tracked
  `.idea/fileTemplates` files).
- **Planner/generation**: `planner=auto|llm` now calls the configured
  `[retrieval_agent]` provider (`ollama` via `/api/chat`, `agy` via the
  subprocess adapter) with the verbatim Python instructions and falls back to
  the heuristic on any failure; `/ask` does grounded generation with inline
  `[N]` citations, the 0.22 grounding gate, and `INSUFFICIENT_CONTEXT`
  handling; `/smart-search` surfaces vocab anchors/files from the
  `<collection>_vocab` collection with the gated-fallback grounding rule.
- **Cutover**: `~/.rag-backup-cutover/` holds SQLite/state/config/token
  backups plus rollback instructions; the Python launcher is preserved as
  `rag-python-launcher.bak`. `DEFAULT_PORT` moved to 7890 and the Rust binary
  is installed as both `~/.local/bin/rag` and `rag-rs`, supervised by the
  `rag-rs.service` systemd user unit (SIGKILL → auto-restart verified). The
  web dashboard now injects the daemon token at serve time. Post-cutover, the
  10-scenario suite on the supervised daemon reproduces the shadow numbers
  exactly: coverage 50.8%, precision 16.1%, 205 ms mean latency.

Known deltas after cutover (documented, not blocking): Python-language chunk
enrichment (`patterns.py`) is not ported (kotlin/java enrichment is); LOD
summary/vocab *building* still requires the Python tooling (querying them is
live); `graph_walk` degrades to hybrid (the Python pickle graph is unreadable
from Rust); non-core routes (`/admin/*`, `/diff`, `/overview`) still return
canned/minimal responses. The Python venv remains installed for the rollback
window per section 6.

## 11.4 Python-free runtime + Docker-hosted Qdrant (2026-07-17)

Operator directive: no Python on any deployment machine; single executable +
Docker for Qdrant. Closed the remaining 11.3 deltas that involved Python:

- **`patterns.py` ported** (`rag-index/src/enrich_python.rs`): tree-sitter
  based pattern/domain/layer tagging, cyclomatic + cognitive complexity,
  imports/external deps, decorators + tags, inherits/abstract, docstring,
  nesting, calls, has_unit_test (test-file stems collected during discovery).
  Matches `ast.parse` all-or-nothing semantics on syntax errors. Verified
  end-to-end: an indexed Python repo carries
  `patterns=['repository'], complexity_cyclomatic=4, inherits_from=[...]`.
- **`/vocab/build` ported** (`rag-server/src/indexing.rs`): summaries JSONL →
  dedupe/ERROR-drop → embed via the shared cache → idempotent upsert into
  `<collection>_vocab` (`uuid5(repo:vocab:rel)` ids). Verified live.
- **Fresh-machine bootstrap**: first `rag start` creates `~/.rag`, a
  `token_urlsafe(32)`-format bearer token (0600), and a default
  `config.toml`; auth is enforced by default (401 without token) — previously
  the Rust daemon silently ran open when `RAG_TOKEN` was unset.
- **Docker-hosted Qdrant**: `rag qdrant-up|down|status` now use plain
  `docker run` (container `rag-qdrant`, image pinned `qdrant/qdrant:v1.18.2`,
  storage `~/.rag/qdrant_server`, loopback port taken from `qdrant.url`) — no
  compose file needed next to a standalone binary. On the production machine
  the pre-existing compose container was adopted: it was the "unidentified
  6333 listener" from 11.2 all along (Docker Desktop VM process, invisible to
  user `ps`). After a container restart it serves the migrated collections
  (46,121 + 3,753 points verified); `config.toml` moved back to the standard
  `http://127.0.0.1:6333`; the native-binary systemd unit (`rag-qdrant.service`,
  port 6335) is disabled and kept as fallback.
- **Release artifact**: `scripts/build-rust-release.sh` →
  `dist/<target>/rag-rs` + SHA256SUMS, smoke-tested with an emptied
  environment. Fresh-machine setup guide in `docs/rust-release.md`.

Post-change verification: all 79 workspace tests, fmt, clippy pass; the
10-scenario retrieval suite on the Docker-hosted stack reproduces
coverage 50.8% / precision 16.1% at 214 ms mean.

Python now remains in the repo only as the rollback oracle and for dev/bench
utilities (`bench/`, `tests/`, eval scripts) — nothing in the production
runtime invokes it. `graph_walk` (hybrid degradation) and the canned
`/admin/*`/`/diff`/`/overview` routes are the only remaining behavior deltas,
and neither involves Python.

## 11.5 Qdrant mode selection + full retrieval-mode matrix (2026-07-17)

- **`qdrant.mode` is user-selectable again** (documented in `default.toml`):
  `server` connects to `qdrant.url` (Docker via `rag qdrant-up`); `embedded`
  makes the daemon host Qdrant itself — pinned v1.18.2 binary auto-downloaded
  to `~/.rag/bin/qdrant`, spawned as a child on the `url` port with
  server-format storage at `~/.rag/qdrant_server`, stopped on graceful
  shutdown, and a live port is adopted instead of double-spawning. Verified
  end to end including the download path and shutdown kill.
- **Full retrieval-mode matrix** (`bench/benchmark_full_matrix.py`, identical
  requests to both daemons, same state/Qdrant; artifacts in
  `bench/benchmark_full_matrix_results.json` +
  `docs/benchmark_full_matrix/summary.md`):

  | Mode | py cov | rs cov | py prec | rs prec | py lat | rs lat |
  |---|---:|---:|---:|---:|---:|---:|
  | vanilla `/search` (fallback) | 50.8% | 50.8% | 16.1% | 16.1% | 220ms | 105ms |
  | `/search` planner=llm | 25.0% | 33.3% | 6.6% | 8.3% | 18.8s | 17.6s |
  | smart `/smart-search` | 55.8% | 54.2% | 10.9% | 6.1% | 820ms | 462ms |
  | ast `/resolve` | 23.3% | 25.0% | 16.7% | 12.9% | 132ms | 77ms |
  | graph `/graph/impact` | 47.5% | 50.8% | 17.7% | 18.0% | 352ms | 209ms |
  | ask `/ask` (citations) | 55.8% | 55.8% | 26.9% | 26.9% | 14.9s | 6.5s |

  The benchmark now also records resource metrics (per-mode CPU seconds,
  RSS/peak RSS, threads, FDs, disk IO, install footprint, cold-start) — after
  the full run: Rust 26.7 MB RSS / 2.0 CPU-s / 82 ms cold start / 29.5 MB
  binary vs Python 144.2 MB RSS / 7.5 CPU-s / 1333 ms cold start / 248 MB
  venv. A third matrix-caught defect: AST resolution (both stacks shell out
  to the same external Node.js `ast-index` CLI) returned nondeterministic
  subsets because the CLI truncates in parallel-scan order; the Rust adapter
  now over-fetches 3x and ranks with Python's `_hit_rank_score` plus explicit
  tie-breakers before truncating — four identical requests now return
  byte-identical results (Python remains subset-nondeterministic).

  The matrix exposed two real Rust regressions, both fixed and re-measured:
  smart-search defaulted its internal semantic search to the LLM planner
  (~11.8s/call; Python never plans from smart-search), and `/graph/impact`
  was missing Python's lexical-definition fallback plus the
  `related_test_files` expansion (33.3% coverage before the port; 50.8% —
  now above Python — after). The LLM planner (qwen3:8b) degrades results on
  both stacks versus the heuristic. Non-LLM latency is dominated by the
  shared external calls (Ollama query embedding ~120-160ms, Qdrant search
  ~25ms warm); LLM modes are ~95% qwen3:8b inference time.

## 12. Historical Fresh Session Entry Point

The first implementation session starts Phase R0 only.

Read, in order:

1. This document.
2. `README.md` architecture and command sections.
3. `pyproject.toml` dependencies and entry point.
4. `src/rag/config.py` and `src/rag/default.toml`.
5. `src/rag/server.py` health/auth models and routes.
6. `tests/test_config.py`, `tests/test_auth.py`, and `tests/test_routes.py`.

Then implement this bounded milestone:

- Add the Cargo workspace and minimal crate boundaries.
- Add the temporary `rag-rs` executable.
- Implement `rag-rs --version`.
- Implement `rag-rs start --host 127.0.0.1 --port 7891`.
- Implement public `GET /health` with the existing serialized response shape.
- Reject wildcard/non-loopback binds using behavior compatible with Python.
- Add Rust formatting, clippy, and unit/integration test commands.
- Document how to run the temporary Rust daemon alongside Python.

Do not port Qdrant, indexing, retrieval, Rig, CLI breadth, or the TUI in the
first session. The first result must be a small, reviewed foundation rather than
an unverified scaffold for the entire rewrite.
