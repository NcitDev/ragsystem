# Codex + RAG Developer Test Suite

Purpose: compare plain Codex navigation against Codex assisted by this RAG index on realistic developer work. Run each task in a fresh context when possible, with the Dodo Android repository indexed as `repo_dodo`.

Machine-readable cases:

- `tests/eval/codex_rag_developer_tasks.jsonl`

Related follow-up docs:

- `docs/codex_rag_developer_test_results.md`
- `docs/codex_rag_precision_improvement_plan.md`

## Comparison Method

For every task, record two runs:

- Plain Codex: use normal repo navigation tools such as `rg`, file reads, and local inspection.
- Codex + RAG: start with RAG retrieval/enumeration, then read only the minimum needed source regions.

Capture:

- Time to first relevant file.
- Number of files opened/read.
- Approximate tokens consumed by source context.
- Whether the final target location was correct.
- Whether the proposed code change was safe and complete.
- Whether tests/build commands were identified correctly.

Expected RAG advantage:

- Faster discovery of semantic targets when names differ from the user query.
- Less full-file reading.
- Better recall for architectural/conceptual tasks.
- More direct edits when chunks include exact symbol boundaries and line citations.

Expected plain Codex advantage:

- Simple literal lookup tasks where `rg` is enough.
- Cases where exact text or generated code is not indexed yet.
- Tasks requiring broad mechanical edits after the relevant file list is already known.

## Ten Developer Job Tests

### 1. Refactor Async/Suspend Functions

Prompt:

> Find suspend/async order checkout functions related to waiting for paid orders and propose a safe refactor that extracts duplicated state-update logic.

RAG should retrieve function chunks with concurrency metadata and checkout/order terms. Plain Codex will likely grep for `suspend`, `waitFor`, `paid`, and read more files.

Success criteria:

- Finds `waitForPayedOrder` or related paid-order flow.
- Finds `setupAppStateForNewOrder` callers.
- Produces a narrow refactor plan with impacted tests.

### 2. Trace UI State From Test Failure

Prompt:

> A test named `ifSuccess_andOrderStateIsAlmostOk_shouldSetupAppStateForNewOrder` is failing. Find the production path it verifies and explain the state transition.

Success criteria:

- Links test to production service/use case.
- Identifies checkout state dependency and paid-order response path.
- Avoids reading unrelated order modules.

### 3. Locate Deprecated API Replacement

Prompt:

> Find deprecated code that points users to `CheckoutService::setupAppStateForNewOrder` and determine what should call the new API instead.

Success criteria:

- Finds deprecated method and replacement target.
- Explains caller migration.
- Identifies minimal files for edit.

### 4. Add Analytics Event Around Payment Completion

Prompt:

> Add or verify analytics tracking for successful payment completion in the order checkout flow.

Success criteria:

- Finds payment completion tests and production flow.
- Identifies analytics helper call site.
- Suggests test updates or confirms existing coverage.

### 5. Find Dependency Injection Boundaries

Prompt:

> For the profile locale list feature, find its dependency interface and explain what module owns the implementation.

Success criteria:

- Finds feature dependency classes/interfaces.
- Identifies module boundaries.
- Avoids broad package browsing.

### 6. Rename a Domain Concept Safely

Prompt:

> The team wants to rename "deferred time" to "scheduled time" in checkout UI internals without touching user-facing strings. Find code-only symbols that need review.

Success criteria:

- Retrieves classes/fragments/viewmodels with semantic relation.
- Separates code identifiers from localization/user-facing text.
- Lists candidate files for mechanical rename.

### 7. Explain Cross-Module Architecture

Prompt:

> Explain how order checkout state is coordinated across `context/order` and `context/core`.

Success criteria:

- Finds both order and core state files.
- Produces architecture-level explanation with citations.
- Does not rely on reading entire modules.

### 8. Identify Risky Test Gaps

Prompt:

> Find production functions in checkout payment processing that have state-changing behavior but weak or missing test coverage.

Success criteria:

- Uses function chunks and test chunks.
- Points to candidate functions and nearest tests.
- Produces a prioritized risk list.

### 9. Debug Naming Mismatch

Prompt:

> The user says "paid order response VO", but the code may use different names. Find the closest actual model/classes and call sites.

Success criteria:

- Retrieves semantically similar `PaidOrderResponse` symbols even if `VO` does not exist.
- Explains naming mismatch.
- Provides concrete call sites.

### 10. Minimal Patch Planning

Prompt:

> Make the smallest safe change so successful paid order handling always resets app state before tracking analytics.

Success criteria:

- Finds exact function/test chunks.
- Proposes ordering-sensitive patch.
- Identifies existing tests to run.
- Reads only the needed files before editing.

## Scoring Template

Use this table for every run:

| Task | Mode | Relevant file found? | Files read | Source tokens approx | Time to target | Final answer quality | Notes |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| 1 | Plain |  |  |  |  |  |  |
| 1 | RAG |  |  |  |  |  |  |

Quality scale:

- 0: missed target.
- 1: found a related file but not enough to act.
- 2: found target and gave partial plan.
- 3: found target, produced safe plan, named tests.
- 4: produced safe patch or exact edit plan with minimal context.

## Hypothesis

RAG should win most on tasks 1, 2, 4, 7, 8, 9, and 10 because these require semantic navigation across symbol names, tests, and architecture. Plain Codex should be competitive on tasks 3 and 6 if literal names are obvious. The benchmark is successful if RAG reduces files read and source tokens by at least 30 percent while preserving or improving answer quality.
