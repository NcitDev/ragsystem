# Rust (`rag-rs`) vs Python daemon — `/search` retrieval benchmark

Same ~/.rag state, same scenarios and golden sets as the planner benchmark. Python runs the full pipeline (planner → strategy dispatch → embedded Qdrant dense search → lexical promotion → scoring); the current Rust daemon answers `/search` from the SQLite code index with keyword scoring only.

**top_k:** 15  |  **repeats:** 3  |  **RSS:** python 117.6 MiB, rust 17.7 MiB

## Averages

| Target | Coverage | Precision | Files | Lat mean | Lat p50 | Lat p95 | Errors |
|---|---:|---:|---:|---:|---:|---:|---:|
| python-fallback | 50.8% | 16.1% | 10.3 | 226ms | 191ms | 343ms | 0 |
| python-llm | 28.6% | 8.1% | 7.6 | 19515ms | 18770ms | 25665ms | 1 |
| rust | 50.8% | 16.1% | 10.3 | 82ms | 16ms | 372ms | 0 |

## Section-8 acceptance gate (rust vs python-fallback)

- Coverage delta: **+0.0pp**, precision delta: **+0.0pp** — within ±2pp: **True**
- Non-LLM p95 no worse: **False**

## Per-scenario

### S1 [feature] — Add a sticker pack install event. What's the existing pattern?

Golden: 3 files

| Target | Strategy | Files | Golden Hit | Coverage | Precision | Lat mean |
|---|---|---:|---:|---:|---:|---:|
| python-fallback | hybrid | 9.0 | 2/3 | 66.7% | 22.2% | 168ms |
| python-llm | hybrid | 2.3 | 0/3 | 0.0% | 0.0% | 24271ms |
| rust | hybrid | 9.0 | 2/3 | 66.7% | 22.2% | 132ms |

### S2 [migration] — Find the database migration interface and show a concrete migration

Golden: 2 files

| Target | Strategy | Files | Golden Hit | Coverage | Precision | Lat mean |
|---|---|---:|---:|---:|---:|---:|
| python-fallback | hybrid | 13.0 | 2/2 | 100.0% | 15.4% | 307ms |
| python-llm | hybrid | 7.0 | 2/2 | 33.3% | 6.1% | 18311ms |
| rust | hybrid | 13.0 | 2/2 | 100.0% | 15.4% | 16ms |

### S3 [arch] — Show me the main classes in the sticker pack management system

Golden: 3 files

| Target | Strategy | Files | Golden Hit | Coverage | Precision | Lat mean |
|---|---|---:|---:|---:|---:|---:|
| python-fallback | hybrid | 9.0 | 1/3 | 33.3% | 11.1% | 147ms |
| python-llm | hybrid | 7.0 | 1/3 | 33.3% | 14.3% | 21356ms |
| rust | hybrid | 9.0 | 1/3 | 33.3% | 11.1% | 72ms |

### S4 [feature] — I need to add a new backup feature. Show me how FullBackupExporter works

Golden: 2 files

| Target | Strategy | Files | Golden Hit | Coverage | Precision | Lat mean |
|---|---|---:|---:|---:|---:|---:|
| python-fallback | hybrid | 4.0 | 1/2 | 50.0% | 25.0% | 218ms |
| python-llm | hybrid | 1.0 | 0/2 | 0.0% | 0.0% | 17178ms |
| rust | hybrid | 4.0 | 1/2 | 50.0% | 25.0% | 19ms |

### S5 [migration] — Find deprecated job migration code that should be cleaned up

Golden: 3 files

| Target | Strategy | Files | Golden Hit | Coverage | Precision | Lat mean |
|---|---|---:|---:|---:|---:|---:|
| python-fallback | hybrid | 14.0 | 2/3 | 66.7% | 14.3% | 176ms |
| python-llm | hybrid | 13.0 | 2/3 | 66.7% | 15.4% | 18532ms |
| rust | hybrid | 14.0 | 2/3 | 66.7% | 14.3% | 131ms |

### S6 [impact] — If I change the Job base class, what code breaks? Show all subclasses

Golden: 4 files

| Target | Strategy | Files | Golden Hit | Coverage | Precision | Lat mean |
|---|---|---:|---:|---:|---:|---:|
| python-fallback | hybrid | 13.0 | 1/4 | 25.0% | 7.7% | 186ms |
| python-llm | hybrid | 12.3 | 2/4 | 41.7% | 13.7% | 21077ms |
| rust | hybrid | 13.0 | 1/4 | 25.0% | 7.7% | 58ms |

### S7 [refactor] — Rename SignalDatabaseMigration interface. Find all implementors and callers

Golden: 3 files

| Target | Strategy | Files | Golden Hit | Coverage | Precision | Lat mean |
|---|---|---:|---:|---:|---:|---:|
| python-fallback | hybrid | 5.0 | 2/3 | 66.7% | 40.0% | 307ms |
| python-llm | hybrid | 3.0 | 2/3 | 22.2% | 8.3% | 19393ms |
| rust | hybrid | 5.0 | 2/3 | 66.7% | 40.0% | 116ms |

### S8 [impact] — Who calls Recipient? Show me the blast radius of changing the Recipient model

Golden: 3 files

| Target | Strategy | Files | Golden Hit | Coverage | Precision | Lat mean |
|---|---|---:|---:|---:|---:|---:|
| python-fallback | hybrid | 14.0 | 1/3 | 33.3% | 7.1% | 152ms |
| python-llm | hybrid | 9.7 | 0/3 | 22.2% | 4.8% | 18498ms |
| rust | hybrid | 14.0 | 1/3 | 33.3% | 7.1% | 12ms |

### S9 [info] — How does the chat backup encryption and passphrase system work?

Golden: 3 files

| Target | Strategy | Files | Golden Hit | Coverage | Precision | Lat mean |
|---|---|---:|---:|---:|---:|---:|
| python-fallback | hybrid | 10.0 | 1/3 | 33.3% | 10.0% | 295ms |
| python-llm | hybrid | 10.3 | 1/3 | 33.3% | 9.8% | 17825ms |
| rust | hybrid | 10.0 | 1/3 | 33.3% | 10.0% | 106ms |

### S10 [debug] — Trace how push notifications are received and processed by the app

Golden: 3 files

| Target | Strategy | Files | Golden Hit | Coverage | Precision | Lat mean |
|---|---|---:|---:|---:|---:|---:|
| python-fallback | hybrid | 12.0 | 1/3 | 33.3% | 8.3% | 303ms |
| python-llm | hybrid | 10.7 | 2/3 | 33.3% | 8.3% | 18385ms |
| rust | hybrid | 12.0 | 1/3 | 33.3% | 8.3% | 156ms |
