---
name: rag-project-enrichment
description: Use when local RAG results are missing durable project knowledge, or when a large repo would benefit from generated docs/specs indexed into RAG. Guides Codex to discover code-grounded concepts such as analytics events, metrics, feature flags, module boundaries, DI ownership, state machines, workflows, public APIs, test coverage maps, and product vocabulary, then create source-cited docs and index them.
metadata:
  short-description: Enrich RAG with project knowledge
---

# RAG Project Enrichment

Use this skill when a repo-agent result is correct but incomplete because important project knowledge lives implicitly in code, naming conventions, or scattered files.

## Core Idea

RAG should contain two kinds of knowledge:

- exact code context from AST/lexical indexes
- durable project knowledge generated from code and indexed as docs/specs, currently in the docs Qdrant collection

Codex may create enrichment docs, but every fact must be grounded in source files and line numbers. Do not invent product rules.

## When To Enrich

Consider enrichment when the task mentions or depends on:

- analytics events, metrics, funnels, dashboards
- feature flags, experiments, AB toggles
- module ownership, Gradle dependencies, DI providers
- public APIs, facades, replacement/deprecated APIs
- state machines, workflows, lifecycle transitions
- domain vocabulary that differs from code names
- test coverage maps or risky untested behavior
- generated code conventions or screen/page object conventions

Also enrich when repo-agent finds the code path but misses an existing reusable concept.

## Calibration Insights

Use these as examples of what “missing durable project knowledge” looks like across repos:

- **Analytics/events are first-class knowledge.** Event constants, producer functions, helper wrappers, tests, and debug/event-preview tooling should become an event catalog before concluding that a new event is needed.
- **DI and module ownership are repetitive and indexable.** Android/Dagger, Spring, NestJS, Django apps, and other frameworks encode ownership in providers/modules/configuration. A dependency/module map is often more useful than more source slices.
- **Workflows and state machines are scattered.** States, transitions, reducers, async jobs, controllers, serializers, and tests often live in different files. A workflow map bridges product wording to code names.
- **Deprecated APIs encode migration knowledge.** Deprecation comments and replacement text should become public API/replacement-map entries.
- **Debug and tooling modules reveal domain surfaces.** Debug screens, toggles, metrics, event previews, route registries, and diagnostics show what the team considers inspectable/product-important.

## Workflow

1. Run repo-agent first:

```bash
uv run rag repo-agent --repo <repo-name> --json "<task>"
```

2. Inspect the result for gaps:

- `reuse_context` empty or misses obvious existing concepts
- `docs_context` empty for product/domain terminology
- `docs_context` returns an unrelated catalog, such as event docs for a DI/module prompt
- `evidence_bundle.risks` mentions missing tests, ambiguous symbols, or module boundaries
- Codex had to infer vocabulary not present in retrieved code

3. Choose the smallest useful enrichment artifact:

- `analytics-event-catalog.md`
- `metrics-catalog.md`
- `feature-flags.md`
- `module-boundaries.md`
- `dependency-injection-map.md`
- `checkout-state-machine.md`
- `domain-glossary.md`
- `test-coverage-map.md`
- `public-api-map.md`

For Android/Kotlin repos, prioritize:

- `analytics-event-catalog.md` for event constants, event producers, tracking helpers, analytics tests, and debug event tooling
- `feature-di-map.md` for `FeatureDependencies`, Dagger `Component`, `Module`, providers, and app/root dependency registries
- `workflow-state-map.md` for state enums/sealed classes, transition functions, polling/recovery paths, and tests
- `deprecated-api-replacements.md` for deprecated symbols and their replacement comments
- `debug-tooling-map.md` for debug screens/tools that reveal events, toggles, segments, remote config, or diagnostics

For other repos, choose equivalent artifacts:

- route/controller map for web frameworks
- ORM/model/query lifecycle map for backend frameworks
- scheduler/task/runtime map for async runtimes
- request/middleware/interceptor map for HTTP frameworks
- render/update lifecycle map for UI frameworks
- serialization/protocol map for generated or wire-format code

