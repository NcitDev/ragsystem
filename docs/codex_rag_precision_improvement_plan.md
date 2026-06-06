# RAG Precision Improvement Plan

Goal: make Codex + RAG beat plain Codex navigation for real developer work by optimizing for precision and minimal source context, not raw latency. It is acceptable for retrieval to spend more time embedding, re-ranking, and resolving symbols if the final context contains only the code needed to answer or patch.

## Target Behavior

For a request like "refactor this function", RAG should return:

- The exact function body, not the whole file.
- Direct callers/callees when relevant.
- The nearest focused tests.
- A confidence/rationale trail with line ranges.
- No resources, generated mocks, unrelated modules, or broad file summaries unless explicitly needed.

The benchmark pass condition should be:

- Equal or better answer quality than plain Codex.
- At least 30-50 percent fewer source tokens placed in context.
- Relevant function/test slices in the first retrieval response for 8 of 10 developer tasks.
- Time can be slower than `rg`; precision and context economy win.

## Saved Test Cases

Machine-readable test cases are saved in:

- `tests/eval/codex_rag_developer_tasks.jsonl`

Human-readable benchmark and measurements are saved in:

- `docs/codex_rag_developer_test_suite.md`
- `docs/codex_rag_developer_test_results.md`

## Why Current RAG Lost

The current system is mostly semantic vector search with metadata attached after retrieval. Plain grep won because many tasks had exact anchors such as test names, function names, or class names.

Observed issues:

- Exact symbols and test names are not promoted strongly enough.
- Kotlin chunks sometimes contain only declarations or class summaries, not useful function bodies.
- Indexed metadata fields like `is_suspend`, `uses_coroutines`, `module_path`, and test links were not reliably populated for the Dodo collection.
- Architecture queries over-ranked DI provider snippets.
- Coverage-gap queries need production-test relationship data, not just similar chunks.
- RAG result objects can be precise in file but imprecise in line/body, forcing local file reads.

## Retrieval Strategy

Use staged retrieval instead of one vector search.

1. Query understanding
   - Extract exact symbols, test names, quoted strings, file/path hints, modules, domains, and intent.
   - Classify task type: exact lookup, refactor, trace test, architecture, DI boundary, rename, test gap, patch planning.
   - Detect CamelCase and snake/camel function names as must-match lexical anchors.

2. Exact lexical pass
   - Run indexed BM25/FTS over `code`, `name`, `parent_name`, `file_path`, and `comments`.
   - Exact symbol/test matches should outrank semantic hits.
   - Return symbol definitions and precise line ranges.

3. Metadata-filtered semantic pass
   - Use vector search only inside likely modules/files from lexical/path/domain hints.
   - Apply filters such as language, module path, chunk type, production/test, symbol kind, annotations, `is_suspend`, and `uses_coroutines`.

4. Code graph expansion
   - Expand from top symbols to direct callers, callees, overrides, implementations, and tests.
   - For refactors, include immediate call sites and focused tests.
   - For architecture, include cross-module edges and owner components.

5. Cross-encoder or LLM re-rank
   - Re-rank candidate slices by answer utility, not semantic similarity alone.
   - Penalize resources, generated files, broad summaries, and declaration-only chunks when function bodies are requested.

6. Minimal context packing
   - Pack final context as slices with line ranges.
   - Prefer function/test chunks; include imports only if needed for patching.
   - Include file summary only when explaining architecture or module ownership.

## Indexing Improvements

1. Store real Kotlin symbol chunks
   - Function body chunks must include full body, signature, annotations, receiver type, parent class/interface, and line range.
   - Class chunks should summarize members but not replace member body chunks.
   - Avoid empty `name` for function chunks.

