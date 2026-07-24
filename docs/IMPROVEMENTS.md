# Project review and evolution plan

Reviewed 2026-07-24 against the working tree of branch `rust-migration`
(9 crates, 20 529 lines of Rust, 88 tests). Supersedes the previous
Python-era backlog, which referenced `core/scoring.py`, `.venv/bin/ruff` and
pytest gates that no longer exist.

## Baseline: what is actually true today

Verified by running the gates, not by reading docs:

| Gate | Result |
| --- | --- |
| `cargo fmt --check` | clean |
| `cargo clippy --workspace --all-targets -- -D warnings` | clean |
| `cargo test --workspace` | 88 passed, 0 failed, 0 ignored |
| `target/release/rag-rs` | 32.4 MB, 771 crates in the dependency graph |

The engineering that is genuinely strong: the workspace dependency direction
holds (`contracts <- config/storage/index/retrieval/services/agent <- server
<- app`), `unsafe_code = "forbid"` is workspace-wide, blocking SQLite work
consistently goes through `spawn_blocking`, the never-500 planner contract is
real (`plan_query` always falls back to `fallback_plan`), the incremental
indexer's language-scoped diff is genuinely subtle and correct, and the
Python-parity comments are precise enough to audit against.

The problems below are ranked by expected damage, not by effort.

---

## P0 — The work is not durably stored

**P0.1 — The entire Rust migration is uncommitted.**
`git diff --cached --stat` reports 133 files / 33 374 insertions staged.
`HEAD` on `rust-migration` is `9fa1ea9`, which is still the Python tree
(`git ls-tree HEAD` shows `src/`, `pyproject.toml`, `uv.lock` and no
`crates/`). The branch has no upstream — `git for-each-ref
refs/heads/rust-migration` shows an empty tracking ref, and `origin` is
`git@gitverse.ru:ncit/coderagsystem.git`. Months of work exist on exactly one
disk, in an index that any `git reset` discards.

**P0.2 — Committing the index as it stands produces a tree that does not
build.** `crates/rag-app/src/tui.rs` is staged, but the TUI that replaced it —
`crates/rag-app/src/tui/{mod,ui,data}.rs`, 2 078 lines — is **untracked**, as
is `crates/rag-server/src/stack.rs` (480 lines, and `rag-server/src/lib.rs:6`
declares `pub mod stack;`). Rust rejects a crate with both `tui.rs` and
`tui/mod.rs` present (E0761), and a missing `stack.rs` fails the `mod`
declaration outright. So the first commit would be broken in two independent
ways.

Fix, in order:

```bash
git rm --cached crates/rag-app/src/tui.rs
git add crates/rag-app/src/tui crates/rag-server/src/stack.rs
git status --porcelain -uall | grep '\.rs$'      # must be empty
git stash --keep-index && cargo build --release -p rag-app && git stash pop
git commit
git push -u origin rust-migration
```

Then verify the commit independently: `git clone . /tmp/verify && cd
/tmp/verify && cargo test --workspace`. A clean-clone build is the only proof
that nothing load-bearing is still untracked.

**P0.3 — The Python source is still in the repository.** `git ls-files src/`
returns 47 tracked `.py` files, and `pyproject.toml` / `uv.lock` are tracked
at HEAD. The staged deletions cover `tests/eval/*.py`, `scripts/*.py` and
`tools/serena_server.py`, but not `src/rag/`. `CLAUDE.md:5-7` states "the
Python source has been removed" — that is not true of this tree. The worktree
also carries `.venv` (240 MB), `.pytest_cache` and `.ruff_cache`.

---

## P1 — Correctness and resource defects

**P1.1 — Unbounded in-process embedding cache (memory leak in a long-lived
daemon).** `crates/rag-services/src/ollama.rs:109` holds
`Arc<RwLock<HashMap<String, Vec<f32>>>>`, and `cache_embeddings` defaults to
`true` (`ollama.rs:52`); `RetrievalBackend::from_settings` inherits that
default via `..OllamaConfig::default()`. Every document embedded during
indexing is retained for the process lifetime: key = the full instruction-
prefixed chunk text, value = 2560 × f32 = 10.24 KB (`default.toml:11`).
A 50 000-chunk repository leaves roughly 600–700 MB resident in a daemon
`rag service install` keeps running for weeks. It is also redundant on the
indexing path, which already consults the durable SQLite `EmbedCache`
(`indexing.rs:712`) and writes through to it (`indexing.rs:747`).

