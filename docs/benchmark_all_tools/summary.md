# All-Tools Retrieval Benchmark

Every tool gets only the natural-language question; query terms come from a single shared extractor (not golden symbols). Each tool's top-K candidate files are scored against the golden set. No oracle backfill.

**top_k:** 15  |  **tools:** rag-agentic, rag-smart, rag-search, rag-resolve

## Averages

| Tool | Avg Coverage | Avg Precision | Avg Files | Avg Latency | Errors |
|---|---:|---:|---:|---:|---:|
| rag-agentic | 36.7% | 9.4% | 11.8 | 26488ms | 0 |
| rag-smart | 17.5% | 3.9% | 12.2 | 602ms | 0 |
| rag-search | 15.0% | 6.1% | 8.5 | 10118ms | 0 |
| rag-resolve | 17.5% | 4.1% | 11.3 | 161ms | 0 |

## Per-scenario

### S1 [feature] — Add a sticker pack install event. What's the existing pattern?

Golden: 3 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| rag-agentic | 13 | 2/3 | 66.7% | 15.4% | 19910ms |
| rag-smart | 14 | 0/3 | 0.0% | 0.0% | 934ms |
| rag-search | 8 | 0/3 | 0.0% | 0.0% | 9497ms |
| rag-resolve | 15 | 0/3 | 0.0% | 0.0% | 360ms |

### S2 [migration] — Find the database migration interface and show a concrete migration

Golden: 2 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| rag-agentic | 8 | 0/2 | 0.0% | 0.0% | 40642ms |
| rag-smart | 6 | 0/2 | 0.0% | 0.0% | 1174ms |
| rag-search | 8 | 0/2 | 0.0% | 0.0% | 10337ms |
| rag-resolve | 4 | 0/2 | 0.0% | 0.0% | 117ms |

### S3 [arch] — Show me the main classes in the sticker pack management system

Golden: 3 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| rag-agentic | 8 | 0/3 | 0.0% | 0.0% | 40316ms |
| rag-smart | 13 | 0/3 | 0.0% | 0.0% | 746ms |
| rag-search | 3 | 0/3 | 0.0% | 0.0% | 10264ms |
| rag-resolve | 15 | 0/3 | 0.0% | 0.0% | 239ms |

### S4 [feature] — I need to add a new backup feature. Show me how FullBackupExporter works

Golden: 2 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| rag-agentic | 4 | 1/2 | 50.0% | 25.0% | 40569ms |
| rag-smart | 11 | 1/2 | 50.0% | 9.1% | 831ms |
| rag-search | 4 | 1/2 | 50.0% | 25.0% | 10390ms |
| rag-resolve | 8 | 1/2 | 50.0% | 12.5% | 30ms |

### S5 [migration] — Find deprecated job migration code that should be cleaned up

Golden: 3 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| rag-agentic | 15 | 1/3 | 33.3% | 6.7% | 21235ms |
| rag-smart | 12 | 0/3 | 0.0% | 0.0% | 701ms |
| rag-search | 12 | 0/3 | 0.0% | 0.0% | 9758ms |
| rag-resolve | 2 | 0/3 | 0.0% | 0.0% | 29ms |

### S6 [impact] — If I change the Job base class, what code breaks? Show all subclasses

Golden: 4 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| rag-agentic | 15 | 2/4 | 50.0% | 13.3% | 11503ms |
| rag-smart | 11 | 1/4 | 25.0% | 9.1% | 45ms |
| rag-search | 9 | 0/4 | 0.0% | 0.0% | 9581ms |
| rag-resolve | 15 | 1/4 | 25.0% | 6.7% | 39ms |

### S7 [refactor] — Rename SignalDatabaseMigration interface. Find all implementors and callers

Golden: 3 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| rag-agentic | 15 | 2/3 | 66.7% | 13.3% | 7871ms |
| rag-smart | 15 | 2/3 | 66.7% | 13.3% | 40ms |
| rag-search | 7 | 2/3 | 66.7% | 28.6% | 9835ms |
| rag-resolve | 15 | 2/3 | 66.7% | 13.3% | 34ms |

### S8 [impact] — Who calls Recipient? Show me the blast radius of changing the Recipient model

Golden: 3 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| rag-agentic | 15 | 2/3 | 66.7% | 13.3% | 7880ms |
| rag-smart | 13 | 1/3 | 33.3% | 7.7% | 41ms |
| rag-search | 13 | 1/3 | 33.3% | 7.7% | 10438ms |
| rag-resolve | 12 | 1/3 | 33.3% | 8.3% | 37ms |

### S9 [info] — How does the chat backup encryption and passphrase system work?

Golden: 3 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| rag-agentic | 15 | 1/3 | 33.3% | 6.7% | 34275ms |
| rag-smart | 14 | 0/3 | 0.0% | 0.0% | 907ms |
| rag-search | 11 | 0/3 | 0.0% | 0.0% | 10515ms |
| rag-resolve | 15 | 0/3 | 0.0% | 0.0% | 662ms |

### S10 [debug] — Trace how push notifications are received and processed by the app

Golden: 3 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| rag-agentic | 10 | 0/3 | 0.0% | 0.0% | 40680ms |
| rag-smart | 13 | 0/3 | 0.0% | 0.0% | 602ms |
| rag-search | 10 | 0/3 | 0.0% | 0.0% | 10570ms |
| rag-resolve | 12 | 0/3 | 0.0% | 0.0% | 59ms |
