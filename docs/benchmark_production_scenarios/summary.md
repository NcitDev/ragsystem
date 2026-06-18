# Production Scenarios Benchmark

**Scenarios:** 10  
**Agents:** Smart Agent (production skill), AST-Index, Graphify, Naive Agent (context-pack only), Vanilla (rg)

## Overall Averages

| Agent | Avg Turns | Avg Tokens | Avg Precision | Avg Signal% | Avg Coverage | Avg Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 11.8 | 5,750 | 68.3% | 89.7% | 94.2% | 142ms |
| AST-Index | 13.9 | 16,793 | 23.1% | 64.9% | 72.5% | 104ms |
| Graphify | 11.0 | 15,959 | 17.0% | 54.0% | 61.7% | 4145ms |
| Naive Agent | 39.0 | 14,110 | 7.1% | 12.0% | 94.2% | 1504ms |
| Vanilla (rg) | 11.4 | 21,534 | 15.0% | 47.0% | 36.7% | 134ms |

## Per-Scenario Results

### Scenario 1: FEATURE — Add a sticker pack install event. What's the existing pattern?

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 4 | 1,933 | 100.0% | 100.0% | 100.0% | 54ms |
| AST-Index | 13 | 15,537 | 37.5% | 62.5% | 100.0% | 181ms |
| Graphify | 11 | 14,067 | 30.0% | 60.0% | 100.0% | 4437ms |
| Naive Agent | 42 | 15,195 | 7.3% | 7.3% | 100.0% | 656ms |
| Vanilla (rg) | 12 | 32,985 | 10.0% | 30.0% | 33.3% | 132ms |

### Scenario 2: MIGRATION — Find the database migration interface and show a concrete migration

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 3 | 1,142 | 100.0% | 100.0% | 100.0% | 29ms |
| AST-Index | 15 | 7,647 | 20.0% | 100.0% | 100.0% | 74ms |
| Graphify | 11 | 9,668 | 20.0% | 100.0% | 100.0% | 3613ms |
| Naive Agent | 30 | 16,193 | 6.9% | 6.9% | 100.0% | 600ms |
| Vanilla (rg) | 12 | 21,486 | 0.0% | 50.0% | 0.0% | 144ms |

### Scenario 3: ARCH — Show me the main classes in the sticker pack management system

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 4 | 2,319 | 100.0% | 100.0% | 100.0% | 39ms |
| AST-Index | 17 | 14,523 | 30.0% | 60.0% | 100.0% | 122ms |
| Graphify | 11 | 18,150 | 30.0% | 50.0% | 100.0% | 3561ms |
| Naive Agent | 43 | 14,919 | 7.1% | 7.1% | 100.0% | 757ms |
| Vanilla (rg) | 12 | 23,052 | 20.0% | 90.0% | 66.7% | 140ms |

### Scenario 4: FEATURE — I need to add a new backup feature. Show me how FullBackupExporter works

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 3 | 1,224 | 100.0% | 100.0% | 100.0% | 40ms |
| AST-Index | 15 | 18,001 | 20.0% | 70.0% | 100.0% | 112ms |
| Graphify | 11 | 15,903 | 10.0% | 10.0% | 50.0% | 3745ms |
| Naive Agent | 41 | 10,565 | 5.0% | 10.0% | 100.0% | 580ms |
| Vanilla (rg) | 12 | 19,025 | 10.0% | 50.0% | 50.0% | 115ms |

### Scenario 5: MIGRATION — Find deprecated job migration code that should be cleaned up

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 4 | 1,200 | 66.7% | 100.0% | 66.7% | 30ms |
| AST-Index | 8 | 5,305 | 33.3% | 66.7% | 33.3% | 95ms |
| Graphify | 11 | 6,804 | 10.0% | 20.0% | 33.3% | 3758ms |
| Naive Agent | 40 | 10,617 | 5.1% | 5.1% | 66.7% | 528ms |
| Vanilla (rg) | 4 | 5,106 | 50.0% | 50.0% | 33.3% | 137ms |

### Scenario 6: IMPACT — If I change the Job base class, what code breaks? Show all subclasses

**Tool path:** `resolve_usages`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 17 | 13,355 | 18.8% | 68.8% | 75.0% | 27ms |
| AST-Index | 13 | 24,559 | 10.0% | 70.0% | 25.0% | 42ms |
| Graphify | 11 | 18,913 | 0.0% | 100.0% | 0.0% | 3787ms |
| Naive Agent | 40 | 17,484 | 7.7% | 7.7% | 75.0% | 8734ms |
| Vanilla (rg) | 12 | 18,563 | 20.0% | 100.0% | 50.0% | 67ms |

### Scenario 7: REFACTOR — Rename SignalDatabaseMigration interface. Find all implementors and callers

