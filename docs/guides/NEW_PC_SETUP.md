# Setup and Migration Guide (GPU PC)

Use this guide to set up, initialize, and optimize the RAG codebase on the new PC with a dedicated GPU.

---

## 1. Prerequisites and Installation

> **This project is Rust-only.** Earlier revisions of this guide told you to
> install Python + `uv` and run `uv sync`; there is no Python runtime any more.
> They also said `cargo install ast-index`, which installs an unrelated crate —
> the real tool ships through npm (see step 2).

1. **Build or install `rag`:** a Rust toolchain is the only build dependency.
   ```bash
   cargo build --release -p rag-app          # produces target/release/rag-rs
   install -m 0755 target/release/rag-rs ~/.local/bin/rag
   ```
2. **Install ast-index** — required for symbol navigation (`resolve`, `callers`,
   `callees`, `impact`, and the structural stage of `smart-search`). Without it
   those routes return **empty results rather than an error**, so a missing
   install looks like a broken index. `rag tui` and the web dashboard show an
   `AST-INDEX` card that tells you which state you are in.
   ```bash
   npm install -g @ast-index/cli            # native binary behind a Node launcher
   cd /path/to/your-repo && ast-index rebuild
   ```
3. **Download target codebase:** Clone the **Signal-Android** codebase to a local directory:
   ```bash
   git clone https://github.com/signalapp/Signal-Android.git /path/to/Signal-Android
   ```
4. **Start Qdrant & Ollama (Local GPU acceleration):**
   * Make sure **Ollama** is running with GPU acceleration enabled.
   * Pull the target embedding model — this is the packaged default, so no
     config edit is needed:
     ```bash
     ollama pull qwen3-embedding
     ```
   * Start the Qdrant vector database (either via docker or local binary). If using the default configuration, ensure it is listening on `http://127.0.0.1:6333`.

---

## 2. Configuration (`~/.rag/config.toml`)

`rag start` writes `~/.rag/config.toml` from the packaged defaults
(`crates/rag-config/assets/default.toml`) on first run, and that file
deep-merges over them afterwards. The defaults already work against the models
pulled in step 4 — the only reason to edit anything here is the GPU batch size:

```toml
[embeddings]
# Defaults (shown for reference; already correct out of the box).
# `model` must be a tag `ollama list` prints — a HuggingFace repo path such as
# "Qwen/Qwen3-Embedding-4B" is never matched and makes the daemon report
# `ollama: unavailable` while Ollama is healthy.
model = "qwen3-embedding:latest"
provider = "ollama"
# Must equal the width the model returns (4096 for the default/8b tag, 2560 for
# `:4b`, 1024 for `:0.6b`). Collections are created with this size at the first
# index, so a mismatch corrupts the index rather than erroring.
dim = 4096
batch_size = 128                  # <- the one GPU tweak: raise from the default 64

[qdrant]
mode = "server"
url = "http://127.0.0.1:6333"

[llm]
ollama_url = "http://localhost:11434"
agent_model = "qwen3:8b"
```

> If you change `embeddings.model` or `embeddings.dim` after indexing, drop and
> rebuild the affected Qdrant collections — the stored vector width is fixed at
> creation.

---

## 3. Initializing and Indexing

1. **Start the RAG Daemon:**
   ```bash
   rag start
   ```
2. **Index Signal-Android:**
   Run a full index of the cloned repository:
   ```bash
   rag index /path/to/Signal-Android --name signal --full
   ```
   * *Note:* Because we are running on a GPU-enabled machine, Ollama embedding generation should complete in **minutes** instead of hours.
   * This builds the lexical SQLite code index and the Qdrant semantic CodeGraph, populated with `inherits_from` metadata tags.

---

## 4. Running the Benchmark

Verify that everything works correctly by running the comparative suite:
```bash
python3 bench/benchmark_rust_only.py   # dev-time harness in bench/
```
This runs 10 developer scenarios comparing the Smart Agent (RAG), AST-Index, Graphify, Vanilla (ripgrep), and Serena (LSP).

---

## 5. Index-time metadata enrichment (and what LSP actually does)

> **Correction.** This section previously described a persistent LSP client
> pool that routed every chunk through a language server to compute cross-file
> references. **That system does not exist in the Rust implementation.**
> `crates/rag-index/src/lsp.rs` exposes exactly one function —
> `detect_lsp_servers`, a PATH probe — and the `[lsp]` config keys below are
> parsed but never acted on. Index-time LSP enrichment is listed as not ported
> in `docs/python-parity-audit.md`.

**What actually happens.** Chunks are enriched by static analysis at index
time (`crates/rag-index/src/enrich.rs` for Kotlin/Java,
`enrich_python.rs` for Python), which computes the metadata the ranker
consumes — `complexity_cyclomatic`, `has_docstring`, `has_unit_test`,
`is_public`, `dead_code_candidate`, `fan_in` / `fan_out`, patterns, domains
and layers. These are real and populated; `quality_score` in
`crates/rag-retrieval/src/lib.rs` scores against them. They are derived from
the tree-sitter parse, not from a compiler, so treat them as heuristics rather
than compile-accurate facts.

**What LSP is used for today.** Nothing but detection: `detect_lsp_servers`
reports which language servers are installed so `rag tui` and the web
dashboard can show them. Installing `jdtls`, `pyright` or `rust-analyzer`
changes that display and nothing else — it does not improve retrieval.

**Symbol-exact navigation** comes from the external `ast-index` CLI (step 2),
not from LSP.

### Configuration
The `[lsp]` section is still accepted for forward compatibility, but setting
it has no runtime effect today:
```toml
[lsp]
enabled = true          # parsed; currently unused
timeout = 5000          # parsed; currently unused
```

