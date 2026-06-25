# All-Tools Retrieval Benchmark

Every tool gets only the natural-language question; query terms come from a single shared extractor (not golden symbols). Each tool's top-K candidate files are scored against the golden set. No oracle backfill.

**top_k:** 15  |  **tools:** vanilla-rg, ast-index, graphify, rag-resolve, rag-smart, rag-search, rag-agentic, rag-agentic-pool

## Averages

Golden found = golden files retrieved out of the whole pool. Coverage = golden found / golden pool. Precision = golden found / files returned.

| Tool | Golden Found | Files Returned | Context Tokens | Coverage | Precision | Avg Latency |
|---|---:|---:|---:|---:|---:|---:|
| vanilla-rg | 1/26 | 144 | 558565 | 3.8% | 0.7% | 56ms |
| ast-index | 5/26 | 144 | 65332 | 19.2% | 3.5% | 168ms |
| graphify | 5/26 | 137 | 461442 | 19.2% | 3.6% | 3667ms |
| rag-resolve | 5/26 | 115 | 112163 | 19.2% | 4.3% | 1665ms |
| rag-smart | 5/26 | 131 | 295252 | 19.2% | 3.8% | 5484ms |
| rag-search | 4/26 | 57 | 58657 | 15.4% | 7.0% | 19051ms |
| rag-agentic | 17/26 | 149 | 90452 | 65.4% | 11.4% | 2935ms |
| rag-agentic-pool | 18/26 | 217 | 44364 | 69.2% | 8.3% | 2898ms |

## Per-scenario

### S1 [feature] — Add a sticker pack install event. What's the existing pattern?

Golden: 3 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| vanilla-rg | 15 | 0/3 | 0.0% | 0.0% | 90ms |
| ast-index | 15 | 0/3 | 0.0% | 0.0% | 286ms |
| graphify | 15 | 0/3 | 0.0% | 0.0% | 8594ms |
| rag-resolve | 15 | 0/3 | 0.0% | 0.0% | 3066ms |
| rag-smart | 14 | 0/3 | 0.0% | 0.0% | 8916ms |
| rag-search | 1 | 0/3 | 0.0% | 0.0% | 24159ms |
| rag-agentic | 15 | 2/3 | 66.7% | 13.3% | 2418ms |
| rag-agentic-pool | 16 | 2/3 | 66.7% | 12.5% | 2421ms |

### S2 [migration] — Find the database migration interface and show a concrete migration

Golden: 2 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| vanilla-rg | 15 | 0/2 | 0.0% | 0.0% | 80ms |
| ast-index | 15 | 0/2 | 0.0% | 0.0% | 184ms |
| graphify | 15 | 0/2 | 0.0% | 0.0% | 3397ms |
| rag-resolve | 14 | 0/2 | 0.0% | 0.0% | 1626ms |
| rag-smart | 13 | 0/2 | 0.0% | 0.0% | 7190ms |
| rag-search | 1 | 0/2 | 0.0% | 0.0% | 17846ms |
| rag-agentic | 15 | 2/2 | 100.0% | 13.3% | 2302ms |
| rag-agentic-pool | 18 | 2/2 | 100.0% | 11.1% | 2269ms |

### S3 [arch] — Show me the main classes in the sticker pack management system

Golden: 3 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| vanilla-rg | 15 | 0/3 | 0.0% | 0.0% | 106ms |
| ast-index | 15 | 0/3 | 0.0% | 0.0% | 303ms |
| graphify | 15 | 0/3 | 0.0% | 0.0% | 3135ms |
| rag-resolve | 15 | 0/3 | 0.0% | 0.0% | 2687ms |
| rag-smart | 15 | 0/3 | 0.0% | 0.0% | 6917ms |
| rag-search | 11 | 0/3 | 0.0% | 0.0% | 17285ms |
| rag-agentic | 15 | 2/3 | 66.7% | 13.3% | 2348ms |
| rag-agentic-pool | 16 | 2/3 | 66.7% | 12.5% | 2252ms |

### S4 [feature] — I need to add a new backup feature. Show me how FullBackupExporter works

Golden: 2 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| vanilla-rg | 9 | 1/2 | 50.0% | 11.1% | 19ms |
| ast-index | 9 | 1/2 | 50.0% | 11.1% | 123ms |
| graphify | 15 | 1/2 | 50.0% | 6.7% | 2810ms |
| rag-resolve | 8 | 1/2 | 50.0% | 12.5% | 858ms |
| rag-smart | 14 | 1/2 | 50.0% | 7.1% | 7826ms |
| rag-search | 4 | 1/2 | 50.0% | 25.0% | 19204ms |
| rag-agentic | 15 | 2/2 | 100.0% | 13.3% | 990ms |
| rag-agentic-pool | 16 | 2/2 | 100.0% | 12.5% | 942ms |

### S5 [migration] — Find deprecated job migration code that should be cleaned up

