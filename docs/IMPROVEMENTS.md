# Improvement backlog

Self-contained task list for a follow-up session (any LLM/agent). Ranked by
expected payoff. Context: commit `9a26c60` fixed the retrieval core (chunker
enrichment, decorated/exported defs, Kotlin names, chunk-id collisions, LSP
positions), hardened the indexer/server, extracted `server.py` logic into
`core/search_exec.py` / `core/structural.py` / `core/smart_search.py`, added
cross-repo `/smart-search`, and set up CI. Read `CLAUDE.md` and
`docs/ADR/001-full-stack-decision.md` before starting.

Verification gate for every task: `.venv/bin/ruff check .` clean and
`RAG_E2E=1 RAG_SKIP_GRAPH=1 .venv/bin/python -m pytest -q` green (151+ tests).

---

## 1. Re-index and re-benchmark (manual, do first — informs 2 and 4)

**Why:** until `9a26c60`, metadata/filter/graph/Kotlin-FQN payload channels were
empty; all tuning was done against a crippled pipeline.

**Do:** `rag index --full` on the indexed repos (needs daemon + Ollama), then
re-run `bench/benchmark_planner_comparison.py` and `bench/benchmark_vocab.py`.
Record deltas in `docs/benchmark_planner_comparison/summary.md`. Requires the
Qdrant server (`compose.qdrant.yml`) and, for vocab, the remote box collection
`repo_signal_vocab`.

**Decision rule:** if vocab coverage grew → prioritize task 2; if golden files
still rank poorly → prioritize task 4.

## 2. Vocab freshness: `rag vocab refresh`

**Problem:** the vocab layer (`core/vocab.py`, `/vocab/build`) is built once
from a JSONL snapshot (`scripts/vocab_summarize_qoder.py` output). When the
indexed repo changes, summaries go stale silently and `/smart-search`'s
`vocab_files` channel degrades.

**Fix:**
- Store the source file's content hash in each vocab point's payload at build
  time (`/vocab/build` in `server.py`, `core/vocab.py`).
- New CLI `rag vocab refresh --repo X`: compare current file hashes (reuse
  `_file_hash` from `core/indexer.py`) against vocab payload hashes; emit the
  changed-file list; re-summarize only those via the qodercli pipeline
  (see `scripts/vocab_summarize_qoder.py` for the prompt/batching); upsert into
  the vocab collection; delete vocab points for removed files.
- Daemon-side route `/vocab/refresh` doing the diff + upsert; CLI stays a thin
  HTTP client (see CLAUDE.md "CLI ↔ daemon coupling").

**Verify:** unit test with a fake vectorstore: build → mutate one file → refresh
→ only that file's vocab point re-written; removed file's point deleted.

## 3. Populate `git_last_modified` (or delete recency scoring)

**Problem:** `core/scoring.py` has `RECENCY_WEIGHT = 0.15` and
`_recency_score()` reading `payload["git_last_modified"]`, but nothing ever
writes that field — 15% of the score formula is dead.

**Fix:** in `core/indexer.py`, during the scan phase (inside the `_scan()`
thread helper), run one `git log --format=%aI --name-only` pass (or
`git ls-files` + `git log -1 --format=%aI -- <batch>`) to build a
{rel_path → ISO date} map; stamp it into each chunk's metadata in
`_process_file`. Add `git_last_modified` to `PAYLOAD_INDEXES` in
`vectorstore.py` only if it needs to be filterable (probably not).
Keep it cheap: one subprocess per index run, not per file.

**Verify:** new test — index a git fixture repo, assert chunks carry
`git_last_modified`; scoring test that a recent file outranks an old one with
equal base score.

## 4. Reciprocal-rank fusion for channel merging

**Problem:** lexical FTS hits are merged into dense results with a hand-tuned
squash `0.75 * raw / (raw + 3)` (`core/search_exec.py:_lexical_hit_to_search_result`).
It fixed lexical-always-wins, but the constants are arbitrary.

