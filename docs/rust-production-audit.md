# Rust production audit

Date: 2026-07-18
Branch: `rust-production-audit`
Worktree: `/home/nikita/orca/workspaces/ragsystem/rust-production-audit`

## Outcome

This audit preserved the inherited Rust migration as an immutable baseline,
then fixed confirmed failures in indexing integrity, daemon authentication,
resource bounds, external-service resilience, Qdrant transport and bootstrap,
CLI/server contracts, and agent context delivery. The result is materially
safer for a trusted single-user or single-team deployment. It is not yet a
safe multi-tenant hosted service; the remaining work is stated explicitly
below.

The main new agent-facing capability is a deterministic, budgeted context pack
with byte and token ceilings, provenance, freshness, citations, and SHA-256
content digests. `/.well-known/rag-capabilities` provides stable public
discovery. This is a native HTTP/OpenAPI capability, not an MCP or A2A
implementation.

## Lineage and audit method

The handoff identified base `9fa1ea9b8d0eeaac9583d8c5c6d57d7cf28dedd9` and
tracked-diff SHA-256
`4549665ac789e4db6bd33be3f94b6f701ca684e1d4a1be04e16b7fca487ecbb8`.
The hash was recomputed before any edit and matched. The inherited migration
was committed unchanged as `e4ff3fba5624f3d315d287c336ab8eaeff8adc49`
(`chore: snapshot inherited Rust migration`). Generated lock/marker files and
runtime request-log additions were excluded. All later changes are audit work.

The review covered every Rust crate, the captured contracts, compatibility
fixtures, migration/release documentation, and existing benchmark reports.
Static review included error paths, lock scope, task spawning, filesystem and
subprocess use, casts, parsers, `unwrap`/`expect`/panic sites, TODO markers,
response buffering, retries/timeouts, state persistence, and secret handling.
Matches were read in context; test assertions and compile-time static-regex
construction were not reported as production defects.

## Baseline

Host at baseline:

- Linux x86_64, kernel 7.0; 12 logical CPUs; 30 GiB RAM.
- `rustc 1.96.1`, `cargo 1.96.1`.
- `cargo fmt --check`: pass, 0.18 s.
- `cargo check --workspace --all-targets`: pass, 46.21 s cold; peak RSS
  1,132,140 KiB.
- `cargo clippy --workspace --all-targets --all-features -- -D warnings`:
  pass, 3.82 s; peak RSS 361,104 KiB.
- `cargo test --workspace --all-targets`: one failure after 48.8 s. The server
  compatibility test expected HTTP 200 and received 503 because ignored SQLite
  fixture files were absent. The test also opened a checked-in fixture home for
  writes and appended to its daemon log.

Baseline logs were retained outside the repository under `/tmp` with the
`rag-audit-baseline-` prefix. The original checkout was never modified.

## Confirmed defects and resolutions

