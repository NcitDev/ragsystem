# Real-fix instrument test — protocol, per-session prompt, and analysis

Goal: go beyond "did the tool find the right files" (that's `benchmark_real_fixes.py`)
to **"using only this instrument, can an agent actually produce the fix?"** — run each
(task × instrument) in its **own fresh session** (no context bleed), then compare every
session's output against the real Signal commit.

## The 3 real tasks (ground truth — keep SHAs OUT of the agent's prompt)

| # | Bug description (give this to the agent) | Real commit (grading only) | Golden files changed |
|---|---|---|---|
| T1 | "The transfer-control UI shows stale data or stops responding. Fix it." | `16232e2f` | `components/transfercontrols/TransferControlView.kt`, `TransferControls.kt` |
| T2 | "The contact search list flickers when the query changes. Fix it." | `4cdd1f70` | `contacts/ContactRepository.java`, `contacts/paged/ContactSearchPagedDataSource.kt`, `…PagedDataSourceRepository.kt`, `…ContactSearchViewModel.kt` |
| T3 | "Outgoing group calls show as incoming when someone joins. Fix it." | `f7eaa1cb` | `service/webrtc/GroupConnectedActionProcessor.java` |

All paths are under `app/src/main/java/org/thoughtcrime/securesms/`. The repo is
indexed at v8.15.3 (`d6871f8`), and all three fixes are ancestors of it, so the
files exist in the index in their pre-fix form.

## Instruments (one per session)

`vanilla-rg`, `ast-index`, `graphify`, `serena`, `rag-agentic` (eager, top-15+code),
`rag-agentic-pool` (lazy links). → 3 tasks × 6 instruments = **18 sessions**.

## Pre-flight (run once, before the sessions)
- Remote box up; rag daemon healthy: `curl -s 127.0.0.1:7890/health`.
- ast-index built, graph.json present, (serena only if Signal is Gradle-built — see build-serena-ubuntu.md).
- Token at `~/.rag/token`. `RAG_BENCH_ROOT=~/development/Signal-Android`.

---

## PER-SESSION PROMPT (copy-paste into a fresh session; fill {{INSTRUMENT}} and {{TASK}})

```
You are fixing a real bug in Signal-Android (indexed as repo "signal", at v8.15.3,
on the daemon at http://127.0.0.1:7890; token in ~/.rag/token). Source tree:
~/development/Signal-Android.

TASK: {{TASK — one of the bug descriptions above, text only}}

HARD RULES:
- For CODE DISCOVERY you may use ONLY this instrument: {{INSTRUMENT}}.
  Allowed calls per instrument:
    vanilla-rg        : `rg` over ~/development/Signal-Android
    ast-index         : `ast-index <symbol|usages|refs|search> --format json ...` (cwd=Signal-Android)
    graphify          : read/traverse signal_graph_out/graphify-out/graph.json
    serena            : POST http://127.0.0.1:7899/find_symbol|/find_usages
    rag-agentic       : POST /smart-search {include_bodies:true, candidate_limit:15}
    rag-agentic-pool  : POST /smart-search {include_bodies:false, candidate_limit:200}, page candidate_offset for more
- You may READ file contents with the editor/Read tool ONLY for files the instrument surfaced.
- You MUST NOT: look at git history/blame, search the web, or consult the actual
  fixing commit/PR. Work only from the bug description + the instrument.

DELIVERABLE — produce a fix and end with this exact block:

=== RESULT ===
instrument: {{INSTRUMENT}}
task: {{TASK id e.g. T1}}
files_identified: <comma-separated repo-relative paths you decided are involved>
files_read_fully: <paths you opened to read full code>
fix_diff: |
  <a unified diff (git diff style) implementing your fix>
instrument_calls: <how many retrieval calls you made>
est_context_tokens: <rough total tokens the instrument returned into your context>
turns: <number of assistant turns>
confidence: <low|med|high>
notes: <1-2 lines: what was hard, what the instrument missed>
=== END ===
```

Run this 18 times (3 tasks × 6 instruments), one fresh session each. Save each
RESULT block to `docs/real-fix-test/results/<task>_<instrument>.md`.

---

## ANALYSIS (run after all 18 sessions, in one session)

### 1. Fetch ground truth (real diffs + files)
```bash
for sha in 16232e2f 4cdd1f70 f7eaa1cb; do
  gh api repos/signalapp/Signal-Android/commits/$sha -q '.files[].filename'   # golden files
  gh api repos/signalapp/Signal-Android/commits/$sha -q '.files[] | .filename, .patch'  # real diff
done
```

### 2. Score each session on 3 axes
- **File recall/precision** (objective): of the golden files, how many did
  `files_identified` include? (recall) and how many of its identified files are golden? (precision)
- **Fix quality** (judged): does `fix_diff` change the SAME logic the real commit
  changed? Grade 0–2: 0 = wrong/no fix, 1 = right file(s) but partial/different
  approach, 2 = equivalent to the real fix. (Use the real `.patch` as reference;
  exact text need not match — same behavioral change counts.)
- **Efficiency**: `est_context_tokens`, `instrument_calls`, `turns`.

### 3. Build the comparison matrix
One row per (task, instrument):
`task | instrument | file_recall% | file_prec% | fix_grade(0-2) | tokens | calls | turns`
Then aggregate per instrument (mean across the 3 tasks): **mean file recall,
mean fix grade, mean tokens**. The headline question:
**which instrument lets the agent produce a correct fix at the lowest token/turn cost?**

### 4. Expected pattern (from the retrieval benchmark — validate or refute)
- `vanilla-rg`/`ast-index`: ~0 file recall on NL bug descriptions → agent flails or
  can't locate the fix site → fix_grade 0 on most tasks.
- `graphify`: medium recall, very high token cost.
- `rag-agentic*`: highest recall → most likely to produce a correct fix.
  `rag-agentic-pool` should match `rag-agentic`'s fix quality at ~half the tokens.
- `serena`: only if Signal is Gradle-built; if so, expect high precision on exact symbols.

### 5. Write up
`docs/real-fix-test/summary.md`: the matrix + per-instrument aggregates + the answer
to "does better retrieval translate into better/cheaper real fixes?" with 1-2
concrete examples (e.g., show how the winning instrument located the webrtc file for T3
while grep returned nothing).

## Notes / pitfalls
- Keep the SHAs and golden files OUT of the per-session prompts (they're for grading only).
- Each session must be FRESH — no shared context, or a later instrument benefits from
  an earlier one's findings.
- `est_context_tokens` is self-reported and rough; the objective token numbers come from
  `benchmark_real_fixes.py` (payload size). Use the benchmark for hard token data and the
  sessions for fix-quality.
