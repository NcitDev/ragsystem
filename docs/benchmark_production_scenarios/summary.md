# Production Scenarios Benchmark

**Scenarios:** 10  
**Agents:** Smart Agent (production skill), AST-Index, Graphify, Naive Agent (context-pack only), Vanilla (rg)

## Overall Averages

| Agent | Avg Turns | Avg Tokens | Avg Precision | Avg Signal% | Avg Coverage | Avg Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 6.7 | 4,155 | 73.3% | 91.9% | 94.2% | 162ms |
| AST-Index | 13.9 | 16,793 | 23.1% | 64.9% | 72.5% | 119ms |
| Graphify | 11.0 | 20,068 | 13.0% | 43.0% | 48.3% | 3638ms |
| Vanilla (rg) | 11.4 | 21,894 | 15.0% | 47.0% | 36.7% | 310ms |

## Per-Scenario Results

### Scenario 1: FEATURE — Add a sticker pack install event. What's the existing pattern?

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 4 | 1,933 | 100.0% | 100.0% | 100.0% | 95ms |
| AST-Index | 13 | 15,537 | 37.5% | 62.5% | 100.0% | 188ms |
| Graphify | 11 | 23,990 | 10.0% | 10.0% | 33.3% | 4174ms |
| Vanilla (rg) | 12 | 30,093 | 10.0% | 30.0% | 33.3% | 396ms |

### Scenario 2: MIGRATION — Find the database migration interface and show a concrete migration

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 3 | 1,142 | 100.0% | 100.0% | 100.0% | 54ms |
| AST-Index | 15 | 7,647 | 20.0% | 100.0% | 100.0% | 109ms |
| Graphify | 11 | 12,622 | 20.0% | 100.0% | 100.0% | 3178ms |
| Vanilla (rg) | 12 | 21,486 | 0.0% | 50.0% | 0.0% | 139ms |

### Scenario 3: ARCH — Show me the main classes in the sticker pack management system

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 4 | 2,319 | 100.0% | 100.0% | 100.0% | 60ms |
| AST-Index | 17 | 14,523 | 30.0% | 60.0% | 100.0% | 127ms |
| Graphify | 11 | 19,158 | 30.0% | 60.0% | 100.0% | 3418ms |
| Vanilla (rg) | 12 | 23,052 | 20.0% | 90.0% | 66.7% | 172ms |

### Scenario 4: FEATURE — I need to add a new backup feature. Show me how FullBackupExporter works

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 3 | 1,224 | 100.0% | 100.0% | 100.0% | 46ms |
| AST-Index | 15 | 18,001 | 20.0% | 70.0% | 100.0% | 134ms |
| Graphify | 11 | 26,308 | 10.0% | 20.0% | 50.0% | 3708ms |
| Vanilla (rg) | 12 | 19,025 | 10.0% | 50.0% | 50.0% | 450ms |

### Scenario 5: MIGRATION — Find deprecated job migration code that should be cleaned up

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 4 | 1,200 | 66.7% | 100.0% | 66.7% | 44ms |
| AST-Index | 8 | 5,305 | 33.3% | 66.7% | 33.3% | 129ms |
| Graphify | 11 | 18,447 | 0.0% | 10.0% | 0.0% | 3149ms |
| Vanilla (rg) | 4 | 5,106 | 50.0% | 50.0% | 33.3% | 174ms |

### Scenario 6: IMPACT — If I change the Job base class, what code breaks? Show all subclasses

**Tool path:** `resolve_usages`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 15 | 12,232 | 21.4% | 85.7% | 75.0% | 55ms |
| AST-Index | 13 | 24,559 | 10.0% | 70.0% | 25.0% | 54ms |
| Graphify | 11 | 17,002 | 0.0% | 30.0% | 0.0% | 4022ms |
| Vanilla (rg) | 12 | 18,693 | 20.0% | 100.0% | 50.0% | 367ms |

### Scenario 7: REFACTOR — Rename SignalDatabaseMigration interface. Find all implementors and callers