| Severity | Defect and executable evidence | Resolution and regression evidence |
| --- | --- | --- |
| High | Discovery followed source-file symlinks, so a repository could index a secret outside its root. Files were read without a byte ceiling. | Discovery accepts regular files only. `index.max_file_bytes` defaults to 4 MiB. Bounded reads/hashes reject oversized files, and Unix final-component opens use `O_NOFOLLOW` to resist replacement after discovery. A regression links an external secret and proves discovery and bounded reads reject it. |
| High | A full rebuild reset local/Qdrant state before all source files were known to be readable. A transient read failure could therefore turn a rebuild into data loss. A failure between the Qdrant and SQLite resets left old hashes claiming the damaged index was current. | Full indexing performs bounded preflight and atomically invalidates in-scope state before its first destructive write. It aborts on preflight/reset errors, so the next incremental run rebuilds any partially reset scope. Incremental indexing preserves retry state on read/size/write failures. Regressions force a Qdrant reset failure and prove stale state is not retained. |
| High | Corrupt or unreadable `state.json` was silently converted to an empty state. Incremental indexing then treated every present file as new, so stale chunks for changed or deleted files could survive indefinitely. | Incremental and scoped runs now fail closed on unreadable state. An explicit unscoped full rebuild may repair it because that path resets the entire collection; a regression proves incremental indexing neither masks nor overwrites corruption. |
| High | Failed Qdrant deletes and changed-file failures could still advance `state.json`, permanently hiding stale vectors or missing replacements. Full reset errors could be ignored while SQLite was cleared. | State is promoted only after acknowledged delete/flush operations. Failed paths retain prior hashes for retry. Full Qdrant reset/drop errors abort. Count errors are surfaced rather than converted to zero. Focused failure tests prove the old hash survives. |
| High | SQLite lexical deletes updated the content table and FTS mirror in separate autocommit operations, so an error/crash between statements could leave divergent search state. | File, language, and collection deletes now update both tables in one SQLite transaction. Existing delete/search compatibility tests exercise the result. |
| High | Documentation indexing followed symlinks, read files without a ceiling, deleted a full collection before read validation, and upserted new chunk IDs without removing stale IDs for changed line ranges. | Docs discovery rejects symlinks, uses the configured file/chunk bounds, preflights full rebuilds before reset, and atomically replaces each file in both SQLite content/FTS tables. |
| High | Per-repository indexing was only serialized in-process. Two daemons/CLIs could interleave state and vector mutations. | Added a fail-fast cross-process file lock with an in-process guard. A regression holds one lock and proves the second run is rejected. |
| High | Daemon bootstrap could bind before a valid token/config was established; unreadable token/config paths could degrade into unsafe defaults. Non-Unix token entropy was predictable, creation was race-prone, token symlinks were followed, and existing permissions were not repaired. | Home, token, dotenv, settings, and external-client policy now validate before bind. Token failures are fatal, entropy uses OS `getrandom`, creation uses `create_new` plus sync (0600 at open on Unix), a concurrent creator's on-disk token wins, and symlink/device or empty token paths are rejected. Corrupt/unsafe config is no longer masked; valid but offline dependencies are represented by readiness. |
| High | External retry “budget” did not bound the first hung attempt. Ollama concurrency was per call, its cache was unbounded, and large responses were read without a memory ceiling. | A Tokio deadline now bounds every attempt and the total retry wall clock. A shared semaphore bounds all concurrent embeds; cancellation-safe `JoinSet` scheduling stops orphan work. Cache capacity is 1,024 entries. JSON responses are capped at 64 MiB. Tests cover a hung first attempt, shared concurrency, and eviction. |
| High | Dense retrieval called Qdrant's deprecated `/points/search` endpoint even though the pinned Qdrant 1.18 line removes deprecated search APIs. A managed 1.18.2 install could therefore index successfully but fail every semantic query. | Migrated to `POST /points/query` with `query`, `using: dense`, filters, limits, and the current `{result:{points:[]}}` response shape. The mock contract asserts the exact path, request, and response envelope. |
| High | Embedded Qdrant executed an unverified, unbounded GitHub archive, extracted directly to the final path, requested a nonexistent ARM GNU asset, and silently adopted any process answering on its port. | The exact v1.18.2 official asset SHA-256 is pinned for Linux/macOS x86_64/aarch64; ARM Linux uses the published musl asset. Downloads and extracted binaries are bounded, only a regular `qdrant` entry is accepted, install is temporary-plus-rename, and a sidecar detects corruption. Embedded mode never executes an arbitrary `qdrant` from `PATH`; use server mode for an operator-managed binary. Unknown port occupants are rejected and failed/early-exit children are killed. Tests cover target/digest shape, safe extraction, symlink rejection, and strict loopback URL/port parsing. |
| Medium | The default model string was not an Ollama registry tag; the quickstart pulled `:latest` (4096 dimensions) while config declared 2560, causing model lookup or vector-dimension failures. | The default and operator docs now use the exact official `qwen3-embedding:4b` tag, whose metadata declares 2560 dimensions. Existing user configs are deliberately not rewritten. |
| Medium | Qdrant credentials could not be configured, and remote HTTP Qdrant or Ollama URLs could expose indexed code, prompts, and an API key in plaintext. | `qdrant.api_key_env` (default `QDRANT_API_KEY`) loads the secret from the environment, sends the sensitive `api-key` header, and redacts debug output. Both external services require HTTPS outside loopback and reject URL credentials/query secrets. Tests verify headers, redaction, and transport policy. |
| Medium | Collection names were interpolated into request URLs without a safe grammar. | Qdrant collection names are restricted to 1–255 ASCII letters, digits, `_`, `-`, or `.`. URL path/query injection regressions are tested. |
| Medium | Unicode error bodies and context trimming sliced Rust strings by arbitrary byte offsets and could panic. | Both paths now choose UTF-8 boundaries. Non-ASCII regression tests exercise the former panics. |
| Medium | The CLI sent `name` while the server registered only another field, so `rag index --name` did not reliably create the requested repository name. | The server recognizes canonical `repo_name` with legacy `name` fallback. The CLI sends `repo_name`; compatibility is regression-tested. |
| Medium | Discovery hashed a file, then processing could read different bytes after a concurrent edit while persisting the stale preflight hash. The next incremental run could incorrectly treat those bytes as already indexed. | Processing now hashes the exact bounded byte buffer it chunks. A regression mutates a file after preflight and proves the promoted hash matches the processed bytes. |
| Medium | `smart-search` accepted `repos` but the Rust implementation ignored it and searched no named repository, returning plausible but wrong data. | Rust now rejects `repos` with a stable 422 and requires one `repo`. OpenAPI documents the intentional difference. Multi-repository search is deferred rather than faked. |
| Medium | `/admin/export` buffered all points; the CLI omitted the required output and then overwrote server output with response metadata. | Export scrolls Qdrant in bounded pages to a unique temporary JSONL file, caps output at one million records and 1 GiB, syncs then renames, and cleans temporary output on errors. The CLI resolves a relative path against the caller's working directory, passes it to the local daemon, and never overwrites it with metadata. Vectors remain explicitly excluded; this is not disaster recovery. |
| Medium | `/admin/import` returned a successful `imported: 0` response without importing anything, while the CLI first buffered an arbitrary input file. This could produce a false recovery signal. | CLI and server now fail explicitly: HTTP 501/`NOT_IMPLEMENTED`, with an explanation that payload-only exports omit vectors. No input file is buffered. |
| Medium | Reload, automatic repair, and Qdrant-to-SQLite backfill endpoints returned success-shaped placeholders without performing the mutation. `/index/start` could bypass the dense indexer, while the no-backend `/index` compatibility path looked indistinguishable from dense success. | Unsafe placeholders now return explicit HTTP 501 with operator guidance. `/index/start` requires the dense backend and runs the production indexer. The programmatic no-backend `/index` compatibility path remains useful but explicitly returns `index_mode: lexical_only`/`dense_indexed: false`, preflights full resets, and atomically replaces per-file lexical chunks. Production startup always constructs the dense backend from validated config. Durable jobs remain roadmap work. |
| Medium | The daemon had no cheap liveness/readiness split, no overall dependency-probe deadline, no protected-work backpressure, and no request correlation. | Added public `/live`, two-second `/ready`, a two-second compatibility `/health` probe, configurable `server.max_in_flight` with immediate 503/`Retry-After`, and safe propagated/generated `x-request-id`. Tests cover each behavior. |
| Medium | `context-pack` ignored key budget fields, returned weak provenance, and could exceed a caller's practical prompt budget. It also silently accepted invalid field types/strategies, and AST source attachment could read an unbounded file. | It now validates the machine contract, requires one repository, enforces slices/tokens/bytes, bounds attached source files, truncates on UTF-8 boundaries, updates citations after truncation, deterministically deduplicates AST/FTS candidates, and returns actual included sources, bytes, digest, freshness, citation, repository/collection, and budget metadata. The CLI omits absent optional fields and requires `--repo`. |
| Medium | `/diff` ran Git synchronously on a Tokio worker, had no timeout/output/file-count bound, and converted an invalid ref, Git failure, or dense-search failure into a plausible empty result. Vocabulary JSONL was also synchronously and unboundedly buffered. | Git diff work is asynchronous, kill-on-drop, limited to ten seconds, 8 MiB, and 10,000 paths; failures propagate. Vocabulary input runs on the blocking pool and is capped at 64 MiB. Focused tests cover invalid refs and oversized input. |
| Medium | Partial indexing runs advanced the repository `last_indexed` timestamp even when source reads, deletes, flushes, state persistence, or collection counts failed. Agent freshness metadata could therefore claim a corpus was current. | Only error-free runs advance `last_indexed`; partial runs retain the previous timestamp (or `null` for a new repository). Context packs surface that conservative timestamp. |
| Medium | `cargo audit` failed on three 2026 `rustls-webpki` advisories locked through Rig's unused optional Bedrock provider. The active Ratatui graph also contained an unsound `lru` release (the affected `IterMut` API was not called here). | The agent crate now depends on provider-neutral `rig-core` with explicit features, reducing the resolved lock graph from 772 to 388 packages. Ratatui/Crossterm were deliberately upgraded to maintained releases, removing the unsound and unmaintained dependencies. A fresh RustSec scan reports zero advisories or warnings. This security update raises the workspace MSRV from Rust 1.85 to 1.88. |
| Low | Compatibility tests depended on ignored binary databases and mutated source fixtures. | SQL fixtures now materialize Python-schema SQLite databases in temporary homes. The original fixture is never opened for writes. |

