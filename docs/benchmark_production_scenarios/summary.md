# Production Scenarios Benchmark

**Scenarios:** 10  
**Agents:** Smart Agent (production skill), AST-Index, Graphify, Naive Agent (context-pack only), Vanilla (rg)

## Overall Averages

| Agent | Avg Turns | Avg Tokens | Avg Precision | Avg Signal% | Avg Coverage | Avg Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 7.7 | 4,904 | 70.2% | 89.5% | 94.2% | 125ms |
| AST-Index | 13.9 | 16,417 | 23.1% | 64.9% | 72.5% | 110ms |
| Graphify | 11.0 | 15,258 | 15.0% | 53.0% | 55.0% | 5142ms |
| Naive Agent | 38.0 | 13,918 | 7.3% | 10.6% | 94.2% | 1689ms |
| Vanilla (rg) | 11.4 | 19,686 | 15.0% | 55.0% | 36.7% | 164ms |

## Per-Scenario Results

### Scenario 1: FEATURE — Add a sticker pack install event. What's the existing pattern?

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 4 | 1,933 | 100.0% | 100.0% | 100.0% | 81ms |
| AST-Index | 13 | 15,537 | 37.5% | 62.5% | 100.0% | 192ms |
| Graphify | 11 | 16,453 | 20.0% | 50.0% | 66.7% | 5665ms |
| Naive Agent | 42 | 15,195 | 7.3% | 7.3% | 100.0% | 1168ms |
| Vanilla (rg) | 12 | 30,093 | 10.0% | 30.0% | 33.3% | 368ms |

### Scenario 2: MIGRATION — Find the database migration interface and show a concrete migration

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 3 | 1,142 | 100.0% | 100.0% | 100.0% | 31ms |
| AST-Index | 15 | 7,647 | 20.0% | 100.0% | 100.0% | 71ms |
| Graphify | 11 | 9,809 | 20.0% | 100.0% | 100.0% | 4345ms |
| Naive Agent | 29 | 13,466 | 7.1% | 7.1% | 100.0% | 613ms |
| Vanilla (rg) | 12 | 21,486 | 0.0% | 50.0% | 0.0% | 128ms |

### Scenario 3: ARCH — Show me the main classes in the sticker pack management system

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 4 | 2,319 | 100.0% | 100.0% | 100.0% | 46ms |
| AST-Index | 17 | 14,523 | 30.0% | 60.0% | 100.0% | 129ms |
| Graphify | 11 | 16,949 | 30.0% | 40.0% | 100.0% | 4616ms |
| Naive Agent | 43 | 15,212 | 7.1% | 7.1% | 100.0% | 1170ms |
| Vanilla (rg) | 12 | 19,613 | 20.0% | 100.0% | 66.7% | 128ms |

### Scenario 4: FEATURE — I need to add a new backup feature. Show me how FullBackupExporter works

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 3 | 1,224 | 100.0% | 100.0% | 100.0% | 39ms |
| AST-Index | 15 | 18,001 | 20.0% | 70.0% | 100.0% | 120ms |
| Graphify | 11 | 17,007 | 10.0% | 10.0% | 50.0% | 5076ms |
| Naive Agent | 41 | 10,487 | 5.0% | 10.0% | 100.0% | 888ms |
| Vanilla (rg) | 12 | 19,025 | 10.0% | 50.0% | 50.0% | 124ms |

### Scenario 5: MIGRATION — Find deprecated job migration code that should be cleaned up

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 4 | 1,200 | 66.7% | 100.0% | 66.7% | 37ms |
| AST-Index | 8 | 5,305 | 33.3% | 66.7% | 33.3% | 112ms |
| Graphify | 11 | 6,558 | 10.0% | 20.0% | 33.3% | 5586ms |
| Naive Agent | 40 | 10,617 | 5.1% | 5.1% | 66.7% | 833ms |
| Vanilla (rg) | 4 | 5,106 | 50.0% | 50.0% | 33.3% | 111ms |

### Scenario 6: IMPACT — If I change the Job base class, what code breaks? Show all subclasses

**Tool path:** `resolve_usages`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 14 | 14,245 | 23.1% | 61.5% | 75.0% | 42ms |
| AST-Index | 13 | 24,559 | 10.0% | 70.0% | 25.0% | 55ms |
| Graphify | 11 | 16,400 | 0.0% | 100.0% | 0.0% | 6373ms |
| Naive Agent | 40 | 17,484 | 7.7% | 7.7% | 75.0% | 9066ms |
| Vanilla (rg) | 12 | 18,563 | 20.0% | 100.0% | 50.0% | 87ms |

### Scenario 7: REFACTOR — Rename SignalDatabaseMigration interface. Find all implementors and callers

