# Asset Hub RAG Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate Asset Hub code/document vector indexes, record their use in the real TUI, and prepare the Russian Pet Projects form entry.

**Architecture:** Route `/index/docs` through the configured async `RetrievalBackend`, convert discovered documentation files into the existing `FileChunks`/`PendingDocument` batch representation, and reuse `flush_group` so code and docs share embedding-cache, Qdrant, UUIDv5, and SQLite behavior. Runtime indexing stays scoped to the explicit Asset Hub project and its canonical `docs/` directory; presentation work consumes only verified runtime outputs.

**Tech Stack:** Rust, Axum, Tokio, Ollama, Qdrant, SQLite, Ratatui, ffmpeg/ffprobe, Orca embedded browser.

**Spec:** `docs/superpowers/specs/2026-08-31-assethub-rag-demo.md`

## Global Constraints

- Runtime remains Rust-only.
- Arcadia access stays inside `/Users/ncitfy/arcadia-asset-hub/design/projects/asset-hub`.
- Embeddings use `qwen3-embedding:0.6b`; retrieval planning uses configured Codex.
- No video upload and no Yandex form submission.

---

### Task 1: Vector-backed document indexing

**Files:**
- Modify: `crates/rag-server/tests/index_route.rs`
- Modify: `crates/rag-server/src/indexing.rs`
- Modify: `crates/rag-server/src/lib.rs`

**Interfaces:**
- Consumes: `RetrievalBackend`, `RagPaths`, `flush_group`, `ensure_collection`, `reset_code_index`.
- Produces: `pub async fn index_docs_route(backend: &RetrievalBackend, paths: &RagPaths, body: &Value) -> Result<Value, String>`.

- [x] **Step 1: Write the failing HTTP behavior test**

Add a test that posts a Markdown directory to `/index/docs` with collection
`doc_fixture` and asserts:

```rust
assert_eq!(status, StatusCode::OK);
assert_eq!(value["files_processed"], 1);
assert!(value["chunks_indexed"].as_u64().unwrap_or(0) > 0);
assert!(harness.qdrant.has_collection("doc_fixture"));
assert_eq!(harness.qdrant.stored_files("doc_fixture"), BTreeSet::from(["guide.md".to_owned()]));
assert!(harness.embed_calls.load(Ordering::SeqCst) > 0);
assert_eq!(harness.sqlite_files("doc_fixture"), BTreeSet::from(["guide.md".to_owned()]));
```

- [x] **Step 2: Run the focused test and verify RED**

Run: `cargo test -p rag-server --test index_route index_docs_embeds_into_qdrant_and_sqlite -- --nocapture`

Expected: FAIL because the existing blocking fallback only mirrors documents
into SQLite; no Qdrant collection exists and no embedding request occurs.

- [x] **Step 3: Implement the minimal async route**

In `indexing.rs`, add `index_docs_route` that canonicalizes `docs_path`, accepts
the requested collection or `doc_chunks`, discovers only `.md`, `.mdx`, `.txt`,
and `.rst`, chunks with Markdown semantics, and creates `PendingDocument`
payloads with `chunk_type=document` and `language=markdown`. On `full=true`,
drop only the selected Qdrant collection and clear the matching SQLite rows;
then call `ensure_collection` and `flush_group` in bounded file batches.

In `lib.rs`, dispatch `/index/docs` beside `/index` through:

```rust
"/index/docs" => Some(indexing::index_docs_route(&backend, &paths, &body).await),
```

Retain the synchronous `live_index_docs` fallback for deliberately
unconfigured servers: the async backend route owns production vector writes,
while the fallback preserves the existing Rust-only lexical compatibility
contract when no `RetrievalBackend` exists.

- [x] **Step 4: Run focused and workspace verification**

Run:

```text
cargo test -p rag-server --test index_route index_docs_embeds_into_qdrant_and_sqlite -- --nocapture
cargo fmt --check
cargo test --workspace
```

Expected: the focused test passes, formatting is clean, and the full workspace
suite passes.

### Task 2: Install and populate the two default collections

**Files:**
- Runtime output only; no Asset Hub source changes.

**Interfaces:**
- Consumes: verified `target/release/rag-rs` and exact Asset Hub paths.
- Produces: populated `code_chunks` and `doc_chunks` collections.

- [ ] **Step 1: Build and install the verified binary**

Run `cargo build --release -p rag-app`, replace `~/.local/bin/rag` with the
result, restart `dev.ragsystem.rag-rs`, and confirm `rag status` is healthy.

- [ ] **Step 2: Index code and measure elapsed time**

Run a full unnamed index against the exact Asset Hub root so the destination is
`code_chunks`; capture wall time and returned file/chunk counts.

- [ ] **Step 3: Index docs and measure elapsed time**

Run `rag index-docs <asset-hub>/docs --full --collection doc_chunks`; capture
wall time and returned file/chunk counts.

- [ ] **Step 4: Verify collection counts and representative retrieval**

Run `rag status` and a repository search for deterministic context-pack
behavior. Require positive point counts and non-empty results.

### Task 3: Record the local TUI video

**Files:**
- Create: `/Users/ncitfy/development/personal/asset-hub-rag-demo.mp4`

**Interfaces:**
- Consumes: healthy RAG daemon, populated collections, real `rag tui` screens.
- Produces: silent H.264 MP4, 60–90 seconds.

- [ ] **Step 1: Stage the terminal**

Use a clean terminal window sized for 16:9 capture, launch `rag tui`, and verify
Dashboard, Search, and Help render without secrets or unrelated windows.

- [ ] **Step 2: Capture the approved demo sequence**

Record Dashboard, Search for deterministic context-pack behavior in
`asset-hub`, results/planner timing, and Help model information. Keep all input
inside the TUI and omit microphone audio.

- [ ] **Step 3: Encode and verify**

Encode to H.264 MP4 and run ffprobe to assert a video stream and duration
between 60 and 90 seconds.

### Task 4: Fill Russian form copy without submitting

**Files:**
- Orca embedded-browser state only.

**Interfaces:**
- Consumes: measured indexing/retrieval facts and private ragsystem project URL.
- Produces: populated Russian description, fun facts, and code-link fields.

- [ ] **Step 1: Draft evidence-based Russian copy**

Describe local code/document RAG, `qwen3-embedding:0.6b`, deterministic and
semantic retrieval, Codex planning, and measured Asset Hub scale/speed. Keep
current implementation separate from planned Asset Hub production behavior.

- [ ] **Step 2: Fill and verify fields in Orca**

Re-snapshot the form, fill only description, fun facts, and project/code link,
then snapshot again and verify exact values. Leave the required Yandex Disk
video field empty until the user provides a link and do not click `Отправить`.