## Agent-facing contract

`POST /context-pack` accepts:

- `max_slices` (1–50), `max_source_tokens` (100–100,000), and
  `max_source_bytes` (64–4 MiB);
- `use_ast_index` and `include_semantic` compatibility flags;
- a repository and query.

The response reports actual aggregate bytes/tokens, the requested budget,
deterministic retrieval metadata, freshness, and whether truncation occurred.
Each slice includes a stable citation, exact source byte count, SHA-256 of the
returned content, truncation state, and provenance. `semantic_requested` is
reported honestly; `semantic_included` is currently `false` because the native
context-pack path combines AST and SQLite FTS, not dense retrieval.
`sources_included` lists only sources that actually contributed returned
slices.

This shape is immediately useful to tool-calling agents through ordinary HTTP
and the served OpenAPI document. It does not satisfy MCP's JSON-RPC lifecycle,
capability negotiation, tool/resource schemas, or Streamable HTTP transport,
and it does not satisfy A2A's Agent Card/task semantics.

## Research and applied conclusions

Only primary/maintainer sources were used for architectural claims.

### Rust, Tokio, Axum, and Tower

- Tokio's [graceful shutdown guidance](https://tokio.rs/tokio/topics/shutdown)
  separates detecting shutdown, notifying tasks (for example with a
  cancellation token), and waiting for tasks (for example with a task
  tracker). Applied: the HTTP server and managed Qdrant stop gracefully.
  Remaining: warm-up/logging and future job tasks need one tracked shutdown
  tree rather than detached spawns.
