# Dodo Android RAG Replacement Eval

Date: 2026-06-05

Target repo: `/Users/nikitaf/development/projects/dodo-mobile-android/project`

RAG repo name: `dodo`

## Goal

Turn this RAG from "semantic code search" into a replacement for basic Codex
navigation tools like `rg` and full-file reads. For large refactors, Codex
should ask for exact code units, for example "all async functions" or
"CardPaymentPresenter handlers", receive only relevant AST chunks, and patch
those functions in place without reading whole files.

## Current Test Harness

Added:

- `tests/eval/dodo_eval.jsonl`
- `tests/eval/run_retrieval_compare.py`

The comparison runner measures:

- RAG `/search` with `repo=dodo`
- Plain `rg` with task patterns, followed by full-file reads of candidate files
- Recall against expected files
- First-hit rank / MRR
- Latency
- Approximate token cost using `chars / 4`

This models the tool behavior we want to replace: `grep -> read whole files`.

## Partial Run Result

The Dodo index was still running when this partial eval was captured, so these
numbers are a lower-bound smoke test, not the final benchmark.

Report:

- `tests/eval/dodo_eval.partial.compare.md`
- `tests/eval/dodo_eval.partial.compare.csv`

Summary:

- RAG avg recall / MRR: `0.095 / 0.190`
- Grep avg recall / MRR: `0.762 / 0.738`
- RAG p50 latency: `13999 ms`
- Grep+read p50 latency: `304 ms`
- Avg approximate tokens returned: RAG `1630`, grep+read `12077`
- Avg token reduction from RAG chunks: `77%`
- Pass rate: RAG `0%`, grep `71%`

Interpretation:

RAG already reduces returned context size, but it is not yet a reliable
navigation replacement for this Android repo. The current semantic-only path
misses many exact code locations that grep finds immediately.

## Issues Found

1. Full repo indexing is too slow and opaque.
   The synchronous CLI timed out while the daemon kept indexing. The daemon logs
   continued to show `upsert_complete`, but the repo registry still had
   `last_indexed=None` and `chunks_count=0`.

2. The CLI error is misleading during long index runs.
   After the client timeout, a retry printed `Index failed: None`; daemon logs
   revealed the real reason: another index run was still holding the per-repo
   lock.

3. Search competes with indexing for Ollama.
   While indexing, Dodo `/search` calls had multi-second latency, often
   10-19 seconds. A replacement for `grep/read` needs predictable sub-second
   metadata and exact-symbol paths, with embeddings as a secondary path.

4. Semantic search alone is not enough for code navigation.
   Queries like "phone number formatting" and "cache inspector validates
   timestamp expiration" missed exact classes already present in the repo.
   Grep found them because class/file names are strong lexical anchors.

5. Duplicate files/chunks appear in search results.
   Several top-k result lists repeat the same file many times. This wastes the
   token budget and reduces recall diversity.

6. No AST symbol API exists for edit-safe refactors.
   Chunks contain metadata, but there is no first-class endpoint like
   `symbols.search(kind=function, modifiers=suspend|async)` returning stable
   `{file_path, start_line, end_line, symbol_name, signature}` records.

7. LSP enrichment is skipped.
   Logs repeatedly show `lsp_enrichment_skipped` with "no LSP servers
   available", so the system lacks references/definitions/call edges that would
   help refactor plans.

8. Default collections fail when empty.
   A clean RAG with no `code_chunks` collection returns a 500 for search instead
   of a clean empty result. This hurts first-run UX and test setup.

## Fix Plan

1. Add exact symbol storage.
   Persist AST symbols separately from vector chunks: repo, language, kind,
   name, parent, signature, modifiers, annotations, file path, line range, and
   content hash. For Kotlin this must detect `fun`, `suspend fun`, constructors,
   classes, objects, interfaces, properties, and annotations.

2. Add a symbol search endpoint.
   Example API:

   ```json
   {
     "repo": "dodo",
     "kind": ["function"],
     "modifiers": ["suspend"],
     "query": "checkout payment",
     "path_glob": "context/order/**",
     "top_k": 50
   }
   ```

   It should return only exact code units with line ranges, so Codex can patch
   them without reading the whole file.

3. Use hybrid retrieval order for coding tasks.
   Search should combine exact lexical/symbol matches, path/module boosts,
   semantic vector hits, and graph neighbors. Exact class/function/file matches
   should outrank vague semantic matches.

4. Deduplicate and diversify results.
   Apply file and symbol diversity after scoring. For navigation tasks, prefer
   one or two best chunks per file unless the user explicitly asks for all
   matches.

5. Make indexing resumable and observable.
   Expose a job id for all index runs, including CLI full index. Persist
   `files_processed`, `chunks_indexed`, `current_file`, `started_at`, and
   `last_error`. If the client times out, the user should be able to poll the
   same job instead of starting a conflicting retry.

6. Separate indexing and query embedding resources.
   Use a small priority queue or separate Ollama client limits so search does
   not starve behind batch indexing. Query embedding should preempt background
   indexing.

7. Tune index batching for large Android repos.
   Avoid repeated embedder verification per batch, make batch size configurable,
   and store state/checkpoints after each confirmed file batch. Keep graph and
   summary generation optional for first-pass code navigation.

8. Add edit-oriented retrieval tests.
   Extend the eval with tasks like "find all suspend functions in module X" and
   "return only functions that call checkoutService.setupAppStateForNewOrder".
   These tests should score symbol-level recall, returned line-range precision,
   and token budget.

## Expected Direction

The architecture is possible, but the current system is not ready to replace
`rg/read` for Android refactoring. The immediate win is token reduction. The
missing piece is exact AST/symbol retrieval with lexical ranking and line-range
patch targets.
