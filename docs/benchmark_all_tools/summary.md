# All-Tools Retrieval Benchmark

Every tool gets only the natural-language question; query terms come from a single shared extractor (not golden symbols). Each tool's top-K candidate files are scored against the golden set. No oracle backfill.

**top_k:** 15  |  **tools:** serena

## Averages

| Tool | Avg Coverage | Avg Precision | Avg Files | Avg Latency | Errors |
|---|---:|---:|---:|---:|---:|
| serena | 17.5% | 42.5% | 5.5 | 3663ms | 0 |

## Per-scenario

### S1 [feature] — Add a sticker pack install event. What's the existing pattern?

Golden: 3 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| serena | 4 | 0/3 | 0.0% | 0.0% | 4350ms |

### S2 [migration] — Find the database migration interface and show a concrete migration

Golden: 2 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| serena | 15 | 0/2 | 0.0% | 0.0% | 3852ms |

### S3 [arch] — Show me the main classes in the sticker pack management system

Golden: 3 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| serena | 4 | 1/3 | 33.3% | 25.0% | 5719ms |

### S4 [feature] — I need to add a new backup feature. Show me how FullBackupExporter works

Golden: 2 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| serena | 1 | 1/2 | 50.0% | 100.0% | 1929ms |

### S5 [migration] — Find deprecated job migration code that should be cleaned up

Golden: 3 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| serena | 4 | 0/3 | 0.0% | 0.0% | 2093ms |

### S6 [impact] — If I change the Job base class, what code breaks? Show all subclasses

Golden: 4 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| serena | 1 | 1/4 | 25.0% | 100.0% | 2130ms |

### S7 [refactor] — Rename SignalDatabaseMigration interface. Find all implementors and callers

Golden: 3 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| serena | 1 | 1/3 | 33.3% | 100.0% | 1997ms |

### S8 [impact] — Who calls Recipient? Show me the blast radius of changing the Recipient model

Golden: 3 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| serena | 1 | 1/3 | 33.3% | 100.0% | 1934ms |

### S9 [info] — How does the chat backup encryption and passphrase system work?

Golden: 3 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| serena | 14 | 0/3 | 0.0% | 0.0% | 8166ms |

### S10 [debug] — Trace how push notifications are received and processed by the app

Golden: 3 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| serena | 10 | 0/3 | 0.0% | 0.0% | 4458ms |
