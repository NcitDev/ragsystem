# Production Scenarios Benchmark

**Scenarios:** 10  
**Agents:** Smart Agent (production skill), AST-Index, Graphify, Naive Agent (context-pack only), Vanilla (rg)

## Overall Averages

| Agent | Avg Turns | Avg Tokens | Avg Precision | Avg Signal% | Avg Coverage | Avg Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 7.7 | 4,904 | 70.2% | 89.5% | 94.2% | 121ms |
| AST-Index | 13.9 | 16,318 | 23.1% | 64.9% | 72.5% | 106ms |
| Graphify | 11.0 | 17,317 | 10.0% | 47.0% | 35.0% | 4248ms |
| Naive Agent | 38.3 | 13,712 | 7.3% | 10.7% | 94.2% | 1517ms |
| Vanilla (rg) | 11.4 | 21,198 | 14.0% | 48.0% | 33.3% | 127ms |

## Per-Scenario Results

### Scenario 1: FEATURE — Add a sticker pack install event. What's the existing pattern?

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 4 | 1,933 | 100.0% | 100.0% | 100.0% | 66ms |
| AST-Index | 13 | 15,537 | 37.5% | 62.5% | 100.0% | 186ms |
| Graphify | 11 | 20,289 | 10.0% | 40.0% | 33.3% | 4921ms |
| Naive Agent | 42 | 15,195 | 7.3% | 7.3% | 100.0% | 648ms |
| Vanilla (rg) | 12 | 25,542 | 10.0% | 30.0% | 33.3% | 110ms |

### Scenario 2: MIGRATION — Find the database migration interface and show a concrete migration

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 3 | 1,142 | 100.0% | 100.0% | 100.0% | 32ms |
| AST-Index | 15 | 7,647 | 20.0% | 100.0% | 100.0% | 72ms |
| Graphify | 11 | 4,574 | 0.0% | 100.0% | 0.0% | 3844ms |
| Naive Agent | 29 | 13,466 | 7.1% | 7.1% | 100.0% | 564ms |
| Vanilla (rg) | 12 | 21,486 | 0.0% | 50.0% | 0.0% | 124ms |

### Scenario 3: ARCH — Show me the main classes in the sticker pack management system

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 4 | 2,319 | 100.0% | 100.0% | 100.0% | 52ms |
| AST-Index | 17 | 14,523 | 30.0% | 60.0% | 100.0% | 132ms |
| Graphify | 11 | 20,441 | 30.0% | 60.0% | 100.0% | 3993ms |
| Naive Agent | 43 | 14,919 | 7.1% | 7.1% | 100.0% | 768ms |
| Vanilla (rg) | 12 | 23,052 | 20.0% | 90.0% | 66.7% | 125ms |

### Scenario 4: FEATURE — I need to add a new backup feature. Show me how FullBackupExporter works

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 3 | 1,224 | 100.0% | 100.0% | 100.0% | 32ms |
| AST-Index | 15 | 18,001 | 20.0% | 70.0% | 100.0% | 118ms |
| Graphify | 11 | 25,250 | 10.0% | 10.0% | 50.0% | 4112ms |
| Naive Agent | 41 | 10,491 | 5.0% | 10.0% | 100.0% | 822ms |
| Vanilla (rg) | 12 | 19,025 | 10.0% | 50.0% | 50.0% | 122ms |

### Scenario 5: MIGRATION — Find deprecated job migration code that should be cleaned up

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 4 | 1,200 | 66.7% | 100.0% | 66.7% | 35ms |
| AST-Index | 8 | 5,305 | 33.3% | 66.7% | 33.3% | 115ms |
| Graphify | 11 | 11,442 | 10.0% | 20.0% | 33.3% | 4039ms |
| Naive Agent | 40 | 10,617 | 5.1% | 5.1% | 66.7% | 567ms |
| Vanilla (rg) | 4 | 5,106 | 50.0% | 50.0% | 33.3% | 123ms |

### Scenario 6: IMPACT — If I change the Job base class, what code breaks? Show all subclasses

**Tool path:** `resolve_usages`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 14 | 14,245 | 23.1% | 61.5% | 75.0% | 38ms |
| AST-Index | 13 | 24,559 | 10.0% | 70.0% | 25.0% | 43ms |
| Graphify | 11 | 18,162 | 0.0% | 40.0% | 0.0% | 3919ms |
| Naive Agent | 40 | 17,484 | 7.7% | 7.7% | 75.0% | 8704ms |
| Vanilla (rg) | 12 | 18,563 | 20.0% | 100.0% | 50.0% | 66ms |

### Scenario 7: REFACTOR — Rename SignalDatabaseMigration interface. Find all implementors and callers

