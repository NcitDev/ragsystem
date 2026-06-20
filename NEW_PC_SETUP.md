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
     ollama pull qwen3-embedding:latest
     ```
   * Start the Qdrant vector database (either via docker or local binary). If using the default configuration, ensure it is listening on `http://127.0.0.1:6333`.

---

## 2. Configuration (`config/default.toml` or `~/.rag/config.toml`)

Update the configuration to take advantage of the GPU:
```toml
[embeddings]
model = "Qwen/Qwen3-Embedding-4B" # Ollama model name
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

## 5. Design Blueprint: Index-Time LSP Type Enrichment

To achieve compiler-level **100% precision** on cross-file usage lookups without running a slow language server at query time, you can implement an **Index-Time LSP Type Enrichment Runner** on the new GPU PC.

### Implementation Blueprint:
1. **LSP Lifecycle during Indexing:**
   In `src/rag/core/indexer.py`, within `_index_repository_locked`:
   * Start a background Kotlin/Java LSP language server connection using our `lsp.py` adapter.
   * Wait for the language server to complete compilation/indexing.
2. **FQN Extraction:**
   When iterating over class declarations and usages:
   * Query the LSP for the **Fully-Qualified Name (FQN)** of classes, interfaces, and methods (e.g. `org.thoughtcrime.securesms.database.helpers.migration.SignalDatabaseMigration`).
3. **Payload Construction:**
   Add these FQNs into Qdrant point payloads:
   ```json
   {
     "file_path": "app/.../SignalDatabaseMigrations.kt",
     "name": "SignalDatabaseMigrations",
     "inherits_from": ["org.thoughtcrime.securesms.database.helpers.migration.SignalDatabaseMigration"],
     "defines_fqn": ["org.thoughtcrime.securesms.database.helpers.SignalDatabaseMigrations"],
     "references_fqn": [
       "org.thoughtcrime.securesms.database.helpers.migration.SignalDatabaseMigration",
       "org.thoughtcrime.securesms.jobmanager.Job"
     ]
   }
   ```
4. **Resolution via Qdrant FQN Search:**
   In `/resolve` (`src/rag/server.py`), when resolving usages of `SignalDatabaseMigration`:
   * Execute a Qdrant keyword scroll where `references_fqn` contains `org.thoughtcrime.securesms.database.helpers.migration.SignalDatabaseMigration`.
   * This completely bypasses substring matching issues, providing compiler-accurate results in under **10ms**.
