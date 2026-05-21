# ADR-001: RAG System Full Stack Decision

**Date:** 2026-04-02
**Status:** Accepted (with amendments)

> **Amendment (post-launch):** Layer 5 (Sparse BM25 via FastEmbed) and
> Layer 6 (Qwen3-Reranker-4B via FastEmbed) were removed in a later
> refactor that nuked the FastEmbed dependency entirely. The runtime is
> now Ollama-only dense embeddings, no reranker. The Layer 4 "FastEmbed
> ONNX fallback" is also gone. See git log for the migration commit.
> This ADR is preserved as-is for historical context — do not rely on
> it as a description of the current code.

## Context

Building a standalone RAG system for code search. Derived from the existing CodeLead AI system at `/Users/nikitaf/learning/sberai` but with a better tech stack, TUI interface, and simplified architecture.

## Decisions

### Layer 1: Language — Python 3.12
- Fastest development, richest AI ecosystem
- Rust rejected: 90% of wall-clock time is LLM/network I/O, not compute

### Layer 2: TUI — Textual
- TUI is the daemon (single process)
- Runs HTTP server, Qdrant, Agno agents, file watcher in same event loop

### Layer 3: Vector Store — Qdrant Embedded
- In-process, no server, native sparse vector support
- Proven hybrid search with RRF fusion
- Full HNSW tuning control

### Layer 4: Dense Embeddings — Qwen3-Embedding-4B
- 100+ languages (code + natural language)
- 32K context window
- Task-specific instructions (+1-5% boost)
- Runtime: Ollama if installed, FastEmbed (ONNX) if not

### Layer 5: Sparse Embeddings — BM25 via FastEmbed
- Always local, always FastEmbed
- Keyword matching complement to dense search

### Layer 6: Reranker — Qwen3-Reranker-4B
- Same Qwen3 family as embedder (trained together)
- Runtime: Ollama if installed, FastEmbed (ONNX) if not

### Layer 7: LLM Integration
- User chat: Claude via Claude Code (external, not our concern)
- Agent reasoning: Ollama (qwen3:8b) for Agno agents
- No built-in chat — this is a retrieval engine

### Layer 8: Agent Framework — Agno
- Internal agents for retrieval logic, query planning, index management
- Not a chat framework — handles search strategy decisions

### Layer 9: Code Chunking — tree-sitter
- 3-tier hierarchy: File (T1) → Class (T2) → Function (T3)
- Functions over 4K tokens split at logical blocks
- Non-code files: Markdown by headings, YAML/JSON by keys
- Priority languages: Python, TypeScript, JavaScript, Go, Rust (P0)

### Layer 10: LSP Integration — Index-Time Only
- Start LSP servers during `rag index`
- Enrich chunks with types, call graph, references
- Kill LSP servers after indexing
- Zero runtime overhead
- TUI shows missing LSP servers with install hints

### Layer 11: Storage — SQLite
- Config, metadata, query logs
- Single file, zero config

### Layer 12: CLI — Typer
- Thin client for `rag search`, `rag index`, `rag status`
- HTTP calls to daemon running inside TUI process

### Layer 13: Config — TOML
- `~/.rag/config.toml`

## Architecture

```
$ rag start              <- single process

+---------------------------------------------+
|  Textual TUI (dashboard)                    |
|  + HTTP server (localhost:7890)              |
|  + Qdrant embedded (in-process)             |
|  + Agno agents (in-process)                 |
|  + File watcher (in-process)                |
+---------------------------------------------+

$ rag search "query"     <- thin client, HTTP to :7890
$ rag index .            <- triggers indexing
$ rag status             <- health check
```

### Index Pipeline

```
File -> tree-sitter (AST) -> T1/T2/T3 chunks
     -> LSP enrich (types, calls, references) -- if servers found
     -> git enrich (blame, author, last modified)
     -> Qwen3-Embedding-4B (dense vector)
     -> BM25 (sparse vector)
     -> Qdrant (store all)
     -> kill LSP servers
```

### Query Pipeline

```
Query -> Agno agent (decides strategy: vector, filtered, graph walk)
      -> Qwen3-Embedding-4B (embed query)
      -> BM25 (sparse query)
      -> Qdrant hybrid search (top 50)
      -> RRF fusion (top 20)
      -> Qwen3-Reranker-4B (top 5-10)
      -> Slim response (path + signature + code + score)
```

### Runtime Detection

```
Startup:
  Ollama running? -> use for embeddings + reranker + agent LLM
  Ollama missing? -> FastEmbed (ONNX) for embeddings + reranker
                  -> Agno agents degraded (no local LLM)

Index time:
  LSP servers on PATH? -> enrich chunks
  Missing? -> tree-sitter only, TUI shows install hints
```

### Response Shapes

| Consumer | Fields |
|----------|--------|
| LLM (Claude) | path, signature, code, score |
| TUI | stats, patterns, complexity distribution |
| CLI search | path, signature, score, key metadata |
| Agno agent | full metadata (for filter decisions) |

## Code Insights Metadata

Stored per chunk in Qdrant payload for filtering (never sent to LLM):

### Design Patterns
singleton, factory, abstract_factory, builder, repository, observer, strategy, decorator, adapter, facade, proxy, command, state_machine, middleware_chain, dependency_injection, event_sourcing, cqrs, unit_of_work, specification, visitor

### Architecture Role
controller, service, domain_model, repository, use_case, port, adapter, middleware, handler, utility, config, migration, test

### Concurrency
async_await, thread_pool, actor_model, lock_based, lock_free, producer_consumer, fan_out_fan_in, rate_limiting, circuit_breaker, retry_with_backoff

### Data Access
orm, raw_sql, query_builder, active_record, data_mapper, connection_pooling, migration, caching_layer, n_plus_one_potential, batch_operations

### API Patterns
rest, graphql, grpc, websocket, openapi, pagination, versioning, auth_scheme, rate_limiting, idempotency

### Error Handling
custom_exceptions, result_type, error_codes, global_handler, retry_logic, graceful_degradation, dead_letter_queue, panic_recover

### Testing
unit_test, integration_test, e2e_test, fixture_factory, mock_stub, property_based, snapshot, test_doubles, bdd

### Security
input_validation, sql_injection_guard, xss_prevention, csrf_protection, secrets_management, rbac, encryption, audit_logging

### Code Quality Metrics
- complexity_cyclomatic: int
- complexity_cognitive: int
- loc: int
- param_count: int
- nesting_depth: int
- dependency_count: int
- fan_in: int (LSP)
- fan_out: int (LSP)
- has_todo: bool
- dead_code_candidate: bool (LSP)
- has_unit_test: bool

### Infrastructure
docker, kubernetes, ci_cd, iac, feature_flags, environment_config, health_checks, structured_logging
