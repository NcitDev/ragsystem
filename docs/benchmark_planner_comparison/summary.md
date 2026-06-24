# Smart Agent Planner Comparison — LLM (agy) vs Fallback

Real retrieval eval: the agent receives **only the natural-language question** and drives the live `/search` pipeline. Files returned are scored against the golden set. No tool-path hints, no handed-in symbols, no oracle backfill.

**top_k:** 15  |  **repeats:** 1

## Averages

| Planner | Avg Coverage | Avg Precision | Avg Files | Avg Latency |
|---|---:|---:|---:|---:|
| fallback | 15.0% | 7.3% | 8.3 | 413ms |
| llm | 18.3% | 6.4% | 8.8 | 10098ms |

## Per-scenario

### S1 [feature] — Add a sticker pack install event. What's the existing pattern?

Golden: 3 files

| Planner | Strategy | Plan Qs | Files | Golden Hit | Coverage | Precision | Latency |
|---|---|---:|---:|---:|---:|---:|---:|
| fallback | hybrid | 1 | 8.0 | 0/3 | 0.0% | 0.0% | 418ms |
| llm | hybrid | 5 | 8.0 | 0/3 | 0.0% | 0.0% | 10728ms |

### S2 [migration] — Find the database migration interface and show a concrete migration

Golden: 2 files

| Planner | Strategy | Plan Qs | Files | Golden Hit | Coverage | Precision | Latency |
|---|---|---:|---:|---:|---:|---:|---:|
| fallback | hybrid | 2 | 8.0 | 0/2 | 0.0% | 0.0% | 508ms |
| llm | hybrid | 5 | 8.0 | 0/2 | 0.0% | 0.0% | 10434ms |

### S3 [arch] — Show me the main classes in the sticker pack management system

Golden: 3 files

| Planner | Strategy | Plan Qs | Files | Golden Hit | Coverage | Precision | Latency |
|---|---|---:|---:|---:|---:|---:|---:|
| fallback | hybrid | 1 | 3.0 | 0/3 | 0.0% | 0.0% | 318ms |
| llm | hybrid | 5 | 3.0 | 0/3 | 0.0% | 0.0% | 9940ms |

### S4 [feature] — I need to add a new backup feature. Show me how FullBackupExporter works

Golden: 2 files

| Planner | Strategy | Plan Qs | Files | Golden Hit | Coverage | Precision | Latency |
|---|---|---:|---:|---:|---:|---:|---:|
| fallback | hybrid | 1 | 4.0 | 1/2 | 50.0% | 25.0% | 372ms |
| llm | hybrid | 4 | 5.0 | 1/2 | 50.0% | 20.0% | 9705ms |

### S5 [migration] — Find deprecated job migration code that should be cleaned up

Golden: 3 files

| Planner | Strategy | Plan Qs | Files | Golden Hit | Coverage | Precision | Latency |
|---|---|---:|---:|---:|---:|---:|---:|
| fallback | hybrid | 1 | 12.0 | 0/3 | 0.0% | 0.0% | 238ms |
| llm | hybrid | 5 | 13.0 | 1/3 | 33.3% | 7.7% | 9702ms |

### S6 [impact] — If I change the Job base class, what code breaks? Show all subclasses

Golden: 4 files

| Planner | Strategy | Plan Qs | Files | Golden Hit | Coverage | Precision | Latency |
|---|---|---:|---:|---:|---:|---:|---:|
| fallback | hybrid | 1 | 9.0 | 0/4 | 0.0% | 0.0% | 327ms |
| llm | hybrid | 6 | 9.0 | 0/4 | 0.0% | 0.0% | 10454ms |

### S7 [refactor] — Rename SignalDatabaseMigration interface. Find all implementors and callers

Golden: 3 files

| Planner | Strategy | Plan Qs | Files | Golden Hit | Coverage | Precision | Latency |
|---|---|---:|---:|---:|---:|---:|---:|
| fallback | hybrid | 2 | 5.0 | 2/3 | 66.7% | 40.0% | 466ms |
| llm | hybrid | 4 | 7.0 | 2/3 | 66.7% | 28.6% | 10448ms |

### S8 [impact] — Who calls Recipient? Show me the blast radius of changing the Recipient model

Golden: 3 files

| Planner | Strategy | Plan Qs | Files | Golden Hit | Coverage | Precision | Latency |
|---|---|---:|---:|---:|---:|---:|---:|
| fallback | hybrid | 1 | 13.0 | 1/3 | 33.3% | 7.7% | 371ms |
| llm | hybrid | 4 | 13.0 | 1/3 | 33.3% | 7.7% | 9573ms |

### S9 [info] — How does the chat backup encryption and passphrase system work?

Golden: 3 files

| Planner | Strategy | Plan Qs | Files | Golden Hit | Coverage | Precision | Latency |
|---|---|---:|---:|---:|---:|---:|---:|
| fallback | hybrid | 2 | 11.0 | 0/3 | 0.0% | 0.0% | 496ms |
| llm | hybrid | 5 | 12.0 | 0/3 | 0.0% | 0.0% | 9574ms |

### S10 [debug] — Trace how push notifications are received and processed by the app

Golden: 3 files

| Planner | Strategy | Plan Qs | Files | Golden Hit | Coverage | Precision | Latency |
|---|---|---:|---:|---:|---:|---:|---:|
| fallback | hybrid | 2 | 10.0 | 0/3 | 0.0% | 0.0% | 619ms |
| llm | hybrid | 7 | 10.0 | 0/3 | 0.0% | 0.0% | 10418ms |