**Fix:** replace score-space merging with RRF in `promote_lexical_hits`:
`fused = Σ_channels 1 / (60 + rank_in_channel)`. Channels: dense results
(already scored/ordered) and lexical results (ordered by `_score_code_row`).
Keep the dedup-by-`_result_key` behavior (a hit in both channels sums both
terms — that's the point of RRF). `core/scoring.py` boosts then apply on top.

**Guardrails:** the e2e canary (`tests/test_e2e.py::test_index_then_search`,
run with `RAG_E2E=1`) asserts auth.py outranks repo.py for an auth query and
that exact-symbol lexical evidence still surfaces. Also re-run
`bench/benchmark_planner_comparison.py` before/after.

## 5. Unit tests for `run_smart_search`

**Problem:** the flagship endpoint (`core/smart_search.py`, ~570 lines) has only
route-level 422/404 tests. The pipeline (inference → grounding → definitions →
usages → vocab → related → semantic → candidates/pagination) is untested.

**Fix:** new `tests/test_smart_search.py` with a fake vectorstore (copy the
pattern from `tests/test_indexer_crash.py::_InMemoryVectorStore`) and
`monkeypatch` on `rag.agents.retrieval.infer_symbols` returning fixed symbols.
Cover at minimum:
- bucket composition for a symbol that resolves vs one that doesn't
- `candidate_offset`/`candidate_limit` pagination math and `candidates_total`
- `include_bodies=False` strips `code` from definitions/usages/semantic
- blast-radius phrasing auto-bumps `usages_limit` (`_BLAST_RADIUS_SIGNALS`)
- `run_smart_search_multi`: repo tags set on every item, semantic re-sorted
  by score, merged limits honored, one failing repo doesn't fail the call

## 6. systemd service for Linux (remote box)

**Problem:** `rag service install` (`src/rag/integration/supervisor.py`) is
macOS-launchd-only; the Ubuntu GPU box (192.168.3.49) runs the daemon by hand.

**Fix:** add a systemd **user** unit path: `rag service install` on Linux writes
`~/.config/systemd/user/rag-daemon.service` (ExecStart =
`<venv-python> -m rag start`, `Restart=always`, `WantedBy=default.target`) and
runs `systemctl --user daemon-reload && systemctl --user enable --now
rag-daemon`. `service status`/`uninstall` get matching branches. Reference
`docs/deployment-linux.md` and update it. Keep the existing "macOS-only"
message for `--tui` mode.

**Also:** document SSH tunneling (`ssh -L 7890:localhost:7890 <box>`) as the
sanctioned remote-access path in `docs/deployment-linux.md`. Do NOT bind
non-loopback: the bearer token travels plaintext (see `config.py`
`reject_wildcard_bind`, and the trusted-host middleware in `server.py` —
a non-loopback bind also requires extending `_allowed_hosts`).

## 7. Finish CLI layering cleanup

**Problem:** CLAUDE.md's invariant is "CLI subcommands are thin HTTP clients",
but in `src/rag/cli.py`: `export`/`import_` (~1862), `diff` (~1911),
`overview`/`plugins`/`repos` (~1999-2154), `backfill_code_index` (~1447), and
`benchmark_embeddings` (~313, calls private `embedder._embed_batch`) import
`rag.core.*` and touch Qdrant/SQLite directly — they can contend with the
running daemon. `repo_agent` (~581-997) re-implements the planner→resolve→
context loop that `/smart-search` now does server-side.

**Fix:** move each behind a daemon route (logic in `server.py` or a core
module, presentation in `cli.py`); delete `repo_agent` and alias its CLI
command to `smart-search` with a deprecation note. Do it one command per
commit; run the full suite between each.

## 8. Smaller items (grab-bag, each ≤1h)

- **Smart-search TTL cache:** key `(question, repo(s), candidate_offset,
  include_*)`, ~10 min TTL, in-process dict in `core/smart_search.py` —
  saves 10-25s of agy inference when an agent re-asks while paging.
  Invalidate on index completion (hook where the indexer finishes a run).
- **Branch-switch reindex:** `core/watcher.py` polls mtimes but misses
  `git checkout`. Also watch `.git/HEAD` + `.git/refs` mtime; on change,
  trigger the same `on_change` with the files git reports changed between
  old and new HEAD (`_get_changed_files` in `core/indexer.py`).
- **pyright in CI:** add `pyright` (basic mode) to `.github/workflows/ci.yml`;
  fix or `# type: ignore` the initial fallout. It would have caught the
  missing-`Any`-import class of bug for free.
- **pytest-asyncio deprecations:** 147 warnings about
  `asyncio.get_event_loop_policy` (removal in Py3.16). Upgrade pytest-asyncio
  and pin in `[dependency-groups].dev`.
- **Symbol-level incremental indexing:** `core/indexer.py` re-embeds a whole
  file per edit. Compare per-chunk `content_hash` against the SQLite code
  index (`storage/db.py`) and re-embed only changed chunks (delete-by-id for
  the removed ones). Only worth it if incremental latency on Signal-sized
  files actually annoys.
- **Vocab for docs:** `/smart-search` only anchors code; the `doc_chunks`
  collection could feed a `doc_files` bucket the same way `vocab_files` does.

## Explicitly rejected / do NOT do

- **MCP server** — decided against; the low-token path is the `rag` CLI +
  skills (`skills/rag-vocab-search`, `skills/rag-smart-retrieval`).
- **Re-adding a cross-encoder reranker** — removed deliberately;
  `SearchRequest.rerank` stays accepted-but-ignored.
- **Restoring the old benchmark scripts** — only the planner-comparison and
  vocab benchmarks (in `bench/`) are kept, per owner's instruction.
