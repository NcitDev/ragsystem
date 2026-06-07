---
name: rag-refactor-agent
description: Use when refactoring, adding features, or moving code in a large indexed repo with the local RAG repo-agent. Guides Codex to ask repo-agent for exact code context, reuse checks, tests, callers, module boundaries, docs/event specs, and eval metrics before editing.
metadata:
  short-description: Refactor with RAG repo-agent context
---

# RAG Refactor Agent

Use this skill when a task touches a large indexed repo and should be grounded by the local RAG repo-agent before Codex edits code.

## Core Rule

The repo-agent populates context. Codex performs the refactor.

Do not ask the local model to decide the final code change. Use it to retrieve a compact evidence bundle:

```bash
uv run rag repo-agent --repo <repo-name> --json "<task>"
```

## Workflow

1. Verify daemon health when needed:

```bash
curl -s http://127.0.0.1:7890/health
```

2. Ask repo-agent first. Prefer JSON for parsing:

```bash
uv run rag repo-agent --repo dodo --json "<developer task>"
```

3. Read the evidence bundle before opening files:

- `evidence_bundle.top_files`
- `evidence_bundle.symbols`
- `evidence_bundle.callers`
- `evidence_bundle.tests`
- `evidence_bundle.modules`
- `evidence_bundle.docs`
- `evidence_bundle.symbol_ambiguities`
- `evidence_bundle.risks`
- `metrics`

4. For feature additions, check `reuse_context` before proposing new APIs/events/classes.

5. For architecture/module work, check `architecture.modules`, `call_trees`, and dependency/DI slices before moving code.

6. If the repo-agent finds code but misses durable project knowledge, use the `rag-project-enrichment` skill before editing. Typical gaps: analytics events, metrics, feature flags, module ownership, DI maps, state machines, public API maps, or product vocabulary that differs from code names.

7. Disambiguate same-name symbols by file path and caller, especially common methods like `setupAppStateForNewOrder`.

8. Only after the repo-agent pass, use `rg`, AST index, and targeted file reads to verify. Avoid whole large-file reads unless the evidence bundle is insufficient.

9. Edit with the smallest safe change. Keep behavior order, side effects, and existing module boundaries intact unless the task explicitly asks otherwise.

10. Run targeted tests first, then broader tests when risk justifies it.

## When Events Or Docs Matter

If the task mentions analytics/events/product terminology, ensure event docs are indexed:

```bash
uv run rag generate-event-catalog /path/to/repo --repo-name dodo --index
```

Then rerun repo-agent and inspect `docs_context`.

If `docs_context` stays empty while `docs_embeddings_used=true`, check for a docs collection/embedding-model mismatch and rebuild docs for the current embedding model.

## Output Discipline

In your final answer, report:

- changed files
- tests run
- first relevant file/rank
- source tokens
- embeddings used for code context
- whether whole-file reads were avoided
- remaining risks
