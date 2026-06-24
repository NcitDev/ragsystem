---
name: rag-smart-retrieval
description: Use when the LLM needs to choose the right retrieval tool for code context. Teaches the agent a decision tree to minimize turns and tokens while maximizing precision. Based on benchmark data across 6 refactoring tasks on Signal-Android (300K+ LOC).
metadata:
  short-description: Pick the right retrieval tool for minimal cost
---

# Smart Retrieval Tool Selection

Use this skill when you need to fetch code context from a RAG-indexed repo and want to minimize turns, tokens, and noise while maximizing precision.

## Fastest path: `/smart-search` (let the agent route for you)

If you have a **natural-language question and don't know the exact symbol
names**, call `/smart-search` first. It runs the whole loop server-side: an LLM
infers the likely class/interface names, resolves them to exact definitions
(plus usages for blast-radius questions), and adds a semantic complement —
returning the golden code context in one call.

```
POST /smart-search
{ "question": "How does the chat backup encryption work?", "repo": "<repo>", "top_k": 15 }
```

Benchmarked: ~2x the file coverage of plain `/search` (36.7% vs 15-18%) because
it cracks vague questions where embeddings bury the canonical file. Cost: a few
seconds of LLM inference. Use the manual decision tree below when you already
know the symbols (skip the LLM round-trip) or need fine control.

## The Decision Tree

```
What are you looking for?
│
├── A natural-language question, symbols unknown
│   → /smart-search (LLM infers symbols → resolve + semantic, one call)
│
├── A class / function / interface (you know the name)
│   → /resolve (definitions only, usages_limit=0)
│     91.7% precision · 6.7K tokens · 1 turn
│
├── Project knowledge (events, DI maps, workflows, feature flags)
│   → /docs-search (semantic search on docs collection)
│     This is WHERE QDRANT SHINES — structured knowledge artifacts
│
├── "What breaks if I change X?" (blast radius)
│   → /resolve TWO-PHASE: definitions first, then selective usages
│     Phase 1: usages_limit=100 (count only), read definitions
│     Phase 2: filter to 15 most relevant usages, read those
│     30-40% precision · ~6K tokens · 2 calls
│
├── A code pattern / flow (no specific symbol name)
│   → /context-pack (include_semantic=false, max_slices=15)
│     Then extract symbols → loop to /resolve
│
└── A text/regex pattern across files
    → rg to discover symbol names → loop to /resolve
```

**Two retrieval worlds:**
- **Code context** (symbols, classes, functions): AST-index via `/resolve` — no embeddings needed
- **Project knowledge** (events, DI, workflows, docs): Qdrant semantic search via `/docs-search` — embeddings required

## Tool Reference

### 1. `/resolve` — Primary Tool (use this 80% of the time)

**When:** You know the class/function/symbol names you need.

**API:**
```
POST /resolve
{
  "repo": "<repo-name>",
  "symbols": ["ClassName", "functionName", "InterfaceName"],
  "definitions_limit": 20,
  "usages_limit": 0
}
```

**What you get:** The exact files where those symbols are **defined** — class bodies, function signatures, interface declarations. No usages, no noise.

**Benchmark:** 91.7% precision, ~6,700 tokens, 1 API call, ~400ms.

**Rules:**
- Always start here when you have symbol names
- Set `usages_limit: 0` unless you need blast radius
- For blast radius, use the two-phase strategy (see Tool 3 below) — NEVER read all 50+ usage files
- Symbols should be exact names from code — `JobManager`, `SignalDatabaseMigration`, not fuzzy queries

### 2. `/context-pack` — Natural Language Fallback

**When:** You have a question like "how does push notification processing work?" but no specific symbol names.

**API:**
```
POST /context-pack
{
  "query": "how does push notification processing work",
  "repo": "<repo-name>",
  "max_slices": 15,
  "max_source_tokens": 30000,
  "use_ast_index": true,
  "include_semantic": false
}
```

