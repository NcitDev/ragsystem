# Setup and Migration Guide (GPU PC)

Use this guide to set up, initialize, and optimize the RAG codebase on the new PC with a dedicated GPU.

---

## 1. Prerequisites and Installation

1. **Install python & uv:** Ensure Python 3.10+ and the `uv` package manager are installed.
2. **Install ast-index:** Install the AST lexical parser tool:
   ```bash
   cargo install ast-index
   # Or install via pre-built binary matching your system architecture
   ```
3. **Download target codebase:** Clone the **Signal-Android** codebase to a local directory:
   ```bash
   git clone https://github.com/signalapp/Signal-Android.git /path/to/Signal-Android
   ```
4. **Sync Project virtualenv:**
   ```bash
   uv sync
   ```
5. **Start Qdrant & Ollama (Local GPU acceleration):**
   * Make sure **Ollama** is running with GPU acceleration enabled.
   * Pull the target embedding model:
     ```bash
     ollama pull qwen3-embedding:4b
     ```
   * Start the Qdrant vector database (either via docker or local binary). If using the default configuration, ensure it is listening on `http://127.0.0.1:6333`.

---

## 2. Configuration (`config/default.toml` or `~/.rag/config.toml`)

Update the configuration to take advantage of the GPU:
```toml
[embeddings]
model = "qwen3-embedding:4b" # exact Ollama tag; 2560 dimensions
provider = "ollama"
dim = 2560
batch_size = 128                  # Increase batch size for GPU parallelization

[qdrant]
mode = "server"
url = "http://127.0.0.1:6333"

[llm]
ollama_url = "http://localhost:11434"
agent_model = "qwen3:8b"
```

---

## 3. Initializing and Indexing

1. **Start the RAG Daemon:**
   ```bash
   uv run rag start
   ```
2. **Index Signal-Android:**
   Run a full index of the cloned repository:
   ```bash
   uv run rag index /path/to/Signal-Android --name signal --full
   ```
   * *Note:* Because we are running on a GPU-enabled machine, Ollama embedding generation should complete in **minutes** instead of hours.
   * This builds the lexical SQLite code index and the Qdrant semantic CodeGraph, populated with `inherits_from` metadata tags.

---

## 4. Running the Benchmark

Verify that everything works correctly by running the comparative suite:
```bash
uv run python benchmark_production_scenarios.py
```
This runs 10 developer scenarios comparing the Smart Agent (RAG), AST-Index, Graphify, Vanilla (ripgrep), and Serena (LSP).

---

## 5. Natively Supported Persistent Index-Time LSP Type Enrichment

To achieve compiler-level precision on cross-file usage lookups without running a slow language server at query time, the system includes an **Index-Time LSP Type Enrichment** system.

### How it works:
1. **Persistent O(1) LSP Client Pool:**
   During a repository indexing run (`uv run rag index`), the system detects and starts the appropriate language server (e.g., Kotlin/Java language server for Signal-Android, Pyright for Python, etc.) exactly once.
   * *Optimization:* The language server is kept alive across the entire indexing run instead of starting/stopping on every document batch. This avoids launcher overhead (which could otherwise run a compiler startup hundreds of times for large repos).
2. **Metadata Enrichment:**
   As chunks are parsed, they are routed through the active language server client to query cross-file symbol references (`fan_in` / `called_by` / `dead_code_candidate`).
3. **FQN/Keyword-accurate Resolution:**
   Enriched metadata is stored directly in Qdrant/SQLite. When calling `/resolve` or performing symbol usage queries, the retrieval agent has immediate access to compile-accurate call-graphs and relationships in under **10ms** (without any query-time compilation overhead).

### Configuration:
In `~/.rag/config.toml` (or `config/default.toml`), ensure the LSP section is enabled:
```toml
[lsp]
enabled = true          # Set to false to disable LSP indexing completely
timeout = 5000          # LSP request timeout in milliseconds
```
