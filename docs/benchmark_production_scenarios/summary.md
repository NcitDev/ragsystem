# Production Scenarios Benchmark

**Scenarios:** 10  
**Agents:** Smart Agent (production skill), AST-Index, Graphify, Naive Agent (context-pack only), Vanilla (rg)

## Overall Averages

| Agent | Avg Turns | Avg Tokens | Avg Precision | Avg Signal% | Avg Coverage | Avg Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 7.3 | 3,683 | 70.9% | 93.3% | 94.2% | 181ms |
| AST-Index | 13.9 | 16,417 | 23.1% | 64.9% | 72.5% | 133ms |
| Graphify | 11.0 | 18,517 | 15.0% | 42.0% | 55.0% | 4262ms |
| Vanilla (rg) | 11.4 | 19,839 | 15.0% | 54.0% | 36.7% | 300ms |
| Serena | 4.5 | 3,436 | 92.5% | 100.0% | 65.8% | 10856ms |

## Per-Scenario Results

### Scenario 1: FEATURE — Add a sticker pack install event. What's the existing pattern?

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 4 | 1,933 | 100.0% | 100.0% | 100.0% | 87ms |
| AST-Index | 13 | 15,537 | 37.5% | 62.5% | 100.0% | 181ms |
| Graphify | 11 | 7,859 | 20.0% | 30.0% | 66.7% | 4065ms |
| Vanilla (rg) | 12 | 30,093 | 10.0% | 30.0% | 33.3% | 145ms |
| Serena | 4 | 1,726 | 100.0% | 100.0% | 66.7% | 28080ms |

### Scenario 2: MIGRATION — Find the database migration interface and show a concrete migration

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 3 | 1,142 | 100.0% | 100.0% | 100.0% | 72ms |
| AST-Index | 15 | 7,647 | 20.0% | 100.0% | 100.0% | 90ms |
| Graphify | 11 | 7,447 | 20.0% | 100.0% | 100.0% | 4666ms |
| Vanilla (rg) | 12 | 21,486 | 0.0% | 50.0% | 0.0% | 181ms |
| Serena | 4 | 2,652 | 100.0% | 100.0% | 100.0% | 3957ms |

### Scenario 3: ARCH — Show me the main classes in the sticker pack management system

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 4 | 2,319 | 100.0% | 100.0% | 100.0% | 68ms |
| AST-Index | 17 | 14,523 | 30.0% | 60.0% | 100.0% | 264ms |
| Graphify | 11 | 21,757 | 30.0% | 60.0% | 100.0% | 4032ms |
| Vanilla (rg) | 12 | 23,052 | 20.0% | 90.0% | 66.7% | 457ms |
| Serena | 6 | 2,828 | 100.0% | 100.0% | 100.0% | 5860ms |

### Scenario 4: FEATURE — I need to add a new backup feature. Show me how FullBackupExporter works

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 3 | 1,224 | 100.0% | 100.0% | 100.0% | 55ms |
| AST-Index | 15 | 18,001 | 20.0% | 70.0% | 100.0% | 146ms |
| Graphify | 11 | 31,240 | 10.0% | 10.0% | 50.0% | 4806ms |
| Vanilla (rg) | 12 | 19,025 | 10.0% | 50.0% | 50.0% | 395ms |
| Serena | 4 | 5,256 | 100.0% | 100.0% | 100.0% | 3883ms |

### Scenario 5: MIGRATION — Find deprecated job migration code that should be cleaned up

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 4 | 1,200 | 66.7% | 100.0% | 66.7% | 48ms |
| AST-Index | 8 | 5,305 | 33.3% | 66.7% | 33.3% | 120ms |
| Graphify | 11 | 17,679 | 10.0% | 20.0% | 33.3% | 4079ms |
| Vanilla (rg) | 4 | 5,106 | 50.0% | 50.0% | 33.3% | 162ms |
| Serena | 4 | 256 | 50.0% | 100.0% | 33.3% | 3901ms |

### Scenario 6: IMPACT — If I change the Job base class, what code breaks? Show all subclasses

**Tool path:** `resolve_usages`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 12 | 5,136 | 27.3% | 100.0% | 75.0% | 49ms |
| AST-Index | 13 | 24,559 | 10.0% | 70.0% | 25.0% | 52ms |
| Graphify | 11 | 19,758 | 0.0% | 40.0% | 0.0% | 3841ms |
| Vanilla (rg) | 12 | 18,563 | 20.0% | 100.0% | 50.0% | 73ms |
| Serena | 3 | 5,000 | 100.0% | 100.0% | 25.0% | 3907ms |

### Scenario 7: REFACTOR — Rename SignalDatabaseMigration interface. Find all implementors and callers