**Tool path:** `resolve_usages`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 53 | 16,862 | 5.8% | 100.0% | 100.0% | 28ms |
| AST-Index | 13 | 7,647 | 20.0% | 100.0% | 66.7% | 61ms |
| Graphify | 11 | 9,668 | 20.0% | 100.0% | 66.7% | 4456ms |
| Naive Agent | 42 | 14,003 | 7.3% | 39.0% | 100.0% | 810ms |
| Vanilla (rg) | 12 | 21,062 | 0.0% | 40.0% | 0.0% | 131ms |

### Scenario 8: IMPACT — Who calls Recipient? Show me the blast radius of changing the Recipient model

**Tool path:** `resolve_usages`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 19 | 15,866 | 16.7% | 27.8% | 100.0% | 44ms |
| AST-Index | 13 | 35,828 | 10.0% | 30.0% | 33.3% | 51ms |
| Graphify | 11 | 29,278 | 10.0% | 20.0% | 33.3% | 4728ms |
| Naive Agent | 43 | 17,962 | 7.1% | 19.0% | 100.0% | 706ms |
| Vanilla (rg) | 12 | 28,144 | 0.0% | 0.0% | 0.0% | 138ms |

### Scenario 9: INFO — How does the chat backup encryption and passphrase system work?

**Tool path:** `context_pack_then_resolve`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 5 | 1,674 | 100.0% | 100.0% | 100.0% | 611ms |
| AST-Index | 15 | 22,340 | 20.0% | 20.0% | 66.7% | 112ms |
| Graphify | 11 | 17,453 | 10.0% | 20.0% | 33.3% | 4845ms |
| Naive Agent | 34 | 11,480 | 9.1% | 9.1% | 100.0% | 955ms |
| Vanilla (rg) | 13 | 25,622 | 20.0% | 20.0% | 66.7% | 178ms |

### Scenario 10: DEBUG — Trace how push notifications are received and processed by the app

**Tool path:** `context_pack_then_resolve`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 6 | 1,921 | 75.0% | 100.0% | 100.0% | 519ms |
| AST-Index | 17 | 16,539 | 30.0% | 70.0% | 100.0% | 189ms |
| Graphify | 11 | 19,684 | 30.0% | 60.0% | 100.0% | 4522ms |
| Naive Agent | 35 | 12,685 | 8.8% | 8.8% | 100.0% | 710ms |
| Vanilla (rg) | 13 | 20,299 | 20.0% | 40.0% | 66.7% | 162ms |

## Per-Category Summary

### ARCH (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 2,319 | 100.0% | 100.0% |
| AST-Index | 14,523 | 30.0% | 100.0% |
| Graphify | 18,150 | 30.0% | 100.0% |
| Naive Agent | 14,919 | 7.1% | 100.0% |
| Vanilla (rg) | 23,052 | 20.0% | 66.7% |

### DEBUG (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,921 | 75.0% | 100.0% |
| AST-Index | 16,539 | 30.0% | 100.0% |
| Graphify | 19,684 | 30.0% | 100.0% |
| Naive Agent | 12,685 | 8.8% | 100.0% |
| Vanilla (rg) | 20,299 | 20.0% | 66.7% |

### FEATURE (2 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,578 | 100.0% | 100.0% |
| AST-Index | 16,769 | 28.8% | 100.0% |
| Graphify | 14,985 | 20.0% | 75.0% |
| Naive Agent | 12,880 | 6.2% | 100.0% |
| Vanilla (rg) | 26,005 | 10.0% | 41.7% |

### IMPACT (2 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 14,610 | 17.8% | 87.5% |
| AST-Index | 30,194 | 10.0% | 29.2% |
| Graphify | 24,096 | 5.0% | 16.7% |
| Naive Agent | 17,723 | 7.4% | 87.5% |
| Vanilla (rg) | 23,354 | 10.0% | 25.0% |

### INFO (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,674 | 100.0% | 100.0% |
| AST-Index | 22,340 | 20.0% | 66.7% |
| Graphify | 17,453 | 10.0% | 33.3% |
| Naive Agent | 11,480 | 9.1% | 100.0% |
| Vanilla (rg) | 25,622 | 20.0% | 66.7% |

### MIGRATION (2 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,171 | 83.3% | 83.3% |
| AST-Index | 6,476 | 26.6% | 66.7% |
| Graphify | 8,236 | 15.0% | 66.7% |
| Naive Agent | 13,405 | 6.0% | 83.3% |
| Vanilla (rg) | 13,296 | 25.0% | 16.7% |

### REFACTOR (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 16,862 | 5.8% | 100.0% |
| AST-Index | 7,647 | 20.0% | 66.7% |
| Graphify | 9,668 | 20.0% | 66.7% |
| Naive Agent | 14,003 | 7.3% | 100.0% |
| Vanilla (rg) | 21,062 | 0.0% | 0.0% |