- Tokio's [`Semaphore`](https://docs.rs/tokio/latest/tokio/sync/struct.Semaphore.html)
  and [`JoinSet`](https://docs.rs/tokio/latest/tokio/task/struct.JoinSet.html)
  support bounded, cancellation-aware work. Applied to shared Ollama
  concurrency and batched task ownership.
- Tower HTTP documents [request ID propagation](https://docs.rs/tower-http/latest/tower_http/request_id/)
  and [timeout semantics](https://docs.rs/tower-http/latest/tower_http/timeout/).
  The project keeps a small local request-ID layer to avoid a new dependency,
  and uses explicit external-client/readiness deadlines. A whole-request
  deadline remains a roadmap decision because long indexing endpoints need a
  job contract, not an arbitrary disconnect timeout.
- Rust's [`rename`](https://doc.rust-lang.org/std/fs/fn.rename.html) documents
  platform replacement differences. State and export files therefore use
  same-directory temporary files, sync, and rename; Windows replacement
  behavior still needs CI coverage.

### Qdrant and Ollama

- Qdrant states that self-hosted instances are insecure by default and
  recommends authentication, network binding, TLS, and audit logging in its
  [security guide](https://qdrant.tech/documentation/security/) and
  [production checklist](https://qdrant.tech/documentation/production-checklist/).
  Applied: loopback defaults, remote HTTPS enforcement, and environment-based
  API-key support. Audit logs, read-only/granular keys, and TLS termination are
  deployment responsibilities still to package.
- Qdrant [collection aliases](https://qdrant.tech/documentation/manage-data/collections/)
  provide atomic collection switching. Inference: full rebuild should
  eventually index a versioned collection and switch an alias, eliminating
  the remaining reset/rebuild availability window.
- Qdrant v1.18.2's official
  [Query Points OpenAPI](https://raw.githubusercontent.com/qdrant/qdrant/v1.18.2/docs/redoc/master/openapi.json)
  defines `POST /collections/{collection_name}/points/query` and a
  `QueryResponse.points` envelope. Applied to replace the removed search API.
- Qdrant [snapshots](https://qdrant.tech/documentation/snapshots/) preserve
  collection data/config but not aliases. Therefore the current payload-only
  JSONL export cannot be called a backup; production recovery needs snapshots
  plus separately captured alias/registry state.
- Official Qdrant v1.18.2 asset names, sizes, and digests come from the
  [GitHub release API](https://api.github.com/repos/qdrant/qdrant/releases/tags/v1.18.2).
- Ollama documents batch input and optional dimensions for
  [`POST /api/embed`](https://docs.ollama.com/api/embed) and installed model
  discovery through [`GET /api/tags`](https://docs.ollama.com/api/tags).
  The official [`qwen3-embedding:4b` registry metadata](https://registry.ollama.com/library/qwen3-embedding%3A4b/blobs/2b0cf8f17b4c)
  declares an embedding length of 2560, which is why the default was changed.

### Security and dependency practice

- OWASP API4:2023 covers
  [unrestricted resource consumption](https://owasp.org/API-Security/editions/2023/en/0xa4-unrestricted-resource-consumption/),
  and its [REST guidance](https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html)
  recommends type/range/length validation and request-size limits. Applied:
  the existing 2 MiB request limit is retained and new file, response,
  context, cache, concurrency, export, and retry ceilings are enforced.
- OWASP's [secrets guidance](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
  supports keeping API keys out of source/config and protecting them in
  transit. Applied to daemon-token permissions and Qdrant env/TLS handling.
- Cargo documents lockfile reproducibility and `--locked` in
  [dependency resolution](https://doc.rust-lang.org/cargo/reference/resolver.html).
  CI now checks/tests/builds locked dependencies. RustSec's
  [`cargo-audit`](https://github.com/rustsec/rustsec/blob/main/cargo-audit/README.md)
  audits `Cargo.lock`; a pinned RustSec audit action now runs in CI and weekly.
  The audit initially found three advisories in an unused provider backend and
  one reachable dependency with an unsound API. Depending directly on
  `rig-core` and updating the terminal stack removed them without a blanket
  workspace update. The relevant primary advisories are
  [RUSTSEC-2026-0098](https://rustsec.org/advisories/RUSTSEC-2026-0098),
  [RUSTSEC-2026-0099](https://rustsec.org/advisories/RUSTSEC-2026-0099),
  [RUSTSEC-2026-0104](https://rustsec.org/advisories/RUSTSEC-2026-0104),
  and [RUSTSEC-2026-0002](https://rustsec.org/advisories/RUSTSEC-2026-0002).
  The final lockfile scan is clean.

### Interoperable agent protocols (as of 2026-07-18)

- MCP's current stable specification selected for this audit is 2025-11-25.
  Its [architecture](https://modelcontextprotocol.io/docs/learn/architecture)
  defines JSON-RPC lifecycle/capability negotiation and tools, resources, and
  prompts. [Streamable HTTP](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
  includes Origin validation requirements, and the
  [tools contract](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
  supports structured content and resource links. The
  [official SDK matrix](https://modelcontextprotocol.io/docs/sdk) lists Rust as
  Tier 2. Build decision: implement a thin adapter only after the native
  context schema is stable; do not mislabel the current REST endpoint as MCP.
- MCP [tasks](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks)
  remain experimental in this stable spec. Build decision: do not base core
  indexing durability on MCP tasks.
- A2A v1.0 defines Agent Cards, tasks, messages, artifacts, and streaming in
  its [official specification](https://github.com/a2aproject/A2A/blob/main/docs/specification.md).
  Inference: A2A becomes useful when this product has durable, cancellable
  long-running jobs and delegation; adding an Agent Card now would overstate
  capability, so it is deferred.

## Performance and retrieval quality

This change deliberately prioritizes integrity and bounded memory over a
microbenchmark-only latency win. Context ordering is deterministic and tests
assert byte/token ceilings and digests. Failed incremental paths now retry
rather than silently claiming success, which can do more work but preserves
retrieval correctness.

The initial acceptance run protected a concurrent benchmark in the original
checkout and therefore used mocks. A subsequent user-requested benchmark ran
the audited release with an isolated home and port against the same read-only
46,121-point Signal-Android index and shared services. The full comparison,
raw artifact hashes, controlled previous-binary A/B, and limitations are in
[`docs/benchmark_rust_production_audit/summary.md`](benchmark_rust_production_audit/summary.md).
Retrieval quality matched the saved Rust results. A 30-answer `/ask` run also
matched saved coverage/precision, with 9.16 s mean and 18.33 s p95 latency.

Final gate timings and a focused release-mode context-pack correctness check
are recorded in the verification section. Timings on this host are not
portable and are not retrieval-quality claims.

## Intentional contract and migration notes

- New homes default to `qwen3-embedding:4b`/2560. Existing `config.toml` files
  are not rewritten; change the former model string manually before indexing.
- Remote plaintext Qdrant URLs now fail client construction. Use HTTPS, or a
  loopback URL for local development.
- Remote plaintext Ollama URLs also fail client construction because source
  context is sent to embedding/generation APIs. Put remote Ollama behind HTTPS.
- Set Qdrant credentials in `QDRANT_API_KEY` or change
  `qdrant.api_key_env`; an empty name disables header loading.
- Embedded mode no longer adopts an unknown service on its port. Choose
  `qdrant.mode = "server"` when reuse is intentional.
- An old regular `~/.rag/bin/qdrant` without the new integrity sidecar is
  replaced by the pinned verified release at the next embedded start. A
  symlink/device at the managed binary or checksum path is rejected.
- Rust `smart-search` rejects `repos`. Send one request per repository until a
  bounded fan-out/merge implementation lands.
- `/admin/export` is payload JSONL without vectors. It is an interchange/debug
  export, not a restorable Qdrant backup. It stops at one million records or
  1 GiB and reports truncation; CLI relative paths are resolved in the caller's
  working directory.
- `/admin/import` now returns HTTP 501 instead of the former false-success
  placeholder. Use a Qdrant snapshot-based recovery process when implemented.
- `/admin/reload`, `/admin/repair`, and `/index/backfill-code-index` also return
  501 rather than claiming a mutation occurred. Restart, verified reindex, or
  snapshot restore are the explicit operator paths.
- `/health` remains compatible; supervisors should migrate to `/live` and
  `/ready`.
- Building from source now requires Rust 1.88 or newer. This targeted MSRV bump
  permits Ratatui 0.30, which removes the audited unsound terminal dependency.
- Source indexing defaults to a configurable 4 MiB limit, AST attachment has a
  4 MiB hard limit, and vocabulary JSONL is capped at 64 MiB. Increase the
  configurable source-file limit only after sizing memory/concurrency.

## Remaining risks, in priority order

1. **Staged full rebuilds:** full indexing is now fail-closed, but it still
   resets then rebuilds a live collection. Use versioned collections plus an
   atomic Qdrant alias switch and garbage collection.
2. **Durable cancellable jobs:** indexing routes remain request-shaped and the
   inherited job APIs are incomplete. Add persisted state transitions,
   idempotency keys, cancellation, bounded queues, and a tracked shutdown tree.
3. **Multi-tenancy:** the bearer token represents one local trust domain.
   There is no tenant principal, row/collection policy, per-tenant key, quota,
   or deletion proof. Do not expose this daemon as shared SaaS.
4. **Backup/recovery:** implement Qdrant snapshots plus SQLite/alias manifests,
   encryption, retention, checksum verification, and restore drills.
5. **Observability:** request IDs exist, but logging still includes synchronous
   file writes and lacks rotation-safe structured tracing, metrics, queue
   depth, saturation, and per-dependency latency histograms.
6. **Process/subprocess cancellation:** model warm-up is detached; some AST/git
   integrations use subprocesses or blocking filesystem work without one
   system-wide cancellation policy.
7. **Retrieval evaluation:** add a versioned golden corpus with recall@k,
   MRR/nDCG, citation validity, freshness, and budget adherence gates. Existing
   reports are useful snapshots but not continuous quality protection.
8. **Documentation deletion tracking:** incremental docs indexing atomically
   replaces changed files but has no per-file state manifest, so removed docs
   persist until a full docs rebuild. Add state/diff parity with code indexing.
9. **Cross-platform verification:** Linux is exercised here. macOS service and
   embedded-Qdrant paths need CI/runtime coverage; Windows is not packaged and
   rename/permission semantics differ.
10. **Dependency duplication:** provider-neutral `rig-core` still brings
   reqwest 0.13 alongside the workspace's reqwest 0.12, plus several duplicate
   transitive versions. The optional provider explosion is gone, but the two
   HTTP stacks should converge when their public APIs permit a focused update.
11. **Protocol adapters:** build MCP after native schemas and authorization are
    stable; defer A2A until durable jobs/delegation exist.
12. **Filesystem race boundary:** Unix final-component source opens use
    `O_NOFOLLOW`, but a hostile process with write access to repository parent
    directories can still swap an ancestor between validation and open. A
    capability/openat-style traversal is required for a stronger boundary.
13. **Ungraceful managed-process exit:** normal shutdown and failed startup
    kill the managed Qdrant child. `SIGKILL`/power loss can orphan it; the next
    embedded start intentionally refuses to adopt the unknown occupant, so the
    operator must stop it or select server mode. Service managers should kill
    the complete process group.

## Verification record

Final verification used a warm Cargo cache unless noted. All commands ran in
this worktree on the baseline host described above:

- `cargo fmt --all --check`: **pass**; 0.20 s; peak RSS 50,348 KiB.
- `cargo check --locked --workspace --all-targets`: **pass**; 0.67 s; peak RSS
  307,908 KiB.
- `cargo clippy --locked --workspace --all-targets --all-features -- -D warnings`:
  **pass with zero warnings**; 1.18 s; peak RSS 368,604 KiB.
- `cargo test --locked --workspace --all-targets`: **pass**; 121 passed, 0
  failed, 0 ignored/skipped, 0 measured; 5.35 s; peak RSS 1,128,412 KiB. This
  includes compatibility fixtures, captured contracts, mock Ollama/Qdrant
  integration tests, temporary SQLite tests, and the dashboard/CLI tests.
- `cargo +1.88.0 check --quiet --locked --workspace --all-targets`: **pass**;
  1.06 s; peak RSS 423,112 KiB, verifying the declared MSRV.
- `cargo build --locked --release -p rag-app`: **pass** from a cold release
  target; 125.50 s; peak RSS 1,532,764 KiB. The resulting Linux x86-64 ELF is
  32,012,944 bytes, and `env -i PATH=/usr/bin:/bin ./target/release/rag-rs
  --version` passed with `rag-rs 0.1.0` and no Python environment.
- `cargo audit`: **pass**; 388 locked dependency packages scanned, 0
  vulnerabilities and 0 warnings; 2.58 s; peak RSS 105,696 KiB.
- `cargo tree --locked --workspace --all-features --duplicates`: **pass** and
  reviewed. The remaining dual Reqwest graph is recorded as a risk above.
- Contract JSON parsed with `jq`, CI YAML parsed with PyYAML, and `git diff
  --check` passed.
- `cargo test --locked --release -p rag-server --lib
  context_pack_enforces_byte_budget_with_provenance_deterministically`:
  **pass**; 1 passed, 0 failed/ignored. Its 54.83 s wall time was dominated by
  release test compilation and is not presented as endpoint latency.

The complete acceptance command set was:

```text
cargo fmt --all --check
cargo check --locked --workspace --all-targets
cargo clippy --locked --workspace --all-targets --all-features -- -D warnings
cargo test --locked --workspace --all-targets
cargo +1.88.0 check --locked --workspace --all-targets
cargo build --locked --release -p rag-app
cargo tree --locked --workspace --all-features --duplicates
cargo audit
```

At initial acceptance, local read-only probes found Qdrant 1.18.2 and Ollama,
but only the older `qwen3-embedding:latest`/4096 model was installed. Live
indexing was not attempted and remains unverified. The later isolated benchmark
used that existing model/index deliberately for comparison, exercised live
Qdrant/Ollama retrieval, readiness, and graceful daemon shutdown, and left the
collection count unchanged at 46,121. It did not pull a model or write/reset a
collection. Its saved Python/previous-Rust comparison is separate from the
non-comparable cold/warm Cargo gate timings above.