4. Generate docs from code, not memory. Each entry should include:

- canonical symbol/name
- human/search terms
- source file and line
- related symbols or callers when known
- short factual meaning, only if supported by code

For DI maps, include dependency interface, component, module/provider, app/root registration, and consuming feature.

For workflow/state maps, include state symbol, producer, consumer, transition function, recovery path, and nearest test.

For deprecated API maps, include deprecated symbol, replacement text, current callers, and migration risk.

## Query Hygiene For Enrichment

Avoid broad instruction words as retrieval terms. Words like “decide”, “explain”, “help”, “details”, “new developer”, or “needed” can collide with real code symbols and produce false positives.

For DI/module enrichment, first derive concrete symbols and rerun with those:

```bash
rg -n "CheckoutDetailsFeatureDependencies|CheckoutDetailsComponent|CheckoutDetailsModule|CheckoutStateModule" /path/to/repo
uv run rag repo-agent --repo dodo --json "CheckoutDetailsFeatureDependencies CheckoutDetailsComponent CheckoutDetailsModule CheckoutStateModule DI provider app registration module ownership"
```

For workflow enrichment, use concrete state/model symbols:

```bash
uv run rag repo-agent --repo dodo --json "PaidOrderState ALMOST_OK OrderCreated OrderIsBeingCreated waitForPayedOrder setupAppStateForNewOrder workflow transition tests"
```

For analytics enrichment, use concrete event/helper/factory symbols after the first broad pass:

```bash
uv run rag repo-agent --repo dodo --json "PaymentAnalytics AnalyticsHelper orderPollingAfterPaymentStart START_ORDER_POLLING_AFTER_PAYMENT trackPaymentFinished tests"
```

For non-Dodo repos, first use exact graph tools to derive concrete terms:

```bash
uv run rag files --repo <repo-name> "router controller middleware" --json
uv run rag node <SymbolName> --repo <repo-name> --json
uv run rag callers <SymbolName> --repo <repo-name> --json
uv run rag impact <SymbolName> --repo <repo-name> --json
```

5. Prefer existing generators before hand-written docs. For analytics/events:

```bash
uv run rag generate-event-catalog /path/to/repo --repo-name <repo-name> --index --full
```

After generating an event catalog, spot-check that it captures:

- event constants
- event producer/factory methods
- tracking helper methods
- analytics tests
- debug/event-preview tooling if present

For other artifacts, use exact RAG/AST plus `rg` verification, then write a compact Markdown file and index it:

```bash
uv run rag index-docs /path/to/generated-doc.md --full
```

Use `--full` only when intentionally rebuilding the docs collection for the current embedding model.

6. Rerun repo-agent:

```bash
uv run rag repo-agent --repo <repo-name> --json "<same task>"
```

7. If docs search returns empty results while embeddings are reported as used, verify the docs collection was indexed with the current embedding model. Rebuild docs with the current model before judging enrichment quality.

8. Compare before/after:

- first relevant rank
- source tokens
- code embeddings used
- docs context retrieved
- docs embeddings used
- reuse concepts found
- ambiguity/risk quality
- whether whole-file reads were avoided

## Guardrails

- Do not place speculative architecture opinions into indexed docs.
- Do not summarize giant files without source references.
- Do not mix generated docs from unrelated repos in one docs collection unless the doc clearly names its repo.
- Keep enrichment docs small enough to be useful: catalogs are fine, essays are not.
- If a fact depends on runtime/product ownership outside code, mark it as “needs product confirmation” instead of indexing it as truth.
- Do not let embeddings decide truth. Embeddings retrieve semantically related docs; Codex must verify against code/source references before editing.

## Output Discipline

When reporting enrichment work, include:

- generated/indexed docs
- commands used
- number of entries/chunks indexed
- before/after retrieval difference
- remaining gaps