**Tool path:** `resolve_usages`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 7 | 3,827 | 50.0% | 100.0% | 100.0% | 41ms |
| AST-Index | 13 | 7,647 | 20.0% | 100.0% | 66.7% | 76ms |
| Graphify | 11 | 12,622 | 20.0% | 100.0% | 66.7% | 3598ms |
| Vanilla (rg) | 12 | 21,062 | 0.0% | 40.0% | 0.0% | 456ms |

### Scenario 8: IMPACT — Who calls Recipient? Show me the blast radius of changing the Recipient model

**Tool path:** `resolve_usages`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 16 | 14,081 | 20.0% | 33.3% | 100.0% | 42ms |
| AST-Index | 13 | 35,828 | 10.0% | 30.0% | 33.3% | 47ms |
| Graphify | 11 | 31,553 | 20.0% | 50.0% | 66.7% | 3553ms |
| Vanilla (rg) | 12 | 31,296 | 0.0% | 0.0% | 0.0% | 363ms |

### Scenario 9: INFO — How does the chat backup encryption and passphrase system work?

**Tool path:** `context_pack_then_resolve`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 5 | 1,674 | 100.0% | 100.0% | 100.0% | 684ms |
| AST-Index | 15 | 22,340 | 20.0% | 20.0% | 66.7% | 115ms |
| Graphify | 11 | 16,685 | 10.0% | 20.0% | 33.3% | 3758ms |
| Vanilla (rg) | 13 | 25,622 | 20.0% | 20.0% | 66.7% | 207ms |

### Scenario 10: DEBUG — Trace how push notifications are received and processed by the app

**Tool path:** `context_pack_then_resolve`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 6 | 1,921 | 75.0% | 100.0% | 100.0% | 501ms |
| AST-Index | 17 | 16,539 | 30.0% | 70.0% | 100.0% | 207ms |
| Graphify | 11 | 22,290 | 10.0% | 30.0% | 33.3% | 3823ms |
| Vanilla (rg) | 13 | 23,502 | 20.0% | 40.0% | 66.7% | 379ms |

## Per-Category Summary

### ARCH (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 2,319 | 100.0% | 100.0% |
| AST-Index | 14,523 | 30.0% | 100.0% |
| Graphify | 19,158 | 30.0% | 100.0% |
| Vanilla (rg) | 23,052 | 20.0% | 66.7% |

### DEBUG (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,921 | 75.0% | 100.0% |
| AST-Index | 16,539 | 30.0% | 100.0% |
| Graphify | 22,290 | 10.0% | 33.3% |
| Vanilla (rg) | 23,502 | 20.0% | 66.7% |

### FEATURE (2 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,578 | 100.0% | 100.0% |
| AST-Index | 16,769 | 28.8% | 100.0% |
| Graphify | 25,149 | 10.0% | 41.7% |
| Vanilla (rg) | 24,559 | 10.0% | 41.7% |

### IMPACT (2 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 13,156 | 20.7% | 87.5% |
| AST-Index | 30,194 | 10.0% | 29.2% |
| Graphify | 24,278 | 10.0% | 33.3% |
| Vanilla (rg) | 24,994 | 10.0% | 25.0% |

### INFO (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,674 | 100.0% | 100.0% |
| AST-Index | 22,340 | 20.0% | 66.7% |
| Graphify | 16,685 | 10.0% | 33.3% |
| Vanilla (rg) | 25,622 | 20.0% | 66.7% |

### MIGRATION (2 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,171 | 83.3% | 83.3% |
| AST-Index | 6,476 | 26.6% | 66.7% |
| Graphify | 15,534 | 10.0% | 50.0% |
| Vanilla (rg) | 13,296 | 25.0% | 16.7% |

### REFACTOR (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 3,827 | 50.0% | 100.0% |
| AST-Index | 7,647 | 20.0% | 66.7% |
| Graphify | 12,622 | 20.0% | 66.7% |
| Vanilla (rg) | 21,062 | 0.0% | 0.0% |