**Tool path:** `resolve_usages`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 18 | 10,179 | 17.6% | 100.0% | 100.0% | 32ms |
| AST-Index | 13 | 7,647 | 20.0% | 100.0% | 66.7% | 67ms |
| Graphify | 11 | 9,809 | 20.0% | 100.0% | 66.7% | 4816ms |
| Naive Agent | 37 | 12,419 | 8.3% | 27.8% | 100.0% | 958ms |
| Vanilla (rg) | 12 | 6,458 | 0.0% | 100.0% | 0.0% | 130ms |

### Scenario 8: IMPACT — Who calls Recipient? Show me the blast radius of changing the Recipient model

**Tool path:** `resolve_usages`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 16 | 13,203 | 20.0% | 33.3% | 100.0% | 33ms |
| AST-Index | 13 | 32,070 | 10.0% | 30.0% | 33.3% | 48ms |
| Graphify | 11 | 20,014 | 10.0% | 50.0% | 33.3% | 5449ms |
| Naive Agent | 39 | 20,126 | 7.9% | 15.8% | 100.0% | 850ms |
| Vanilla (rg) | 12 | 27,695 | 0.0% | 10.0% | 0.0% | 163ms |

### Scenario 9: INFO — How does the chat backup encryption and passphrase system work?

**Tool path:** `context_pack_then_resolve`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 5 | 1,674 | 100.0% | 100.0% | 100.0% | 464ms |
| AST-Index | 15 | 22,340 | 20.0% | 20.0% | 66.7% | 112ms |
| Graphify | 11 | 14,158 | 10.0% | 10.0% | 33.3% | 4799ms |
| Naive Agent | 34 | 11,480 | 9.1% | 9.1% | 100.0% | 758ms |
| Vanilla (rg) | 13 | 25,622 | 20.0% | 20.0% | 66.7% | 181ms |

### Scenario 10: DEBUG — Trace how push notifications are received and processed by the app

**Tool path:** `context_pack_then_resolve`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 6 | 1,921 | 75.0% | 100.0% | 100.0% | 449ms |
| AST-Index | 17 | 16,539 | 30.0% | 70.0% | 100.0% | 194ms |
| Graphify | 11 | 25,421 | 20.0% | 50.0% | 66.7% | 4694ms |
| Naive Agent | 35 | 12,695 | 8.8% | 8.8% | 100.0% | 590ms |
| Vanilla (rg) | 13 | 23,198 | 20.0% | 40.0% | 66.7% | 222ms |

## Per-Category Summary

### ARCH (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 2,319 | 100.0% | 100.0% |
| AST-Index | 14,523 | 30.0% | 100.0% |
| Graphify | 16,949 | 30.0% | 100.0% |
| Naive Agent | 15,212 | 7.1% | 100.0% |
| Vanilla (rg) | 19,613 | 20.0% | 66.7% |

### DEBUG (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,921 | 75.0% | 100.0% |
| AST-Index | 16,539 | 30.0% | 100.0% |
| Graphify | 25,421 | 20.0% | 66.7% |
| Naive Agent | 12,695 | 8.8% | 100.0% |
| Vanilla (rg) | 23,198 | 20.0% | 66.7% |

### FEATURE (2 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,578 | 100.0% | 100.0% |
| AST-Index | 16,769 | 28.8% | 100.0% |
| Graphify | 16,730 | 15.0% | 58.3% |
| Naive Agent | 12,841 | 6.2% | 100.0% |
| Vanilla (rg) | 24,559 | 10.0% | 41.7% |

### IMPACT (2 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 13,724 | 21.6% | 87.5% |
| AST-Index | 28,314 | 10.0% | 29.2% |
| Graphify | 18,207 | 5.0% | 16.7% |
| Naive Agent | 18,805 | 7.8% | 87.5% |
| Vanilla (rg) | 23,129 | 10.0% | 25.0% |

### INFO (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,674 | 100.0% | 100.0% |
| AST-Index | 22,340 | 20.0% | 66.7% |
| Graphify | 14,158 | 10.0% | 33.3% |
| Naive Agent | 11,480 | 9.1% | 100.0% |
| Vanilla (rg) | 25,622 | 20.0% | 66.7% |

### MIGRATION (2 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,171 | 83.3% | 83.3% |
| AST-Index | 6,476 | 26.6% | 66.7% |
| Graphify | 8,184 | 15.0% | 66.7% |
| Naive Agent | 12,042 | 6.1% | 83.3% |
| Vanilla (rg) | 13,296 | 25.0% | 16.7% |

### REFACTOR (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 10,179 | 17.6% | 100.0% |
| AST-Index | 7,647 | 20.0% | 66.7% |
| Graphify | 9,809 | 20.0% | 66.7% |
| Naive Agent | 12,419 | 8.3% | 100.0% |
| Vanilla (rg) | 6,458 | 0.0% | 0.0% |
