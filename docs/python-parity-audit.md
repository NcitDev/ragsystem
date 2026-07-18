# Python → Rust Parity Audit (2026-07-17)

Method: five parallel auditors read the entire Python runtime (17,179 lines,
the behavioral oracle) module by module and cross-checked every observable
behavior against the Rust workspace — routes, request/response contracts,
constant tables element-by-element, formulas, side effects, CLI flags, and
ops surfaces. Only differences are recorded; each was verified with
file:line evidence on both sides. This document is the authoritative gap
list; the migration plan (§11.x) records what was *done*, this records what
*remains*.

Totals: **~145 differences** across five subsystems
(HTTP ~34, retrieval 16, structural 56, indexing/storage 23, CLI/TUI/ops 46;
some overlap). High-severity: ~40.

Fixed immediately during the audit (2026-07-17):
- **Data loss**: language-filtered incremental `/index` deleted every
  other-language file's chunks (diff against unscoped prior state). Fixed
  with language-scoped diffing + out-of-scope hash preservation; verified on
  a mixed kotlin+python repo.
- **No per-repo index lock**: concurrent `/index` calls raced state/Qdrant/
  SQLite. Fixed with an in-process fail-fast run guard (Python parity:
  non-blocking flock).
- **Query expansion table**: 5 missing keys (`queue`, `deploy`, `ui`,
  `perf`, `debt`) restored in Python's iteration order.
- Earlier the benchmark had already caught and fixed: smart-search invoking
  the LLM planner internally, graph-impact missing lexical fallback +
  related tests, nondeterministic ast-index truncation.

## Priority 1 — correctness / security — ✅ DONE (2026-07-17, verified live)

| Gap | Status |
|---|---|
| CSRF origin guard absent | ✅ `csrf_guard` middleware — 403 CSRF_BLOCKED on non-localhost Origin + no bearer (verified) |
| `/index` ignores `collection` field | ✅ explicit `collection` wins; registered-repo stats refresh |
| Dashboard `GET /` missing `Cache-Control: no-store` | ✅ header added (verified) |
| Validation contract | ✅ MAX_QUERY_LENGTH 2000, top_k 422 (200/20 ceilings), planner enum, smart-search repo-required, FastAPI `{detail:[{loc,msg,type}]}` shape (verified) |
| CLI fixed 120s timeout | ✅ `post_with_timeout`: 600s index-type, 300s ask/smart-search, 180s understand |
| dotenv never loaded | ✅ `load_env_files` called at daemon + CLI startup |
| launchd old-agent cleanup | ✅ `install` boots out + removes legacy `com.rag.daemon.plist` on macOS |
| No `daemon.jsonl` | ✅ `log_daemon_event` — request log + lifecycle, 10 MB rotation (verified) |

## Priority 2 — retrieval quality (measurable in benchmarks)

Done (2026-07-17), benchmark-verified:
- ✅ **smart-search pipeline depth**: LLM `infer_symbols` (agy) with heuristic
  fallback; `_symbol_exists` grounding (via SQLite `symbol_named`); `sem_names`
  PascalCase grounding from top-10 semantic; usages gating (default 0,
  blast-radius bump to 100) + two-phase trim; full candidates pool
  (defs+vocab+usages+related+semantic) with `candidate_offset`/`candidate_limit`
  pagination; `include_bodies=false` code stripping; `include_semantic`/
  `include_related` honored. Benchmark: smart mode 54.2%→**55.8% cov,
  6.1%→11.1% prec** (now == Python coverage, > Python precision) at 3× speed.
- ✅ **structural related channel**: `ast_index::related_files`
  (`implementations` + `refs`, priority merge, per-relation cap 12) wired into
  smart-search `related`.
- ✅ **agy planner prompt**: full `_RETRIEVAL_INSTRUCTIONS` block + `_SYMBOL_PROMPT`
  verbatim (shared consts in rag-agent).

More P2 done (2026-07-17, benchmark-verified with ast-index rebuilt):
- ✅ **ast_index `_attach_code`**: file-reading symbol/usage bounds (brace
  balance, decorator backfill, 40-line up-scan, windows, path-escape guard) +
  50%-overlap dedupe + empty-code drop. Code spans no longer depend on the CLI
  emitting `code`.