Fix: construct the indexing-path client with `cache_embeddings: false`, or
replace the map with a bounded LRU sized for queries only (a few thousand
entries). Verify with RSS before/after a full index of a large repo.

**P1.2 — 15 % of the ranking formula is permanently zero.**
`rag-retrieval/src/lib.rs:13` sets `RECENCY_WEIGHT = 0.15` and
`recency_score` (lib.rs:55) reads `payload["git_last_modified"]`. A
workspace-wide grep for that key returns exactly one hit — the read. Nothing
writes it. Every hit scores 0.0 on recency, so the weight is dead and the
remaining weights are effectively renormalised by accident.

Fix (pick one, don't leave it as-is): either stamp the field in
`indexing.rs::process_file` from a single `git log --format=%aI --name-only`
pass per index run (one subprocess, not one per file), or delete
`RECENCY_WEIGHT`/`recency_score` and re-tune the remaining weights against
`bench/`.

**P1.3 — Two divergent implementations of the same endpoints, indistinguishable
to clients.** The live dense pipeline lives in `rag-server/src/retrieval.rs`;
a parallel SQLite keyword implementation of the same routes lives in
`rag-server/src/lib.rs` (`live_search` :770, `live_smart_search` :1442,
`live_ask` :1534, ~700 lines total). They return the same JSON contract with
materially different quality. `live_search` loads up to 100 000 chunks into
memory and substring-scores all of them per query (lib.rs:779, 830).
`live_ask` synthesises an answer string from the top hit and labels it
`"model": "deterministic-fallback"` — the only signal a caller gets, and only
on that one route.

Fix: add an explicit `retrieval_mode: "dense" | "lexical_fallback"` field to
every degraded response, then delete the fallback bodies that no longer earn
their maintenance cost. The daemon already returns `BACKEND_NOT_READY` for
most routes (`lib.rs:1955`); extending that to `/search` and `/smart-search`
is more honest than answering badly.

**P1.4 — `/` hands the bearer token to any unauthenticated loopback caller.**
`dashboard` (lib.rs:511) substitutes the token into the served HTML, and the
route is registered on the public router (lib.rs:178) — before
`.merge(protected)`. The token file is 0600, but `curl 127.0.0.1:7890/` from
any local process or user recovers it. DNS rebinding is blocked by
`trusted_host` and cross-origin reads by the absent CORS headers, so this is
acceptable on a single-user laptop and a real privilege downgrade on the
shared GPU box.

Fix: issue a short-lived session token for the dashboard instead of the
long-lived daemon token, or add a `server.dashboard = false` setting for
multi-user hosts.

**P1.5 — `/admin/export` is an authenticated arbitrary-file-write primitive.**
`retrieval.rs:258` does `std::fs::write(output, ...)` with `output` taken
verbatim from the request body. Constrain it to `~/.rag/exports/` and reject
paths that escape after canonicalisation.

**P1.6 — Rate-limit map never evicts.** `consume_rate_limit` (lib.rs:2123)
inserts into `rate_windows` per bearer value and never removes expired
entries. Bounded in practice by a single fixed token; unbounded if tokens ever
rotate. Sweep entries older than the window on insert.

**P1.7 — Lock poisoning panics request handlers.** `push_event` (lib.rs:104)
and `consume_rate_limit` (lib.rs:2125) `.expect("... poisoned")`. One panic
anywhere holding those mutexes converts every subsequent request into a 500 on
a daemon whose stated contract is "never 500". Use `unwrap_or_else(|e|
e.into_inner())` — event loss is preferable to a permanently wedged daemon.
There are 81 `.unwrap()/.expect()` sites in library code, 27 of them in
`rag-server/src`; the two above are the ones on the hot path.

---

## P2 — Architecture debt

**P2.1 — The "Rust-only, three runtime dependencies" claim is false; symbol
navigation shells out to a Node.js CLI.** `rag-retrieval/src/ast_index.rs:83`
and `:87` invoke `ast-index` as a subprocess — currently resolved to
`~/.nvm/versions/node/v22.22.2/bin/ast-index`. It backs `/resolve`,
`/graph/node`, `/graph/callers`, `/graph/callees`, `/graph/impact`,
`/call-tree`, `/context-pack` and the structural stage of `/smart-search`
(several subprocesses per request there). `README.md:16-30` lists three
runtime dependencies and does not include it, and `CLAUDE.md` mentions it only
as an implementation note.

Worse, its absence is silent: every entry point guards on `is_available()`
(ast_index.rs:229, 308, 585, 611, 689) and returns empty results. Nothing in
`/health`, `/health/detail`, `/diagnose` or `/stack` reports it, so a machine
without Node gets an apparently healthy daemon whose navigation answers are
uniformly empty.

This is the largest remaining migration debt. Two-step fix below (P2 short
term, Phase 4 long term).

**P2.2 — The `rig` provider layer is reachable only from tests.**
`rag-agent/src/lib.rs:1077-1160` defines `openai_planner`,
`anthropic_planner`, `gemini_planner`, `ollama_planner` and the matching
`*_ask_generator`s. The only non-test callers are in
`tests/rust-compat/r5/mod.rs`; `plan_query` (retrieval.rs:906-935) matches on
`"ollama"` and `"agy"` and comments that "other Rig providers are not wired
into this daemon". Meanwhile `default.toml:60` advertises
`provider="gemini"` as a supported fallback — configuring it silently yields
the heuristic plan. `rig` plus its four provider clients is a large share of
the 771-crate graph and the 32 MB binary.

Fix: either wire the providers into `plan_query` (the config already promises
them) or put `rig` behind a non-default `cloud-planners` cargo feature and
drop the promise from `default.toml`. Pick one — the current state is the
cost of both with the benefit of neither.

**P2.3 — `rag-server/src/lib.rs` is a 2 434-line god module with untyped
dispatch.** It holds the router, four middlewares, auth, the JSONL logger,
~15 route implementations, the contract fixtures and hand-rolled validation.
`generic_post` (lib.rs:551) dispatches on `request.uri().path()` string
matches, so request and response bodies are `serde_json::Value` end to end and
the compiler checks nothing. The FastAPI-compatible 422 shape is reproduced by
hand in `validate_request_contract` (lib.rs:2019), which is why bounds like the
`/ask` top_k ceiling live in a match arm rather than on a type.

Fix incrementally: define typed request/response structs in `rag-contracts`,
convert one route per commit to a real Axum handler with `Json<T>` extractors,
and let the derived rejection produce the 422. `/search` and `/smart-search`
first — they carry the contract tests.

**P2.4 — `contract_fixtures` is a mode in which the server returns canned
JSON as live data.** `fixture()` (lib.rs:1981) serves checked-in
`tests/contracts/*.json`. One test guards the leak
(`production_mode_never_returns_captured_results_as_live_data`, lib.rs:2361).
It works, but it is one refactor away from shipping fixtures to users. Move
the fixture surface behind `#[cfg(feature = "contract-fixtures")]` so it
cannot exist in a release build at all.

---

## P3 — Tests, CI, hygiene, product surface

**P3.1 — The two highest-value code paths have no unit tests.** 88 tests for
20 529 lines is thin, but the distribution is the real problem:
`smart_search_route` (retrieval.rs:456-863, ~400 lines: inference →
grounding → resolve → usage trim → structural expansion → candidate
pagination) and `index_route` (indexing.rs:125-427, ~300 lines: language-
scoped diff, stale-chunk deletion, per-batch hash promotion, partial-failure
recovery) are both untested. Both are hand-rolled, both are subtle, and both
are where a silent regression costs the most.

Fix: a fake Qdrant + fake Ollama pair in `rag-services` behind a `test-doubles`
feature, then table tests for: language-filtered runs leaving other languages'
chunks intact; a failed flush dropping only that batch's hashes; changed files
deleting their stale chunks before re-upsert; candidate pagination math and
`candidates_total`; `include_bodies=false` stripping `code`; blast-radius
phrasing bumping `usages_limit` to 100.

**P3.2 — CI has no live-service job, no benchmark gate, no dependency audit.**
`.github/workflows/ci.yml` runs fmt, clippy, test, release build and a
Python-free smoke test — good, and the smoke test with `env -i` is a nice
touch. Missing: an integration job with Qdrant + a small Ollama model
(services containers), a benchmark regression check against `bench/`
artifacts, and `cargo deny check` / `cargo audit` over 771 dependencies.

**P3.3 — `rag install-agent` is broken.** `main.rs:505` executes
`scripts/install-codex-skills.sh`, which this branch deletes; `scripts/` now
contains only `build-rust-release.sh`. Remove the subcommand or restore the
script.

**P3.4 — Repository weight.** `ragsystem.pen` (1.2 MB) and ~800 KB of
`vocab_*.jsonl` are tracked in git (the `.gitignore` rule `/vocab_*.jsonl`
was added after they were committed, so it has no effect on tracked files).
`.venv` (240 MB), `.pytest_cache`, `.ruff_cache`, `.qoder`, `.gemini` sit in
the worktree.

**P3.5 — Product gaps carried over from the parity audit** (still accurate):
`/index` is synchronous with no progress despite `/index/progress/{job_id}`
existing as a stub (lib.rs:662) and `rag-index/src/jobs.rs` defining an unused
`IndexJob`; no file watcher; no plugins; LOD/summary and vocab collections are
consumed by search but never generated by the Rust indexer; `/graph/callees`
is a regex source scan (lib.rs:1013) rather than a real call graph.

---

## Evolution plan

Six phases. Each has a verification gate; nothing moves to the next phase with
a red gate. Phases 0–2 are sequential; 3–6 can be reordered by appetite.

### Phase 0 — Secure the work — ✅ DONE 2026-07-24

1. ✅ Index fixed and committed as `567e410`: obsolete `tui.rs` dropped, the
   real `tui/{mod,ui,data}.rs` and `stack.rs` added, `.claude/scheduled_tasks.lock`
   and `.qdrant-initialized` unstaged and gitignored. Tag `python-final`
   marks the last Python tree.
2. ✅ Python runtime removed in `b3b9909` (`src/rag/`, `pyproject.toml`,
   `uv.lock`, `tools/`); `ragsystem.pen` and `vocab_*.jsonl` untracked but
   kept on disk. `CLAUDE.md`'s "the Python source has been removed" is now
   true. The only remaining `.py` in tracking is
   `tests/rust-compat/r3/fixtures/sample.py` (chunker *input* data) plus
   `bench/` dev harnesses, which is the existing convention.
3. ✅ Not pushed — owner's call; the branch is deliberately local-only, so
   the single-disk risk is reduced (recoverable from git) but not eliminated.

**New defect found by the gate — `76e0c4a`.** The clean-clone build failed
where the in-place worktree passed: `.gitignore`'s blanket `*.db` rule had
silently excluded `tests/rust-compat/r1/python-rag-home/{rag,repos}.db`, the
fixtures `r6_contract::live_search_reads_a_copied_python_created_database`
depends on. Without them the registry lookup fails and the route returns 503
instead of 200. `cargo test --workspace` therefore passed *only* on machines
that already had the files — CI would have failed on first push. Fixed by
negating the rule (`!tests/rust-compat/**/*.db`) and tracking the fixtures.

The lesson generalises: **an in-place worktree cannot verify a commit.** Only
`git clone . /tmp/x && cd /tmp/x && cargo test --workspace` can.

**Gate:** ✅ clean clone of `b3b9909` passes `cargo test --workspace`
(88 passed, 0 failed), `clippy -D warnings`, and `fmt --check`.

### Phase 1 — Tell the truth — ✅ DONE 2026-07-24 (`a3ae2bf`)

4. ✅ `/stack` carries an `AST-INDEX` card (probe cached 300 s behind a 5 s
   timeout, so the 12 s dashboard poll costs ≤1 subprocess per five minutes).
   Both dashboards render it — TUI card row went 4→5 columns plus a header
   dot, web dashboard got a card and dot. README's runtime-dependency section
   now states the real set and what degrades without it.
   **Correction to P2.1 above:** `ast-index` is `@ast-index/cli`, a *native
   binary* distributed through npm behind a 53-line Node launcher shim — not a
   Node program. Node is needed only to run the shim. This matters for Phase 4
   scoping.
5. ✅ `retrieval_mode` (`"dense"` / `"lexical_fallback"`) added to both paths.
6. ✅ `rag install-agent` removed, not repaired: it exec'd a script the
   migration deleted, by *relative* path, and needed the repo's `skills/`
   directory — so it could never work from an installed binary anyway.
7. ✅ Done in Phase 0.

**Gate:** ✅ verified empirically both ways — card reads `ok` with the CLI on
PATH, `warn` with the install hint when removed (this box has two installs,
`~/.nvm/.../bin` and `/usr/local/bin`; both must go to test the absent case).

### Phase 2 — Correctness and resource fixes — ✅ DONE 2026-07-24 (`a13ca2e`)

8. ✅ Embedding cache: `embed_documents` now bypasses it entirely (SQLite
   already owns that durability); `embed_query` still caches, bounded FIFO at
   2048 entries. **Unbounded → 20.0 MiB hard ceiling.**
9. ✅ Recency populated, not deleted — and the decision was validated rather
   than assumed. On a live corpus the term is genuinely discriminating (3 % of
   files score 0.0, the rest spread across 0.00–0.15), and a real top-10
   result band is only 0.072 wide with adjacent gaps of 0.002–0.017. A term
   worth up to 0.15 is wider than the entire band it reorders.
10. ✅ Export path confined, rate-limit map swept and capped, poisoning
    recovery on both request-path mutexes.
11. ⏸️ Dashboard token model (P1.4) **not done** — deferred, see below.

**Gate:** ✅ clean clone of `a3ae2bf`: fmt clean, clippy 0 issues, 111 tests
(was 88), release build + empty-env smoke pass, and the working tree stays
clean after a full test run.

### Newly found during Phase 1–2 (were not in the original review)

- **`rag export` could never have worked.** The CLI sent no `output` field,
  which the route required → every invocation died on a 422; and the live
  route omitted the `records` the declared contract shape promises, so even
  past that it wrote a file with no data. Fixed both ends: `output` is now
  optional, `records` is always returned, the CLI writes them to the user's
  path (which also works when the daemon is not on the caller's machine).
- **`docs/guides/NEW_PC_SETUP.md` documented a system that does not exist** —
  a persistent index-time LSP client pool computing `fan_in`/`dead_code_candidate`.
  `lsp.rs` exposes exactly one function, `detect_lsp_servers`, a PATH probe;
  the `[lsp]` config keys are parsed and ignored. Those enrichment fields are
  real but come from static tree-sitter analysis. The guide also said
  `cargo install ast-index` (an unrelated crate) and told users to install
  Python + `uv`. `docs/deployment-linux.md` still shipped a systemd unit
  running `.venv/bin/python -m rag start`.
- **The r6 contract test mutated its own checked-in fixture** on every run,
  dirtying the tree. Now copies into a tempdir.
- **Lexical hits carry no enrichment payload** (`promote_lexical_hits`,
  retrieval.rs ~1250): FTS-promoted hits build their payload from SQLite
  columns only, so they score 0.0 on recency *and* patterns *and* quality
  while dense hits carry the full Qdrant payload. Pre-existing and untouched —
  it systematically under-ranks lexical evidence. Worth a decision in Phase 6
  alongside the RRF work.
- **`docs/wiki/` is auto-generated and stale** — it still links
  `scripts/install-codex-skills.sh` as though it existed.

### Phase 2 — Correctness and resource fixes (3–5 days)

8. Bound or bypass the in-process embedding cache (P1.1).
9. Resolve the recency term — populate or delete (P1.2).
10. Constrain `/admin/export` paths (P1.5); sweep the rate-limit map (P1.6);
    replace poisoning `.expect()`s on the request path (P1.7).
11. Decide on the dashboard token model (P1.4).

**Gate:** RSS after a full index of a 50k-chunk repo stays flat across a
second run; `bench/` numbers unchanged or better after the recency decision.

### Phase 3 — Make the core testable — ✅ DONE 2026-07-24

12. ✅ **Deviation from this plan:** no cargo feature was added. The existing
    r2 test already establishes the better pattern — spawn an in-process axum
    mock per test file — and the dev-dependencies were already present, so a
    shared feature-gated double would have added coupling for nothing.
13. ✅ `15f6044` — 19 tests, 88 → 135 workspace total. Both suites drive the
    real HTTP surface, and the Qdrant double is a real point store rather than
    a call recorder, so invariants are asserted on surviving state.
14. ✅ `138db9e` — `cargo deny` (`advisories ok, bans ok, licenses ok,
    sources ok`), a live-Qdrant integration job, and clean-checkout hygiene
    checks.

**Gate:** ✅ exceeded. 36 mutations (19 indexer, 17 smart-search) were each
confirmed to turn the relevant test red and then reverted. Clean clone of
`18e6b31`: fmt clean, clippy 0 issues, 135 passing / 0 failed, release build
and empty-env smoke pass, no tracked-but-ignored files, tree clean after a
full test run.

### Found during Phase 3

- **Caller-controlled panic — fixed (`4b6cad8`).** `ast_index::resolve_symbols`
  sized its over-fetch pool with `(limit * 3).clamp(limit, 200)`, and
  `Ord::clamp` panics when min > max, so any limit above 200 panicked.
  Reachable from `/smart-search` (`usages_limit` was read unclamped, unlike
  every sibling limit) and `/resolve` (neither limit was). It surfaced as a
  503 `BACKEND_NOT_READY` because `spawn_blocking`'s JoinError is absorbed as
  a backend outage — so a bad request looked like an infrastructure failure.
- **`repos` was validated but never read — fixed (`4b6cad8`).** A `repos`
  request returned 200 having searched the *default* collection while
  reporting `repos_searched: []`. Single-element `repos` now resolves; longer
  lists get an explicit 422 until cross-repo is ported.
- **The packaged default config cannot work.** `default.toml` ships
  `model = "Qwen/Qwen3-Embedding-4B"`, `dim = 2560` — that is the HuggingFace
  name, not an Ollama tag, so `model_is_present()` fails and a fresh install
  reports `ollama: unavailable` with Ollama running perfectly. The failure
  names the wrong component. **Not yet fixed.**
- **`rig` is ~half the dependency graph, for code only tests call.** Confirmed
  against P2.2: `reqwest 0.13.4`'s sole parent is `rig-core`, so the binary
  links two `reqwest` majors; rig's subtree spans 142 of the 277 crates in
  the shipped binary. `plan_query` still only wires `"ollama"` and `"agy"`.
- **A flaky test was a test bug — fixed (`18e6b31`).**
  `agy_timeout_cleans_up_process_tree` probed `kill -0` immediately after the
  timeout, asserting the kernel had already run the group kill. It failed
  under parallel load and passed alone, which is what "known flaky" was
  recording. Now a bounded poll; still fails if `.process_group(0)` is removed.
- **Three sharp edges reported, not fixed** (they are contract decisions):
  a run-lock conflict returns 503 rather than 409 and loses its message; a
  nonexistent `repo_path` also returns 503 rather than 4xx; and the per-repo
  lock is process-local, so the "Python parity: flock" comment overstates it —
  only the fail-fast semantics match, not the cross-process scope.
- **`include_semantic: false` silently changes pagination** (it drops semantic
  entries from `candidates` and shrinks `candidates_total`). Clients wanting
  "links, not bodies" want `include_bodies: false`. Worth a doc line.

### Phase 5 — Slim and harden — ⏳ IN PROGRESS

18. ✅ **rig gated** (`7e0d41f`). It was never reachable at runtime: `plan_query`
    matches only `"ollama"` (plain `OllamaClient`) and `"agy"` (subprocess).
    Measured A/B from identical snapshotted source into empty target dirs:

    | | before | after |
    | --- | --- | --- |
    | crates in the binary graph | 277 | **239** |
    | release binary | 32,496,192 B | **30,646,352 B** (−1.76 MiB) |
    | clean build | 164.8 s | **107.9 s** (−34.5 %) |
    | `cargo deny` duplicates | 10 | **5** |

    **Correction to P2.2 above:** it claimed rig spanned "142 of 277 crates".
    That was its *subtree*, most of it shared with tokio/hyper/serde; the
    **exclusive** contribution is 38. Gone: `rig*`, `reqwest 0.13.4` (the
    binary linked two reqwest majors), `h2`, the `futures` family,
    `toml_edit`/`winnow`, and `aws-lc-rs`/`aws-lc-sys` — a C crypto library
    built from source, which is most of the build-time saving.
19. ⬜ Contract fixtures still compile into release builds.
20. ⬜ Typed handlers not started.

### Phase 6 — Product surface — ⏳ IN PROGRESS

21. ⏳ Async index jobs — in flight.
22. ⚠️ **RRF is under-specified in this plan and must not be implemented
    literally.** RRF is rank-space (`1/(60+rank)` ≈ 0.016); the recency,
    pattern and quality boosts are additive in score-space at up to 0.15.
    Swapping the lexical squash for RRF without re-tuning the boosts would
    let them dominate the fused score by roughly 10×. Doing it properly means
    re-tuning both together against `bench/`, which needs live Qdrant +
    Ollama + indexed corpora. Deferred rather than guessed at.
23. ⬜ Vocab freshness.
24. ⬜ Branch-switch reindex.

### Also fixed along the way

- **Lexical hits carried no enrichment** (`a6eca68`) — the asymmetry noted at
  the end of Phase 3. `code_index` stores only structural columns, so every
  FTS hit scored 0.0 on recency *and* pattern *and* quality while dense hits
  carried the full Qdrant payload: a systematic penalty of up to 0.30 against
  a top-10 band measured at 0.072 wide. Fixed with a new
  `QdrantClient::retrieve` (deterministic uuid5 ids ⇒ one round trip).
- **`/diagnose` had never done anything** (`17cd506`) — hard-coded
  `{"status":"degraded","checks":[]}` on every call, while the README told
  users to run it to check for `ast-index`. Now a real projection of the
  `/stack` probes plus a config-sanity check.
- **Misleading 503s** (`17cd506`) — index-lock conflict → 409, bad
  `repo_path` → 422; genuine outages still 503.
- **The packaged default config could not work** (`72d7a32`) — a HuggingFace
  path where an Ollama tag was required, so a fresh install reported
  `ollama: unavailable` against a healthy Ollama. Six parsed-but-ignored
  config keys documented at the same time.

### Phase 4 — Retire the Node.js dependency — ⏳ IN PROGRESS

**Foundation landed** (`65f8fa4`): `crates/rag-index/src/symbols.rs` extracts
definitions, references and edges straight from the tree-sitter parse, with
four collection-scoped tables in the existing `rag.db`. Validated on
Signal-Android — 5,598 files → 77,220 definitions / 964,381 references /
356,292 edges in 28 s, 0.29 GB; resolve 65 µs, callers 230 µs. Wiring is in
flight. Known gaps to plan around: no cross-file resolution (parity with the
CLI, but `/graph/impact` will be noisy for common names), no fuzzy `search`
verb, Go `implementations` always empty (structural interfaces), C/C++
partial.

15. Build a native symbol index in `rag-index`. The raw material is already
    there: tree-sitter parsers for ten languages (`chunker.rs:328`), name-node
    resolution (`chunker.rs:515`), and an `AstGraph` with callers/callees/
    traverse already written and currently used only by a compat test
    (`rag-index/src/graph.rs`). Persist definitions/usages/edges into the
    existing SQLite database beside the code index.
16. Swap `ast_index.rs`'s subprocess bridge for the native index behind a
    config flag, keeping the CLI path as fallback for one release.
17. Delete the bridge once the benchmark matrix shows parity.

**Gate:** `bench/` navigation modes (resolve, callers, impact, smart-search)
match or beat the current ast-index numbers, with `ast-index` uninstalled.

This phase is what makes the README's "single binary, three dependencies"
claim true, removes one subprocess spawn per navigation request, and unblocks
`graph_walk` as a real strategy instead of a degradation to hybrid
(`retrieval.rs:1130`).

### Phase 5 — Slim and harden (about a week)

18. Decide `rig`: wire the providers or feature-gate them (P2.2).
19. Feature-gate the contract fixtures out of release builds (P2.4).
20. Begin typed handlers in `rag-server`, `/search` and `/smart-search` first
    (P2.3).

**Gate:** release binary and dependency count both measurably down; contract
tests still green.

### Phase 6 — Product surface (ongoing)

21. Async index jobs with real progress — `jobs.rs` and
    `/index/progress/{job_id}` already exist as scaffolding.
22. Reciprocal-rank fusion to replace the hand-tuned lexical squash
    `0.75·raw/(raw+3)` (`rag-retrieval/src/lib.rs:148`), guarded by `bench/`.
23. Vocab freshness: store the source file's content hash in each vocab point
    (`indexing.rs:536` already writes `content_hash`) and add a
    `/vocab/refresh` diff route so summaries stop going stale silently.
24. Branch-switch reindex: watch `.git/HEAD` and `.git/refs` alongside file
    mtimes.

---

## Explicitly not recommended

- **MCP server** — previously decided against; the low-token path stays the
  `rag` CLI plus skills.
- **Re-adding a cross-encoder reranker** — removed deliberately from both
  stacks; `SearchRequest.rerank` stays accepted-and-ignored.
- **Reviving the deleted Python benchmark scripts** — only the planner-
  comparison and vocab benchmarks in `bench/` are kept.