2. Populate metadata reliably
   - `symbol_kind`: function, class, interface, object, enum, test, module, resource.
   - `name`, `qualified_name`, `parent_name`, `package`, `module_path`.
   - `start_line`, `end_line`, `line_count`.
   - `is_test`, `test_framework`, `test_subject_guess`, `test_names`.
   - `is_suspend`, `uses_coroutines`, `returns_flow`, `uses_async`, `concurrency_patterns`.
   - `calls`, `called_by`, `implements`, `overrides`, `injected_types`.
   - `api_contract`: true for DTOs, serialized fields, Retrofit APIs.
   - `user_facing_text`: true for resources and string-bearing UI surfaces.

3. Add lexical indexes
   - SQLite FTS5 or Tantivy for exact symbol/file/body search.
   - Store normalized forms: lower-case, camel-case tokens, typo variants like `Payed`/`Paid`, package path tokens.

4. Build test-production links
   - Link test files to production by imports, class names, SUT fixture creation, mocked dependencies, and verified methods.
   - Store `tests_for` and `covered_by` edges.

5. Build DI ownership links
   - Link `ComponentDependencies` interfaces to `@Component(dependencies=...)`.
   - Link app/root components that implement dependencies.
   - Link Dagger modules that provide dependency implementations.

## Query-Time APIs To Add

### `/resolve`

Input: symbols, test names, file/path hints.

Output: exact definitions, implementations, overrides, and line ranges.

Use when:

- Query contains exact identifiers.
- User asks about a named failing test.
- User asks for a minimal patch.

### `/context-pack`

Input: task prompt plus optional resolved symbols.

Output: compact context pack:

- `primary_slices`
- `supporting_slices`
- `tests`
- `excluded_reasons`
- `token_estimate`
- `confidence`

This is the main API Codex should use before reading local files.

### `/coverage-map`

Input: module/package/function filters.

Output:

- Production functions with side effects.
- Nearest tests.
- Missing/weak coverage reasons.

Use for test-gap tasks.

### `/rename-plan`

Input: concept old/new, constraints such as "do not touch user-facing strings".

Output:

- Code-only symbols.
- API/serialized/resource exclusions.
- Risk classes.
- Mechanical rename candidate list.

## Ranking Rules

Boost:

- Exact symbol/test-name matches.
- Function bodies over signatures.
- Test chunks that verify the target symbol.
- Files in modules named in the prompt.
- Chunks with call edges to top hits.
- Chunks whose metadata matches task type.

Penalize:

- Resource files unless the task asks for text/resources.
- Debug assets and network JSON mocks unless the task asks for mocks.
- Broad file summaries when a function body is available.
- Unrelated DI modules for architecture queries unless ownership is requested.
- Chunks with empty symbol names.

## Minimal Context Policy

The RAG system should not return whole files by default.

Context pack budgets:

- Exact function patch: 1-2 function bodies plus 1-2 focused tests, usually under 3k tokens.
- Test trace: failing test plus production function chain, usually under 4k tokens.
- Refactor: target function, duplicated function/caller, relevant tests, usually under 6k tokens.
- Architecture: selected interfaces/classes and call edges, usually under 8k tokens.
- Rename: symbol inventory first; source bodies only after user chooses scope.

For every returned slice include:

- `file_path`
- `start_line`
- `end_line`
- `symbol`
- `why_included`
- `token_estimate`

## Evaluation Harness

Use `tests/eval/codex_rag_developer_tasks.jsonl`.

For each task, record:

- First relevant file rank.
- First relevant symbol rank.
- Whether function body was returned.
- Number of context slices.
- Source tokens in final context pack.
- Whether expected files/symbols were covered.
- Whether excluded files were correctly avoided.
- Latency.
- Final answer quality from 0-4.

Primary metric:

- Context precision = relevant source tokens / total source tokens returned.

Secondary metrics:

- Recall of expected symbols.
- First target rank.
- Number of unnecessary files.
- Patch/test command correctness.

## Implementation Phases

## Implemented First Slice

Implemented in this working tree:

