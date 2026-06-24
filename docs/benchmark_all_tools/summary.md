# All-Tools Retrieval Benchmark

Every tool gets only the natural-language question; query terms come from a single shared extractor (not golden symbols). Each tool's top-K candidate files are scored against the golden set. No oracle backfill.

**top_k:** 15  |  **tools:** rag-agentic

## Averages

Golden found = golden files retrieved out of the whole pool. Coverage = golden found / golden pool. Precision = golden found / files returned.

| Tool | Golden Found | Files Returned | Coverage | Precision | Avg Latency |
|---|---:|---:|---:|---:|---:|
| rag-agentic | 13/29 | 130 | 44.8% | 10.0% | 7814ms |

## Per-scenario

### S1 [feature] — Add a sticker pack install event. What's the existing pattern?

Golden: 3 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| rag-agentic | 15 | 1/3 | 33.3% | 6.7% | 7895ms |

### S2 [migration] — Find the database migration interface and show a concrete migration

Golden: 2 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| rag-agentic | 11 | 2/2 | 100.0% | 18.2% | 7092ms |

### S3 [arch] — Show me the main classes in the sticker pack management system

Golden: 3 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| rag-agentic | 15 | 0/3 | 0.0% | 0.0% | 7003ms |

### S4 [feature] — I need to add a new backup feature. Show me how FullBackupExporter works

Golden: 2 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| rag-agentic | 15 | 2/2 | 100.0% | 13.3% | 8790ms |

### S5 [migration] — Find deprecated job migration code that should be cleaned up

Golden: 3 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| rag-agentic | 14 | 2/3 | 66.7% | 14.3% | 6806ms |

### S6 [impact] — If I change the Job base class, what code breaks? Show all subclasses

Golden: 4 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| rag-agentic | 15 | 1/4 | 25.0% | 6.7% | 6959ms |

### S7 [refactor] — Rename SignalDatabaseMigration interface. Find all implementors and callers

Golden: 3 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| rag-agentic | 15 | 2/3 | 66.7% | 13.3% | 10931ms |

### S8 [impact] — Who calls Recipient? Show me the blast radius of changing the Recipient model

Golden: 3 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| rag-agentic | 15 | 1/3 | 33.3% | 6.7% | 7786ms |

### S9 [info] — How does the chat backup encryption and passphrase system work?

Golden: 3 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| rag-agentic | 6 | 1/3 | 33.3% | 16.7% | 7493ms |

### S10 [debug] — Trace how push notifications are received and processed by the app

Golden: 3 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| rag-agentic | 9 | 1/3 | 33.3% | 11.1% | 7383ms |
