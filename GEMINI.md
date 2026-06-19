## RAG System

Standalone code-search RAG: headless FastAPI daemon with embedded Qdrant, tree-sitter chunking, and configurable LLM providers.

### Commands

```bash
# Start daemon (required for most commands)
uv run rag start

# Index a repo
uv run rag index [path] --name <repo-name>

# Get code context for a task
uv run rag repo-agent --repo <repo-name> --json "<task>"

# Symbol lookups
uv run rag node <Symbol> --repo <repo-name> --json
uv run rag callers <Symbol> --repo <repo-name> --json
uv run rag impact <Symbol> --repo <repo-name> --json
```

### Configuration

Edit `~/.rag/config.toml` or `config/default.toml`:

```toml
[retrieval_agent]
provider = "gemini"  # gemini, openai, anthropic, ollama
model = "gemini-2.0-flash"
api_key_env = "GEMINI_API_KEY"
```

### Repo Names

- Signal-Android: `signal` (not `signal-android`)

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