- ✅ **graph callees**: heuristic source scan (`_CALL_RE`, `_SKIP_CALLEES`,
  resolve-each-callee, `relation_source=heuristic_source_scan`) — was empty.
- ✅ **graph impact**: `_impact_risks` + `_stale_risks`, full metrics, stale
  detection (`_stale_index_files` mtime vs updated_at+2s).
- ✅ **graph affected**: `git diff --name-only <since>` fallback, changed∩indexed
  semantics, `related_test_files`, `_modules_for_files`, risks + metrics.

Full-matrix result (ast-index built): Rust ≥ Python on **all six modes** —
ast 54.2 vs 53.3, graph 56.7 vs 50.8, smart 67.5 vs 62.5, vanilla/ask ==, at
1.5–3× lower latency.

Remaining P2 (lower value, non-default paths):
- **structural.py Qdrant channel**: default-gated OFF in Python
  (`RAG_QDRANT_RELATED=0`); ast-index channel (ported) is the live default.
- ast_index `search` channel dict-parse; retrieve_context per-term scoring.
- `/graph/node` lexical fallback (impact has it); `graph_walk` native traversal.
- **context-pack**: AST + lexical + semantic + token budget (Rust AST-only).
- **Java/Kotlin FQN enrichment** (`defines_fqn`/`references_fqn`) at index time
  — unblocks the structural.py Qdrant channel above.
- Index-time **LSP enrichment** (`fan_in`/`fan_out`/`dead_code_candidate`).
- **Docs indexing** dense embeddings.
- Planner: gemini/openai/anthropic unwired in live path (agy is the default).

## Priority 3 — product surface (CLI/TUI/ops)

- CLI: JSON-only output (no human tables/`--json` toggle); `init` is a stub;
  `smart-search`/`resolve`/`repo-agent`/`list`/`context-pack`/`understand`
  missing most flags; `index` synchronous without progress; `install-claude`
  no-op; `generate-event-catalog` delegated; export/import/verify/repair
  depend on canned admin routes; `--base-url` ignores config.
- TUI: single JSON snapshot vs 6-screen dashboard with probes, crash tail,
  D/U action keys.
- Missing subsystems: file watcher, plugins (`~/.rag/plugins/*.yaml`),
  overview_stats, index_runs log, post-index graph/community/LOD build,
  async index jobs + progress, admin export/import, `/diff` (git-aware
  search), `/queries/stats`, `/health/detail`, `/stack`.
- Rate limiting: in-memory fixed window vs Python's persistent SQLite token
  bucket (600 burst / 20 rps) covering all routes.
- Dart chunker grammar divergence (bounds/names differ from Python's
  language pack).

## Deliberate / accepted deltas (not gaps)

- Reranker + sparse embeddings: removed from Python too.
- `qdrant.mode` semantics: Rust "embedded" = managed local server
  (documented R2 decision); Python local-mode store kept read-only for
  rollback.
- Rust-only additions: `migration` + `raw` CLI, `/events/ws`, request-body
  413 limit, `RAG_HOME` env, in-process embed cache, deterministic
  ast-index ranking, stricter plan-filter sanitization, case-insensitive
  extension discovery.
- Summaries/LOD generation: unused in this deployment (collections empty by
  design); consumption paths are live.

## Confirmed full parity (spot-verified element-by-element)

Config settings tree/defaults/bounds/deep-merge; token generation/0600;
all retrieval constant tables (filter vocabularies, stopwords, weights,
payload indexes, fallback hints, strategy signals, instruction text);
strategy execution incl. LOD hops and repo-forces-hybrid; lexical promotion
squash; symbol sanity filter; scoring formulas incl. string-truthy handling;
embedder prefixes/batching; vectorstore filter compilation + uuid5 ids;
chunker configs for python/java/kotlin/ts/js/go/rust/c/cpp; patterns.py
tables; kotlin/java text enrichment; storage schemas and lexical search;
incremental hash/state machinery; embed-cache format.
