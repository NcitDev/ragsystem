# Real-time File Watching and Live Indexing

<cite>
**Referenced Files in This Document**
- [src/rag/core/watcher.py](file://src/rag/core/watcher.py)
- [src/rag/core/indexer.py](file://src/rag/core/indexer.py)
- [src/rag/server.py](file://src/rag/server.py)
- [src/rag/config.py](file://src/rag/config.py)
- [config/default.toml](file://config/default.toml)
- [src/rag/cli.py](file://src/rag/cli.py)
- [src/rag/core/chunker.py](file://src/rag/core/chunker.py)
</cite>

## Table of Contents
1. [Introduction](#introduction)
2. [Project Structure](#project-structure)
3. [Core Components](#core-components)
4. [Architecture Overview](#architecture-overview)
5. [Detailed Component Analysis](#detailed-component-analysis)
6. [Dependency Analysis](#dependency-analysis)
7. [Performance Considerations](#performance-considerations)
8. [Troubleshooting Guide](#troubleshooting-guide)
9. [Conclusion](#conclusion)

## Introduction
This document explains the real-time file watching and live indexing system used to automatically re-index a repository when files change. The system combines a polling-based file watcher with an incremental indexing pipeline to maintain an up-to-date vector store with minimal disruption to developers. It covers how file system events are monitored, how automatic indexing is triggered, how selective re-indexing works, configuration options for watch behavior, and practical guidance for setting up and optimizing live indexing in active development environments.

## Project Structure
The live indexing system spans several modules:
- File watcher: polls for changes and invokes a callback
- Indexer: performs incremental re-indexing of changed files
- Server: integrates the watcher into the daemon lifecycle
- CLI: enables watch mode and sets the watched path
- Configuration: defines skip directories and other index behavior
- Chunker: provides language-aware chunking used during indexing

```mermaid
graph TB
CLI["CLI (start --watch)"] --> ENV["Environment Variable<br/>RAG_WATCH_PATH"]
ENV --> Server["Server Lifespan"]
Server --> Watcher["FileWatcher"]
Watcher --> Callback["On-change Callback"]
Callback --> Indexer["index_repository (incremental)"]
Indexer --> VectorStore["Qdrant Vector Store"]
Indexer --> Storage["SQLite Storage"]
Config["Settings (skip_dirs, etc.)"] --> Watcher
Config --> Indexer
Chunker["Chunker (language-aware)"] --> Indexer
```

**Diagram sources**
- [src/rag/cli.py:175-220](file://src/rag/cli.py#L175-L220)
- [src/rag/server.py:664-691](file://src/rag/server.py#L664-L691)
- [src/rag/core/watcher.py:26-108](file://src/rag/core/watcher.py#L26-L108)
- [src/rag/core/indexer.py:242-550](file://src/rag/core/indexer.py#L242-L550)
- [src/rag/config.py:83-89](file://src/rag/config.py#L83-L89)
- [src/rag/core/chunker.py:385-444](file://src/rag/core/chunker.py#L385-L444)

**Section sources**
- [src/rag/cli.py:175-220](file://src/rag/cli.py#L175-L220)
- [src/rag/server.py:664-691](file://src/rag/server.py#L664-L691)
- [src/rag/core/watcher.py:26-108](file://src/rag/core/watcher.py#L26-L108)
- [src/rag/core/indexer.py:242-550](file://src/rag/core/indexer.py#L242-L550)
- [src/rag/config.py:83-89](file://src/rag/config.py#L83-L89)
- [src/rag/core/chunker.py:385-444](file://src/rag/core/chunker.py#L385-L444)

## Core Components
- FileWatcher: Polls a repository directory at a configurable interval, compares modification times, and invokes a callback with a list of changed files. It coalesces rapid changes and ensures only one callback runs at a time.
- index_repository: Performs incremental indexing by scanning for changed files since the last run, chunking and enriching content, and upserting vectors while deleting obsolete chunks for removed files.
- Server integration: Starts the watcher when the daemon initializes with watch mode enabled.
- CLI watch flag: Sets the watched path via an environment variable and launches the daemon in watch mode.
- Configuration: Controls which directories are skipped and chunk sizing.

**Section sources**
- [src/rag/core/watcher.py:18-184](file://src/rag/core/watcher.py#L18-L184)
- [src/rag/core/indexer.py:242-550](file://src/rag/core/indexer.py#L242-L550)
- [src/rag/server.py:664-691](file://src/rag/server.py#L664-L691)
- [src/rag/cli.py:175-220](file://src/rag/cli.py#L175-L220)
- [src/rag/config.py:83-89](file://src/rag/config.py#L83-L89)

## Architecture Overview
The live indexing pipeline connects the file watcher to the indexing engine and vector store. The watcher monitors file system changes and triggers incremental re-indexing. The indexer computes diffs, chunks files, enriches metadata, and updates the vector store and storage.

```mermaid
sequenceDiagram
participant CLI as "CLI"
participant Server as "Server"
participant Watcher as "FileWatcher"
participant Indexer as "index_repository"
participant VS as "VectorStore"
participant DB as "SQLite Storage"
CLI->>Server : "rag start --watch"<br/>sets RAG_WATCH_PATH
Server->>Watcher : create FileWatcher(watch_path, on_change)
Watcher->>Watcher : start()<br/>capture initial mtimes
loop Every poll_interval
Watcher->>Watcher : scan()<br/>compare mtimes
alt Changes detected
Watcher->>Indexer : index_repository(repo_path, full=False)
Indexer->>VS : delete_by_filter(file_path)<br/>delete old chunks
Indexer->>VS : upsert(chunks)<br/>insert new chunks
Indexer->>DB : upsert_code_chunks()<br/>persist chunk metadata
Indexer->>DB : reset_overview()/rebuild_overview()<br/>update counters
Indexer-->>Watcher : IndexResult
else No changes
Watcher->>Watcher : continue polling
end
end
```

**Diagram sources**
- [src/rag/cli.py:175-220](file://src/rag/cli.py#L175-L220)
- [src/rag/server.py:664-691](file://src/rag/server.py#L664-L691)
- [src/rag/core/watcher.py:50-184](file://src/rag/core/watcher.py#L50-L184)
- [src/rag/core/indexer.py:242-550](file://src/rag/core/indexer.py#L242-L550)

## Detailed Component Analysis

### FileWatcher: Polling-based Change Detection
The FileWatcher periodically scans the repository for file changes by comparing modification times. It respects configured skip directories and supported file extensions. Changes are coalesced into a single in-flight callback to prevent overlapping re-indexing.

Key behaviors:
- Initialization captures baseline mtimes to avoid reporting every file on first tick
- Poll loop sleeps for a configurable interval between scans
- Change detection identifies new/modified and deleted files
- Single-flight dispatch ensures only one callback runs at a time
- Callback receives a sorted list of changed file paths (relative to repo root)

```mermaid
flowchart TD
Start(["Start watcher"]) --> Init["Capture initial mtimes"]
Init --> Sleep["Sleep poll_interval"]
Sleep --> Scan["Scan repository for file mtimes"]
Scan --> Compare{"Compare with cached mtimes"}
Compare --> |New/Modified| AddChanged["Add to changed set"]
Compare --> |Deleted| AddDeleted["Add to changed set"]
Compare --> |No changes| Sleep
AddChanged --> Dispatch["Ensure dispatch task"]
AddDeleted --> Dispatch
Dispatch --> Drain["Drain dirty set"]
Drain --> Callback["Invoke on_change(sorted(changed))"]
Callback --> Await{"Is callback coroutine?"}
Await --> |Yes| AwaitTask["Await completion"]
Await --> |No| Sleep
AwaitTask --> Sleep
```

**Diagram sources**
- [src/rag/core/watcher.py:50-184](file://src/rag/core/watcher.py#L50-L184)

**Section sources**
- [src/rag/core/watcher.py:26-108](file://src/rag/core/watcher.py#L26-L108)
- [src/rag/core/watcher.py:110-184](file://src/rag/core/watcher.py#L110-L184)

### Indexer: Incremental Re-indexing Pipeline
The indexer performs incremental re-indexing by:
- Determining which files changed since the last run using Git commands
- Computing file hashes to detect content changes without Git diff
- Discovering files respecting skip directories and supported extensions
- Chunking and enriching content using language-aware chunking
- Upserting vectors into the vector store and updating SQLite storage
- Deleting chunks for removed files and rebuilding overview statistics when needed

```mermaid
flowchart TD
StartIdx(["Start index_repository"]) --> LoadState["Load IndexState"]
LoadState --> HeadCommit["Get HEAD commit"]
HeadCommit --> Discover["Discover files (respect skip_dirs)"]
Discover --> Diff{"Incremental mode?"}
Diff --> |Yes| GitDiff["git diff --name-only since HEAD"]
GitDiff --> SelectChanged["Select changed files"]
SelectChanged --> HashCheck["Hash changed files since last run"]
HashCheck --> MergeChanged["Merge changed + hash-changed files"]
Diff --> |No| AllFiles["Use all files"]
MergeChanged --> Chunk["Chunk code/document content"]
AllFiles --> Chunk
Chunk --> Enrich["Enrich metadata (LSP, patterns)"]
Enrich --> DeleteOld["Delete old chunks for changed files"]
DeleteOld --> Upsert["Upsert new chunks"]
Upsert --> Persist["Persist chunk metadata to SQLite"]
Persist --> Removed["Detect removed files and delete their chunks"]
Removed --> Overview{"Post-index maintenance?"}
Overview --> |Yes| Rebuild["Rebuild overview stats"]
Overview --> |No| Skip["Skip maintenance"]
Rebuild --> SaveState["Save IndexState"]
Skip --> SaveState
SaveState --> EndIdx(["Complete"])
```

**Diagram sources**
- [src/rag/core/indexer.py:242-550](file://src/rag/core/indexer.py#L242-L550)
- [src/rag/core/chunker.py:385-444](file://src/rag/core/chunker.py#L385-L444)

**Section sources**
- [src/rag/core/indexer.py:242-550](file://src/rag/core/indexer.py#L242-L550)
- [src/rag/core/chunker.py:385-444](file://src/rag/core/chunker.py#L385-L444)

### Server Integration: Watch Mode Lifecycle
The server starts the watcher during daemon initialization when watch mode is enabled. It sets up an on-change callback that triggers incremental re-indexing and emits events for progress visibility.

```mermaid
sequenceDiagram
participant Server as "Server lifespan"
participant Env as "Environment"
participant Watcher as "FileWatcher"
participant Indexer as "index_repository"
Server->>Env : read RAG_WATCH_PATH
alt watch_path set
Server->>Watcher : create FileWatcher(watch_path, on_change)
Watcher->>Watcher : start()
Watcher->>Indexer : index_repository(full=False)
Indexer-->>Watcher : IndexResult
else watch_path not set
Server-->>Server : continue without watcher
end
```

**Diagram sources**
- [src/rag/server.py:664-691](file://src/rag/server.py#L664-L691)

**Section sources**
- [src/rag/server.py:664-691](file://src/rag/server.py#L664-L691)

### CLI: Enabling Watch Mode
The CLI supports enabling watch mode via a command-line option. When enabled, it sets the watched path via an environment variable and launches the daemon in watch mode.

```mermaid
flowchart TD
CLIStart["rag start --watch"] --> SetEnv["Set RAG_WATCH_PATH to current directory"]
SetEnv --> Launch["Start Uvicorn server"]
Launch --> ServerInit["Server lifespan"]
ServerInit --> WatcherStart["Start FileWatcher if RAG_WATCH_PATH set"]
```

**Diagram sources**
- [src/rag/cli.py:175-220](file://src/rag/cli.py#L175-L220)

**Section sources**
- [src/rag/cli.py:175-220](file://src/rag/cli.py#L175-L220)

## Dependency Analysis
The live indexing system exhibits clear separation of concerns:
- FileWatcher depends on configuration for skip directories and supported extensions
- Indexer depends on configuration for chunk sizing and skip directories
- Server orchestrates the watcher lifecycle and delegates re-indexing to the indexer
- CLI controls watch mode activation and sets the watched path

```mermaid
graph TB
CLI["CLI"] --> Server["Server"]
Server --> Watcher["FileWatcher"]
Watcher --> Config["Settings"]
Watcher --> Indexer["index_repository"]
Indexer --> Config
Indexer --> Chunker["Chunker"]
Indexer --> VS["VectorStore"]
Indexer --> DB["SQLite Storage"]
```

**Diagram sources**
- [src/rag/cli.py:175-220](file://src/rag/cli.py#L175-L220)
- [src/rag/server.py:664-691](file://src/rag/server.py#L664-L691)
- [src/rag/core/watcher.py:26-108](file://src/rag/core/watcher.py#L26-L108)
- [src/rag/core/indexer.py:242-550](file://src/rag/core/indexer.py#L242-L550)
- [src/rag/config.py:83-89](file://src/rag/config.py#L83-L89)
- [src/rag/core/chunker.py:385-444](file://src/rag/core/chunker.py#L385-L444)

**Section sources**
- [src/rag/cli.py:175-220](file://src/rag/cli.py#L175-L220)
- [src/rag/server.py:664-691](file://src/rag/server.py#L664-L691)
- [src/rag/core/watcher.py:26-108](file://src/rag/core/watcher.py#L26-L108)
- [src/rag/core/indexer.py:242-550](file://src/rag/core/indexer.py#L242-L550)
- [src/rag/config.py:83-89](file://src/rag/config.py#L83-L89)
- [src/rag/core/chunker.py:385-444](file://src/rag/core/chunker.py#L385-L444)

## Performance Considerations
- Poll interval tuning: Adjust the watcher’s poll interval to balance responsiveness and CPU usage. Longer intervals reduce overhead but delay re-indexing.
- Skip directories: Configure skip_dirs to exclude large or irrelevant directories (e.g., build artifacts, caches) to minimize scanning overhead.
- Batch size and chunk sizing: Tune max_chunk_chars and embedding batch sizes to optimize throughput without sacrificing interactivity.
- Concurrency control: The single-flight dispatch prevents overlapping re-indexing, reducing contention and redundant work.
- Incremental indexing: Only changed files and hashes are processed, minimizing work compared to full re-indexing.
- Vector store operations: Deletion and upsert operations are scoped to changed files, reducing write amplification.

[No sources needed since this section provides general guidance]

## Troubleshooting Guide
Common issues and resolutions:
- Watcher not starting: Verify that RAG_WATCH_PATH is set and points to a valid directory. Confirm that the server started with watch mode enabled.
- No re-indexing after changes: Ensure the poll interval is appropriate and that the callback is invoked. Check logs for watcher_poll_error or watcher_callback_error.
- Excessive CPU usage: Increase the poll interval or expand skip_dirs to exclude unnecessary directories.
- Large working directories: Reduce the number of tracked files by adjusting skip_dirs and supported extensions.
- Permission errors: Ensure the process has read permissions for watched files and directories.
- Indexing stalls: Monitor the single-flight dispatch behavior; long-running re-indexes will coalesce changes into a single run.

**Section sources**
- [src/rag/core/watcher.py:50-184](file://src/rag/core/watcher.py#L50-L184)
- [src/rag/server.py:664-691](file://src/rag/server.py#L664-L691)

## Conclusion
The real-time file watching and live indexing system provides responsive, incremental updates to the vector store by combining a polling-based file watcher with an efficient indexing pipeline. By configuring watch mode, tuning poll intervals, and optimizing skip directories and chunk sizing, teams can maintain accurate search results with minimal impact on development workflows.