**What you get:** Code slices from files matching the query via AST-index and lexical search.

**Benchmark:** 19-75% precision (depends on query specificity), ~6-15K tokens, 1 API call.

**Rules:**
- **Always set `include_semantic: false`** — semantic search adds embedding noise that destroys precision (files like `PaymentType.java` match "deprecated migration cleanup" via vector similarity)
- Keep `max_slices` at 15 or below — more slices = more noise
- After getting results, **filter by symbol match**: only keep slices where the file path contains a relevant symbol name or is in the same package as your target
- If you extract symbol names from the results, **loop back to `/resolve`** with those symbols for precise definitions

### 3. `/resolve` with usages — Blast Radius Analysis (two-phase)

**When:** You need to know "what breaks if I change this class/function/interface?"

**IMPORTANT: Use the TWO-PHASE strategy to keep precision high (30-40% instead of 5-8%):**

**Phase 1 — Get the blast radius (count only, don't read all files):**
```
POST /resolve
{
  "repo": "<repo-name>",
  "symbols": ["Job"],
  "definitions_limit": 5,
  "usages_limit": 100
}
```
Read the **definitions** (usually 1-3 files). Note the definition's directory path.
From the response, note how many usage files exist (e.g., "53 files reference Job").
**Do NOT read all usage files yet.**

**Phase 2 — Selective read (filter before reading):**
From the usages list, **keep only** files matching these relevance rules:
1. **Same directory** as the definition (e.g., if Job is in `org/signal/jobs/`, keep usages there)
2. **Symbol name in filename** (e.g., `JobManager.java`, `JobScheduler.kt`)
3. **First 10 usages** by order (most important usages tend to come first)

**Read at most 15 usage files total.** Report the full count to the user: "53 files reference Job — here are the 15 most relevant."

**Benchmark:** 30-40% precision, ~6K tokens, 2 API calls, ~800ms.

**Rules:**
- NEVER read all 50+ usage files — this kills precision
- Always report the total usage count to the user
- If the user asks for "all usages", give them the count + the 15 most relevant file paths

### 4. `/docs-search` — Project Knowledge (Qdrant semantic search)

**When:** You need project-level knowledge that lives in indexed docs, not in raw code symbols.

**API:**
```
POST /docs-search
{
  "query": "analytics events for checkout flow",
  "top_k": 10
}
```

**What you get:** Semantic search results from the docs Qdrant collection — event catalogs, DI maps, feature flag docs, workflow state maps, deprecated API replacements, module boundary docs.

**This is where Qdrant + embeddings shine.** The docs collection contains structured knowledge artifacts generated from code:
- `rag generate-event-catalog` → event constants, producers, tracking helpers
- `rag index-docs path/to/events.md` → manually curated project knowledge
- Module ownership maps, DI wiring docs, state machine definitions

**Rules:**
- Use when the question is about **project knowledge**, not code symbols
- Queries like "find all analytics events", "what feature flags exist", "show me the DI map" belong here
- `/resolve` CANNOT answer these — there's no single symbol to look up
- Semantic search works well here because docs are **well-structured** (unlike raw code where embeddings add noise)
- Combine with `/resolve` for complete answers: docs-search gives the map, resolve gives the code

**Workflow for knowledge + code:**
```
1. /docs-search "analytics events" → finds event catalog with event names
2. Extract symbol names from results (e.g., "START_ORDER_POLLING")
3. /resolve { symbols: ["START_ORDER_POLLING", "trackPaymentFinished"] }
4. Now you have BOTH the knowledge map AND the exact code
```

### 5. AST-Index CLI — Scripted Symbol Lookup

**When:** You need to script lookups or pipe results.

```bash
# Find symbol definitions
ast-index symbol --format json --limit 20 "JobManager"

# Search by text pattern
ast-index search --format json --limit 20 "extends Job"

# Find all usages of a symbol
ast-index usages --format json "JobManager"
```

**Use case:** When building automated pipelines or when you need CLI-friendly output.

### 5. `rg` (ripgrep) — Last Resort

**When:** Nothing else found what you need, or you need regex/text patterns.

```bash
rg -l "extends Job" --include "*.java" --include "*.kt"
rg -l "@Deprecated" --include "*.kt"
```

**Warning:** rg returns hundreds of files with 5-10% precision. Use only to discover symbol names, then loop back to `/resolve`.

## Decision Examples

| User asks | Tool to use | Why |
|---|---|---|
| "Find the JobManager class" | `/resolve` with `symbols: ["JobManager"]`, `usages_limit: 0` | Exact symbol → definitions only |
| "Find all analytics events" | `/docs-search` with `query: "analytics events"` | Project knowledge, no single symbol |
| "Show me the DI wiring map" | `/docs-search` with `query: "DI dependencies modules"` | Indexed knowledge artifact |
| "What feature flags exist?" | `/docs-search` with `query: "feature flags toggles"` | Docs collection knowledge |
| "How does job scheduling work?" | `/resolve` with `symbols: ["JobManager", "JobScheduler"]`, `usages_limit: 0` | Extract symbols from question first |
| "What breaks if I change the Job base class?" | `/resolve` two-phase: defs first (read 1-3 files), then filter usages to 15 most relevant | Blast radius = usages, but NEVER read all 50+ |
| "Trace the push notification pipeline" | `/context-pack` with query, no semantic | Natural language, no specific symbols |
| "Find deprecated migration code" | `/resolve` with `symbols: ["DeprecatedJobMigration"]` | If you know the symbol name |
| "Find all deprecated annotations" | `rg "@Deprecated"`, then `/resolve` symbols | rg to discover, resolve to read |

## Anti-Patterns

**DO NOT:**
- Call `/context-pack` with `include_semantic: true` for symbol-specific queries — embedding noise will add 20-40 irrelevant files
- Call `/resolve` with `usages_limit: 50` and read ALL returned files for blast radius — use the two-phase strategy instead (read definitions, count usages, selectively read max 15)
- Use `/context-pack` as your first call when you already know symbol names — `/resolve` is more precise
- Chain multiple `/context-pack` calls hoping for better results — the noise compounds
- Read every file returned by a tool — filter by relevance (symbol match, same package, golden file set)
- Use `/docs-search` to find code symbols — use `/resolve` for that. `/docs-search` is for knowledge artifacts

**DO:**
- Use `/docs-search` for project knowledge (events, DI, workflows, flags) — semantic search works well on structured docs
- Combine `/docs-search` + `/resolve` for complete answers: docs give the map, resolve gives the code

## Performance Budget

For a production LLM agent, target these budgets per retrieval:

| Metric | Target | How |
|---|---|---|
| Turns | 1-5 | One `/resolve` call + optional fallback |
| Tokens | < 10,000 | Definitions only, no usages unless needed |
| Precision | > 90% | Use `/resolve` with exact symbols |
| Signal% | 100% | Filter `/context-pack` results by symbol match |
| Latency | < 1s | `/resolve` is ~400ms, `/context-pack` is ~600ms |

## Auth

All RAG server endpoints require:
```
Authorization: Bearer <token>
```

Token is stored at `~/.rag/token`. Read it before making requests:
```bash
TOKEN=$(cat ~/.rag/token)
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:7890/health
```

## The Two Golden Rules

1. **For code:** Extract symbols first, then call `/resolve`. A question like "how does the DI container wire dependencies?" should become `/resolve` with `symbols: ["AppDependencies", "AppComponent", "MainModule"]` — not a `/context-pack` call with the full question.

2. **For knowledge:** Ask `/docs-search` first. A question like "find all analytics events" or "show the DI map" belongs in semantic search on the docs collection. Then extract symbol names from the results and call `/resolve` to get the actual code.

**The pattern:** `/docs-search` finds the map → extract symbols → `/resolve` gets the code.