**Tool path:** `resolve_usages`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 16 | 6,201 | 20.0% | 100.0% | 100.0% | 46ms |
| AST-Index | 13 | 7,647 | 20.0% | 100.0% | 66.7% | 87ms |
| Graphify | 11 | 7,447 | 20.0% | 100.0% | 66.7% | 3738ms |
| Vanilla (rg) | 12 | 6,458 | 0.0% | 100.0% | 0.0% | 123ms |
| Serena | 4 | 113 | 100.0% | 100.0% | 33.3% | 7556ms |

### Scenario 8: IMPACT — Who calls Recipient? Show me the blast radius of changing the Recipient model

**Tool path:** `resolve_usages`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 16 | 14,081 | 20.0% | 33.3% | 100.0% | 52ms |
| AST-Index | 13 | 32,070 | 10.0% | 30.0% | 33.3% | 56ms |
| Graphify | 11 | 23,711 | 10.0% | 10.0% | 33.3% | 4315ms |
| Vanilla (rg) | 12 | 25,484 | 0.0% | 10.0% | 0.0% | 622ms |
| Serena | 5 | 11,232 | 100.0% | 100.0% | 33.3% | 41358ms |

### Scenario 9: INFO — How does the chat backup encryption and passphrase system work?

**Tool path:** `context_pack_then_resolve`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 5 | 1,674 | 100.0% | 100.0% | 100.0% | 844ms |
| AST-Index | 15 | 22,340 | 20.0% | 20.0% | 66.7% | 113ms |
| Graphify | 11 | 23,974 | 10.0% | 20.0% | 33.3% | 4541ms |
| Vanilla (rg) | 13 | 25,622 | 20.0% | 20.0% | 66.7% | 365ms |
| Serena | 4 | 2,794 | 100.0% | 100.0% | 66.7% | 4014ms |

### Scenario 10: DEBUG — Trace how push notifications are received and processed by the app

**Tool path:** `context_pack_then_resolve`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 6 | 1,921 | 75.0% | 100.0% | 100.0% | 487ms |
| AST-Index | 17 | 16,539 | 30.0% | 70.0% | 100.0% | 225ms |
| Graphify | 11 | 24,301 | 20.0% | 30.0% | 66.7% | 4537ms |
| Vanilla (rg) | 13 | 23,502 | 20.0% | 40.0% | 66.7% | 474ms |
| Serena | 7 | 2,508 | 75.0% | 100.0% | 100.0% | 6042ms |

## Per-Category Summary

### ARCH (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 2,319 | 100.0% | 100.0% |
| AST-Index | 14,523 | 30.0% | 100.0% |
| Graphify | 21,757 | 30.0% | 100.0% |
| Vanilla (rg) | 23,052 | 20.0% | 66.7% |
| Serena | 2,828 | 100.0% | 100.0% |

### DEBUG (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,921 | 75.0% | 100.0% |
| AST-Index | 16,539 | 30.0% | 100.0% |
| Graphify | 24,301 | 20.0% | 66.7% |
| Vanilla (rg) | 23,502 | 20.0% | 66.7% |
| Serena | 2,508 | 75.0% | 100.0% |

### FEATURE (2 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,578 | 100.0% | 100.0% |
| AST-Index | 16,769 | 28.8% | 100.0% |
| Graphify | 19,550 | 15.0% | 58.3% |
| Vanilla (rg) | 24,559 | 10.0% | 41.7% |
| Serena | 3,491 | 100.0% | 83.3% |

### IMPACT (2 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 9,608 | 23.6% | 87.5% |
| AST-Index | 28,314 | 10.0% | 29.2% |
| Graphify | 21,734 | 5.0% | 16.7% |
| Vanilla (rg) | 22,024 | 10.0% | 25.0% |
| Serena | 8,116 | 100.0% | 29.2% |

### INFO (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,674 | 100.0% | 100.0% |
| AST-Index | 22,340 | 20.0% | 66.7% |
| Graphify | 23,974 | 10.0% | 33.3% |
| Vanilla (rg) | 25,622 | 20.0% | 66.7% |
| Serena | 2,794 | 100.0% | 66.7% |

### MIGRATION (2 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,171 | 83.3% | 83.3% |
| AST-Index | 6,476 | 26.6% | 66.7% |
| Graphify | 12,563 | 15.0% | 66.7% |
| Vanilla (rg) | 13,296 | 25.0% | 16.7% |
| Serena | 1,454 | 75.0% | 66.7% |

### REFACTOR (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 6,201 | 20.0% | 100.0% |
| AST-Index | 7,647 | 20.0% | 66.7% |
| Graphify | 7,447 | 20.0% | 66.7% |
| Vanilla (rg) | 6,458 | 0.0% | 0.0% |
| Serena | 113 | 100.0% | 33.3% |