Golden: 3 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| vanilla-rg | 15 | 0/3 | 0.0% | 0.0% | 36ms |
| ast-index | 15 | 0/3 | 0.0% | 0.0% | 75ms |
| graphify | 15 | 0/3 | 0.0% | 0.0% | 3003ms |
| rag-resolve | 2 | 0/3 | 0.0% | 0.0% | 796ms |
| rag-smart | 12 | 0/3 | 0.0% | 0.0% | 6954ms |
| rag-search | 6 | 1/3 | 33.3% | 16.7% | 16827ms |
| rag-agentic | 15 | 3/3 | 100.0% | 20.0% | 2402ms |
| rag-agentic-pool | 22 | 3/3 | 100.0% | 13.6% | 2314ms |

### S6 [impact] — If I change the Job base class, what code breaks? Show all subclasses

Golden: 3 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| vanilla-rg | 15 | 0/3 | 0.0% | 0.0% | 35ms |
| ast-index | 15 | 1/3 | 33.3% | 6.7% | 83ms |
| graphify | 15 | 0/3 | 0.0% | 0.0% | 3575ms |
| rag-resolve | 15 | 1/3 | 33.3% | 6.7% | 852ms |
| rag-smart | 8 | 1/3 | 33.3% | 12.5% | 801ms |
| rag-search | 11 | 0/3 | 0.0% | 0.0% | 17117ms |
| rag-agentic | 15 | 1/3 | 33.3% | 6.7% | 4579ms |
| rag-agentic-pool | 46 | 1/3 | 33.3% | 2.2% | 4523ms |

### S7 [refactor] — Rename SignalDatabaseMigration interface. Find all implementors and callers

Golden: 2 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| vanilla-rg | 15 | 0/2 | 0.0% | 0.0% | 20ms |
| ast-index | 15 | 2/2 | 100.0% | 13.3% | 107ms |
| graphify | 2 | 2/2 | 100.0% | 100.0% | 2675ms |
| rag-resolve | 15 | 2/2 | 100.0% | 13.3% | 846ms |
| rag-smart | 15 | 2/2 | 100.0% | 13.3% | 904ms |
| rag-search | 7 | 2/2 | 100.0% | 28.6% | 18694ms |
| rag-agentic | 15 | 2/2 | 100.0% | 13.3% | 3864ms |
| rag-agentic-pool | 15 | 2/2 | 100.0% | 13.3% | 3818ms |

### S8 [impact] — Who calls Recipient? Show me the blast radius of changing the Recipient model

Golden: 3 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| vanilla-rg | 15 | 0/3 | 0.0% | 0.0% | 20ms |
| ast-index | 15 | 1/3 | 33.3% | 6.7% | 66ms |
| graphify | 15 | 2/3 | 66.7% | 13.3% | 2892ms |
| rag-resolve | 5 | 1/3 | 33.3% | 20.0% | 783ms |
| rag-smart | 15 | 1/3 | 33.3% | 6.7% | 842ms |
| rag-search | 1 | 0/3 | 0.0% | 0.0% | 19152ms |
| rag-agentic | 15 | 0/3 | 0.0% | 0.0% | 5643ms |
| rag-agentic-pool | 31 | 1/3 | 33.3% | 3.2% | 5628ms |

### S9 [info] — How does the chat backup encryption and passphrase system work?

Golden: 2 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| vanilla-rg | 15 | 0/2 | 0.0% | 0.0% | 94ms |
| ast-index | 15 | 0/2 | 0.0% | 0.0% | 356ms |
| graphify | 15 | 0/2 | 0.0% | 0.0% | 3527ms |
| rag-resolve | 15 | 0/2 | 0.0% | 0.0% | 3442ms |
| rag-smart | 14 | 0/2 | 0.0% | 0.0% | 7171ms |
| rag-search | 7 | 0/2 | 0.0% | 0.0% | 18587ms |
| rag-agentic | 15 | 2/2 | 100.0% | 13.3% | 2418ms |
| rag-agentic-pool | 23 | 2/2 | 100.0% | 8.7% | 2422ms |

### S10 [debug] — Trace how push notifications are received and processed by the app

Golden: 3 files

| Tool | Files | Golden Hit | Coverage | Precision | Latency |
|---|---:|---:|---:|---:|---:|
| vanilla-rg | 15 | 0/3 | 0.0% | 0.0% | 64ms |
| ast-index | 15 | 0/3 | 0.0% | 0.0% | 98ms |
| graphify | 15 | 0/3 | 0.0% | 0.0% | 3066ms |
| rag-resolve | 11 | 0/3 | 0.0% | 0.0% | 1697ms |
| rag-smart | 11 | 0/3 | 0.0% | 0.0% | 7318ms |
| rag-search | 8 | 0/3 | 0.0% | 0.0% | 21642ms |
| rag-agentic | 14 | 1/3 | 33.3% | 7.1% | 2384ms |
| rag-agentic-pool | 14 | 1/3 | 33.3% | 7.1% | 2395ms |
