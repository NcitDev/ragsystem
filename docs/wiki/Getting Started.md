# Getting Started

<cite>
**Referenced Files in This Document**
- [README.md](file://README.md)
- [pyproject.toml](file://pyproject.toml)
- [config/default.toml](file://config/default.toml)
- [src/rag/config.py](file://src/rag/config.py)
- [src/rag/cli.py](file://src/rag/cli.py)
- [src/rag/server.py](file://src/rag/server.py)
- [src/rag/core/embedder.py](file://src/rag/core/embedder.py)
- [src/rag/core/indexer.py](file://src/rag/core/indexer.py)
- [src/rag/integration/logging_setup.py](file://src/rag/integration/logging_setup.py)
- [compose.qdrant.yml](file://compose.qdrant.yml)
- [scripts/install-codex-skills.sh](file://scripts/install-codex-skills.sh)
</cite>

## Update Summary
**Changes Made**
- Complete rewrite of the Getting Started guide with comprehensive installation and setup documentation
- Added detailed 30-second quickstart workflow with step-by-step instructions
- Enhanced environment setup section with Ollama and Qdrant configuration
- Expanded configuration management with TOML-based settings explanation
- Added troubleshooting section with common setup issues and solutions
- Included practical examples and first-time usage patterns

## Table of Contents
1. [Introduction](#introduction)
2. [Prerequisites](#prerequisites)
3. [Quickstart in 30 Seconds](#quickstart-in-30-seconds)
4. [Installation](#installation)
5. [Environment Setup](#environment-setup)
6. [Configuration Management](#configuration-management)
7. [First-Time Usage Patterns](#first-time-usage-patterns)
8. [Troubleshooting Guide](#troubleshooting-guide)
9. [Conclusion](#conclusion)

## Introduction
Welcome to the RAG system! This guide will help you rapidly onboard and become productive with the standalone code-search RAG system. The system consists of a headless FastAPI daemon (running on localhost:7890) with an embedded Qdrant vector store, Qwen3 dense embeddings via Ollama, and a separate read-only Textual TUI dashboard. The daemon stays up even if the TUI crashes, and can be configured to auto-start on login.

## Prerequisites
Before installing the RAG system, ensure you have the following prerequisites:

### System Requirements
- **Python 3.11 or newer** - Required for the RAG system
- **Ollama** - **Required** for embeddings (Qwen3-Embedding) and recommended for the planner agent (qwen3:8b)
- **Optional**: Docker for local Qdrant server (via docker compose)

### Key Dependencies
The system relies on several core technologies:
- **FastAPI** for the HTTP server
- **Qdrant Client** for vector storage
- **Tree-sitter** parsers for code chunking (Python, JavaScript, TypeScript, Go, Rust, Java, Kotlin, C/C++, Dart)
- **Ollama** for dense embeddings and agent capabilities
- **Textual** for the TUI dashboard

**Section sources**
- [README.md:9-18](file://README.md#L9-L18)
- [pyproject.toml:15-57](file://pyproject.toml#L15-L57)
- [config/default.toml:5-13](file://config/default.toml#L5-L13)

## Quickstart in 30 Seconds
Follow this minimal workflow to get indexing and searching immediately:

### Step 1: Pull Required Models
```bash
# Pull the embedding model (recommended)
ollama pull qwen3-embedding

# Pull the planner model (recommended)
ollama pull qwen3:8b
```

### Step 2: Initialize and Index
```bash
# Initialize and index the current directory
rag init .

# This creates config, starts daemon, and indexes your codebase
```

### Step 3: Perform Your First Search
```bash
# Search your codebase
rag search "your search query"

# Example searches
rag search "authentication middleware"
rag search "database connection pooling"
rag search "error handling patterns"
```

### Step 4: Explore Additional Features
```bash
# Launch the TUI dashboard (optional)
rag tui

# Get codebase overview
rag overview

# List registered repositories
rag repos

# Check daemon status
rag status
```

### Step 5: Auto-Start Configuration (macOS)
```bash
# Enable auto-start on login
rag service install
```

This sequence creates a config file, starts the daemon, indexes your current directory, and prepares the vector store for immediate search.

**Section sources**
- [README.md:25-35](file://README.md#L25-L35)
- [src/rag/cli.py:82-141](file://src/rag/cli.py#L82-L141)

## Installation
Install the RAG system in development mode and prepare your environment:

### Step 1: Install the Package
```bash
# Install in development mode
pip install -e .

# Verify installation
rag --help
```

### Step 2: Verify Python Version
```bash
# Check Python version
python --version
# Should show Python 3.11 or newer
```

### Step 3: Ensure Ollama is Running
```bash
# Check if Ollama is running
ollama list

# If not running, start Ollama
ollama serve
```

### Step 4: Pull Required Models
```bash
# Pull embedding model
ollama pull qwen3-embedding

# Pull planner model
ollama pull qwen3:8b
```

### Step 5: Verify Installation
```bash
# Test the installation
rag status
```

**Section sources**
- [README.md:9-18](file://README.md#L9-L18)
- [pyproject.toml:66-67](file://pyproject.toml#L66-L67)
- [src/rag/server.py:603-716](file://src/rag/server.py#L603-L716)

## Environment Setup
Configure your environment for optimal performance and reliability:

### Ollama Configuration
Ensure Ollama is running locally with the required models:

```bash
# Start Ollama service
ollama serve

# Verify Ollama is running
curl http://localhost:11434/api/tags

# Pull required models
ollama pull qwen3-embedding
ollama pull qwen3:8b
```

### Vector Store Setup
Choose between local Qdrant server or embedded mode:

#### Option A: Local Qdrant Server (Recommended for larger projects)
```bash
# Start Qdrant via Docker Compose
docker compose -f compose.qdrant.yml up -d

# Verify Qdrant is running
curl http://localhost:6333/healthz
```

#### Option B: Embedded Mode (Simplest setup)
The system defaults to embedded mode, which requires no additional setup.

### Logging Configuration
The daemon writes rotated JSON logs to `~/.rag/logs/daemon.jsonl`:

```bash
# Check log directory
ls -la ~/.rag/logs/

# View recent logs
tail -f ~/.rag/logs/daemon.jsonl
```

**Section sources**
- [README.md:17](file://README.md#L17)
- [compose.qdrant.yml:1-11](file://compose.qdrant.yml#L1-L11)
- [src/rag/integration/logging_setup.py:38-107](file://src/rag/integration/logging_setup.py#L38-L107)

## Configuration Management
The RAG system uses TOML-based configuration with Pydantic validation. Configuration precedence:

### Configuration Locations
1. **Default configuration** bundled with the package
2. **User configuration** at `~/.rag/config.toml` (created automatically by the CLI)

### Key Configuration Areas

#### Server Configuration
```toml
[server]
host = "127.0.0.1"  # Bind to localhost only
port = 7890         # HTTP server port
```

#### Embeddings Configuration
```toml
[embeddings]
model = "qwen3-embedding:4b"
dim = 2560          # Embedding dimension
batch_size = 64     # Batch processing size
keep_alive = "30m"  # Model persistence
```

#### Qdrant Configuration
```toml
[qdrant]
mode = "server"     # "server" or "embedded"
url = "http://127.0.0.1:6333"
path = "~/.rag/qdrant_data"
code_collection = "code_chunks"
docs_collection = "doc_chunks"
```

#### Index Configuration
```toml
[index]
max_chunk_chars = 8000
retrieval_top_k = 20
skip_dirs = [".git", "node_modules", ".venv", "venv", "__pycache__", "build", "dist", ".tox", ".mypy_cache", ".ruff_cache"]
```

#### LLM Configuration
```toml
[llm]
ollama_url = "http://localhost:11434"
agent_model = "qwen3:8b"
```

#### LSP Configuration
```toml
[lsp]
enabled = true
auto_detect = true
timeout = 5000
```

### Managing Configuration
```bash
# Create or edit configuration
rag config

# Open configuration file directly
nano ~/.rag/config.toml

# Reload daemon after configuration changes
rag status
```

**Section sources**
- [src/rag/config.py:150-194](file://src/rag/config.py#L150-L194)
- [config/default.toml:1-41](file://config/default.toml#L1-41)
- [src/rag/cli.py:82-141](file://src/rag/cli.py#L82-L141)

## First-Time Usage Patterns
After installation and environment setup, follow these patterns to get productive:

### Basic Workflow
```bash
# 1. Initialize and index your project
rag init .

# 2. Perform searches
rag search "authentication logic"
rag search "database models"
rag search "error handling"

# 3. Explore results
rag search "logging configuration" --top-k 10
```

### Advanced Search Patterns
```bash
# Search with repository filtering
rag search "middleware" --repo my-project

# Search with explain mode
rag search "auth flow" --explain

# Context pack for code review
rag context_pack "database migration" --max-slices 5
```

### Repository Management
```bash
# List registered repositories
rag repos

# Index additional repositories
rag index /path/to/other/project

# Verify index integrity
rag verify
```

### TUI Dashboard
```bash
# Launch the read-only TUI dashboard
rag tui

# Launch web dashboard
rag web
```

### Diagnostics and Health Checks
```bash
# Check system health
rag diagnose

# Check daemon status
rag status

# Verify index
rag verify
```

**Section sources**
- [README.md:37-66](file://README.md#L37-L66)
- [src/rag/cli.py:425-476](file://src/rag/cli.py#L425-L476)
- [src/rag/cli.py:530-800](file://src/rag/cli.py#L530-L800)

## Troubleshooting Guide
Common issues and their solutions:

### Daemon Not Running
```bash
# Start the daemon
rag start

# Check daemon health
curl http://127.0.0.1:7890/health

# View logs
tail -f ~/.rag/logs/daemon.jsonl
```

### Ollama Unreachable
```bash
# Ensure Ollama is running
ollama serve

# Check model availability
ollama list

# Pull required models
ollama pull qwen3-embedding
ollama pull qwen3:8b
```

### Indexing Errors
```bash
# Verify index integrity
rag verify

# Repair orphaned chunks
rag repair

# Re-index repository
rag index . --full
```

### Configuration Issues
```bash
# Reset to default configuration
rm ~/.rag/config.toml

# Recreate configuration
rag init .

# Check configuration syntax
rag config
```

### Performance Issues
```bash
# Adjust embedding batch size
# Edit ~/.rag/config.toml and modify [embeddings].batch_size

# Enable watch mode for auto-reindex
rag start --watch

# Check resource usage
htop
```

### Service Management (macOS)
```bash
# Install service
rag service install

# Check service status
rag service status

# Uninstall service
rag service uninstall
```

**Section sources**
- [README.md:71-74](file://README.md#L71-L74)
- [src/rag/cli.py:388-400](file://src/rag/cli.py#L388-L400)
- [src/rag/integration/logging_setup.py:38-107](file://src/rag/integration/logging_setup.py#L38-L107)

## Conclusion
You are now ready to use the RAG system effectively! Start with the 30-second quickstart workflow, then explore the full feature set through the CLI and TUI interfaces. The system provides:

- **Instant search capabilities** across your codebase
- **Persistent configuration** managed via TOML files
- **Robust diagnostics** for troubleshooting
- **Flexible deployment options** (local or cloud)
- **Auto-start capabilities** for seamless development workflow

For advanced usage patterns and deeper customization, refer to the CLI reference and configuration documentation. The system is designed for both beginners getting started with code search and experienced developers needing powerful retrieval capabilities.

Happy coding and happy searching!
