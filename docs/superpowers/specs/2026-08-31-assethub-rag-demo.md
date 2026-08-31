# Asset Hub RAG Demo Specification

## Goal

Prepare `ragsystem` to index and retrieve Asset Hub source and documentation,
capture a short real TUI demonstration as a local video, and fill the remaining
Pet Projects 2026 form text fields in Russian without submitting the form.

## Scope and constraints

- Index only the exact allowlisted Asset Hub root:
  `/Users/ncitfy/arcadia-asset-hub/design/projects/asset-hub`.
- Populate the default Qdrant collections `code_chunks` and `doc_chunks`.
- Preserve the existing named repository collection `repo_asset_hub`.
- `index-docs` must embed document chunks through Ollama, store vectors in
  Qdrant, and mirror the same chunks into the SQLite lexical index.
- Keep the runtime Rust-only and reuse the existing embedding cache, Qdrant
  payload schema, deterministic point IDs, and batching path.
- Use `qwen3-embedding:0.6b` for embeddings and the configured Codex planner for
  retrieval planning; do not send source text to Codex for embedding.
- Index canonical documentation from the Asset Hub `docs/` directory. Do not
  traverse an Arcadia parent or sibling project.
- Record a silent 60–90 second demonstration of the real Ratatui interface and
  save it locally as `/Users/ncitfy/development/personal/asset-hub-rag-demo.mp4`.
- Do not upload the video. The user will upload it to Yandex Disk and provide
  the required link.
- Fill the Russian description, fun facts, and source link in the Orca-hosted
  Yandex form. Leave the required video-link field for the user-provided URL
  and do not click `Отправить`.

## Demo sequence

1. Open the Dashboard and show a healthy daemon plus all three populated
   collections.
2. Open Search, target repository `asset-hub`, and query for the deterministic
   context-pack behavior.
3. Show the returned files, timings, and planner information.
4. Open Help briefly to show the configured embedder and agent model.

## Acceptance criteria

- `rag status` reports positive point counts for `code_chunks`, `doc_chunks`,
  and `repo_asset_hub`.
- A document-index route test proves that `/index/docs` creates Qdrant points,
  invokes the embedder, and mirrors document chunks into SQLite.
- The focused test and the full workspace test suite pass.
- The MP4 exists, has non-zero video duration, and can be decoded by ffprobe.
- The remaining available form text fields contain Russian copy, while the
  video URL and final submit action remain untouched.