- SQLite `code_index` plus FTS5 mirror of indexed chunks.
- Indexer synchronization for full reindex, incremental changed-file replacement, and removed-file deletion.
- Kotlin/Java metadata enrichment during indexing, so coroutine/DI/singleton flags are populated on future indexes.
- `/search` fusion that promotes exact lexical code hits alongside dense Qdrant hits.
- `/context-pack` endpoint with `max_slices`, `max_source_tokens`, exact-first packing, and semantic fallback.
- `/index/backfill-code-index` endpoint to populate SQLite from existing Qdrant payloads without re-embedding.
- CLI commands: `rag context-pack ...` and `rag backfill-code-index --repo dodo`.
- Optional `ast-index` sidecar integration for named repos. `/context-pack` now asks `ast-index` for exact symbol/search/usage hits before SQLite/Qdrant, then packs bounded function/test slices.
- `/resolve` endpoint and `rag resolve` CLI command for exact AST definitions/usages before context packing.
- Overlap-aware context packing so duplicate windows around the same test/function do not waste token budget.
- `/call-tree` endpoint and `rag call-tree` CLI command for AST caller-tree nodes with enclosing function/test slices.
- `/project-understand` endpoint and `rag understand` CLI command for module ranking, likely symbols, and recommended context slices for a topic.

Activation for the existing Dodo index:

1. Restart the RAG daemon so it loads these code changes.
2. Run `ast-index rebuild` in the Dodo repository.
3. Run `uv run rag backfill-code-index --repo dodo`.
4. Query with `uv run rag context-pack --repo dodo "completePayment analytics PaymentCompleted"`.

For improved Kotlin metadata fields, run a normal or full reindex after restart; the backfill can only mirror metadata already present in Qdrant payloads.

Verified Dodo activation:

- `ast-index rebuild` indexed 5,158 files, 50 modules, 988 XML usages, and 62,753 resources in the Dodo repo.
- `uv run rag backfill-code-index --repo dodo` mirrored 31,181 Qdrant chunks into SQLite FTS.
- `uv run rag context-pack --repo dodo --max-slices 5 --max-source-tokens 1200 --no-semantic "waitForPayedOrder"` returned exact interface/implementation/test slices in about 273 source tokens.

### Phase 1: Exact + Metadata Baseline

- Add lexical FTS index.
- Add `/resolve` for exact symbols/test names.
- Fix Kotlin chunk names and line ranges.
- Ensure function body chunks are returned.
- Reindex Dodo.

Expected result:

- Beat plain grep on Tasks 2, 3, 4, 9, and 10 for token usage while matching quality.

### Phase 2: Context Packs

- Add `/context-pack`.
- Implement task classifier and minimal-context budgets.
- Add re-ranker over candidate slices.
- Add source-token accounting.

Expected result:

- Beat plain grep on Tasks 1, 2, 4, 9, and 10 for minimal context.

### Phase 3: Relationship Graph

- Add caller/callee/override/implementation edges.
- Add test-production links.
- Add DI ownership links.

Expected result:

- Beat plain grep on Tasks 5, 7, and 8.

### Phase 4: Specialized Modes

- Add `/coverage-map` for risky test gaps.
- Add `/rename-plan` for code-only rename tasks.
- Add architecture mode that prefers ownership/call-edge paths over generic semantic chunks.

Expected result:

- Beat plain grep on Tasks 6, 7, and 8.

## Concrete Next Engineering Tasks

1. Inspect Kotlin chunker output for `CheckoutOrderProcessingService.waitForPayedOrder`.
2. Fix empty function `name` and missing line metadata in Qdrant payloads.
3. Add FTS table with `repo`, `file_path`, `symbol`, `kind`, `code`, `start_line`, `end_line`.
4. Implement exact symbol search and reciprocal-rank fusion with vector results.
5. Add context-pack response schema and token estimator.
6. Reindex Dodo and rerun `tests/eval/codex_rag_developer_tasks.jsonl`.
7. Compare against `docs/codex_rag_developer_test_results.md`.

## Product Principle

Do not optimize for "search result list looks relevant." Optimize for "Codex can act without reading the whole file."

If a function-level patch is requested, returning the exact function body plus the exact test is better than returning ten semantically related files. Retrieval can spend more time if it saves context and keeps the patch safe.
