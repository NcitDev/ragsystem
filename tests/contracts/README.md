# Phase R0 Python contract fixtures

These fixtures capture the Python HTTP contract at the commit recorded in
`source-commit.txt`. `openapi.json` is generated from `rag.server.create_app()`
with keys sorted and no daemon lifespan startup. The endpoint JSON files are
representative serialized responses from the same Pydantic models.

Latency, uptime, generated identifiers, and external-service state are fixed to
stable representative values. They are contract fixtures, not claims about a
particular machine's live Qdrant or Ollama state.

Regenerate the OpenAPI fixture from a clean environment with:

```bash
uv run python scripts/export_openapi.py
```