**Tool path:** `resolve_usages`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 18 | 10,179 | 17.6% | 100.0% | 100.0% | 30ms |
| AST-Index | 13 | 7,647 | 20.0% | 100.0% | 66.7% | 58ms |
| Graphify | 11 | 4,574 | 0.0% | 100.0% | 0.0% | 4424ms |
| Naive Agent | 38 | 12,833 | 8.1% | 27.0% | 100.0% | 1106ms |
| Vanilla (rg) | 12 | 21,486 | 0.0% | 50.0% | 0.0% | 126ms |

### Scenario 8: IMPACT — Who calls Recipient? Show me the blast radius of changing the Recipient model

**Tool path:** `resolve_usages`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 16 | 13,203 | 20.0% | 33.3% | 100.0% | 32ms |
| AST-Index | 13 | 31,087 | 10.0% | 30.0% | 33.3% | 45ms |
| Graphify | 11 | 34,022 | 10.0% | 30.0% | 33.3% | 4124ms |
| Naive Agent | 43 | 18,125 | 7.1% | 16.7% | 100.0% | 581ms |
| Vanilla (rg) | 12 | 29,161 | 0.0% | 10.0% | 0.0% | 127ms |

### Scenario 9: INFO — How does the chat backup encryption and passphrase system work?

**Tool path:** `context_pack_then_resolve`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 5 | 1,674 | 100.0% | 100.0% | 100.0% | 434ms |
| AST-Index | 15 | 22,340 | 20.0% | 20.0% | 66.7% | 103ms |
| Graphify | 11 | 19,556 | 10.0% | 10.0% | 33.3% | 4329ms |
| Naive Agent | 35 | 11,462 | 8.8% | 8.8% | 100.0% | 787ms |
| Vanilla (rg) | 13 | 25,060 | 10.0% | 10.0% | 33.3% | 165ms |

### Scenario 10: DEBUG — Trace how push notifications are received and processed by the app

**Tool path:** `context_pack_then_resolve`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 6 | 1,921 | 75.0% | 100.0% | 100.0% | 458ms |
| AST-Index | 17 | 16,539 | 30.0% | 70.0% | 100.0% | 191ms |
| Graphify | 11 | 14,863 | 20.0% | 60.0% | 66.7% | 4775ms |
| Naive Agent | 32 | 12,523 | 9.7% | 9.7% | 100.0% | 620ms |
| Vanilla (rg) | 13 | 23,502 | 20.0% | 40.0% | 66.7% | 183ms |

## Per-Category Summary

### ARCH (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 2,319 | 100.0% | 100.0% |
| AST-Index | 14,523 | 30.0% | 100.0% |
| Graphify | 20,441 | 30.0% | 100.0% |
| Naive Agent | 14,919 | 7.1% | 100.0% |
| Vanilla (rg) | 23,052 | 20.0% | 66.7% |

### DEBUG (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,921 | 75.0% | 100.0% |
| AST-Index | 16,539 | 30.0% | 100.0% |
| Graphify | 14,863 | 20.0% | 66.7% |
| Naive Agent | 12,523 | 9.7% | 100.0% |
| Vanilla (rg) | 23,502 | 20.0% | 66.7% |

### FEATURE (2 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,578 | 100.0% | 100.0% |
| AST-Index | 16,769 | 28.8% | 100.0% |
| Graphify | 22,770 | 10.0% | 41.7% |
| Naive Agent | 12,843 | 6.2% | 100.0% |
| Vanilla (rg) | 22,284 | 10.0% | 41.7% |

### IMPACT (2 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 13,724 | 21.6% | 87.5% |
| AST-Index | 27,823 | 10.0% | 29.2% |
| Graphify | 26,092 | 5.0% | 16.7% |
| Naive Agent | 17,804 | 7.4% | 87.5% |
| Vanilla (rg) | 23,862 | 10.0% | 25.0% |

### INFO (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,674 | 100.0% | 100.0% |
| AST-Index | 22,340 | 20.0% | 66.7% |
| Graphify | 19,556 | 10.0% | 33.3% |
| Naive Agent | 11,462 | 8.8% | 100.0% |
| Vanilla (rg) | 25,060 | 10.0% | 33.3% |

### MIGRATION (2 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,171 | 83.3% | 83.3% |
| AST-Index | 6,476 | 26.6% | 66.7% |
| Graphify | 8,008 | 5.0% | 16.7% |
| Naive Agent | 12,042 | 6.1% | 83.3% |
| Vanilla (rg) | 13,296 | 25.0% | 16.7% |

### REFACTOR (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 10,179 | 17.6% | 100.0% |
| AST-Index | 7,647 | 20.0% | 66.7% |
| Graphify | 4,574 | 0.0% | 0.0% |
| Naive Agent | 12,833 | 8.1% | 100.0% |
| Vanilla (rg) | 21,486 | 0.0% | 0.0% |
