# Production Scenarios Benchmark

**Scenarios:** 10  
**Agents:** Smart Agent (production skill), AST-Index, Graphify, Naive Agent (context-pack only), Vanilla (rg)

## Overall Averages

| Agent | Avg Turns | Avg Tokens | Avg Precision | Avg Signal% | Avg Coverage | Avg Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 7.3 | 3,683 | 70.9% | 93.3% | 94.2% | 207ms |
| AST-Index | 13.9 | 16,417 | 23.1% | 64.9% | 72.5% | 171ms |
| Graphify | 11.0 | 17,357 | 16.0% | 45.0% | 58.3% | 4192ms |
| Vanilla (rg) | 11.4 | 20,472 | 15.0% | 54.0% | 36.7% | 264ms |
| Serena | 4.5 | 3,436 | 92.5% | 100.0% | 65.8% | 11024ms |

## Per-Scenario Results

### Scenario 1: FEATURE — Add a sticker pack install event. What's the existing pattern?

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 4 | 1,933 | 100.0% | 100.0% | 100.0% | 60ms |
| AST-Index | 13 | 15,537 | 37.5% | 62.5% | 100.0% | 298ms |
| Graphify | 11 | 14,446 | 10.0% | 10.0% | 33.3% | 3899ms |
| Vanilla (rg) | 12 | 30,093 | 10.0% | 30.0% | 33.3% | 156ms |
| Serena | 4 | 1,726 | 100.0% | 100.0% | 66.7% | 28022ms |

### Scenario 2: MIGRATION — Find the database migration interface and show a concrete migration

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 3 | 1,142 | 100.0% | 100.0% | 100.0% | 68ms |
| AST-Index | 15 | 7,647 | 20.0% | 100.0% | 100.0% | 114ms |
| Graphify | 11 | 7,507 | 20.0% | 100.0% | 100.0% | 5030ms |
| Vanilla (rg) | 12 | 21,486 | 0.0% | 50.0% | 0.0% | 158ms |
| Serena | 4 | 2,652 | 100.0% | 100.0% | 100.0% | 4024ms |

### Scenario 3: ARCH — Show me the main classes in the sticker pack management system

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 4 | 2,319 | 100.0% | 100.0% | 100.0% | 66ms |
| AST-Index | 17 | 14,523 | 30.0% | 60.0% | 100.0% | 147ms |
| Graphify | 11 | 17,265 | 30.0% | 50.0% | 100.0% | 4052ms |
| Vanilla (rg) | 12 | 19,613 | 20.0% | 100.0% | 66.7% | 345ms |
| Serena | 6 | 2,828 | 100.0% | 100.0% | 100.0% | 6152ms |

### Scenario 4: FEATURE — I need to add a new backup feature. Show me how FullBackupExporter works

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 3 | 1,224 | 100.0% | 100.0% | 100.0% | 49ms |
| AST-Index | 15 | 18,001 | 20.0% | 70.0% | 100.0% | 140ms |
| Graphify | 11 | 16,163 | 10.0% | 10.0% | 50.0% | 3882ms |
| Vanilla (rg) | 12 | 19,025 | 10.0% | 50.0% | 50.0% | 154ms |
| Serena | 4 | 5,256 | 100.0% | 100.0% | 100.0% | 3882ms |

### Scenario 5: MIGRATION — Find deprecated job migration code that should be cleaned up

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 4 | 1,200 | 66.7% | 100.0% | 66.7% | 39ms |
| AST-Index | 8 | 5,305 | 33.3% | 66.7% | 33.3% | 118ms |
| Graphify | 11 | 14,491 | 10.0% | 20.0% | 33.3% | 4033ms |
| Vanilla (rg) | 4 | 5,106 | 50.0% | 50.0% | 33.3% | 169ms |
| Serena | 4 | 256 | 50.0% | 100.0% | 33.3% | 3917ms |

### Scenario 6: IMPACT — If I change the Job base class, what code breaks? Show all subclasses

**Tool path:** `resolve_usages`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 12 | 5,136 | 27.3% | 100.0% | 75.0% | 56ms |
| AST-Index | 13 | 24,559 | 10.0% | 70.0% | 25.0% | 52ms |
| Graphify | 11 | 20,398 | 0.0% | 50.0% | 0.0% | 4278ms |
| Vanilla (rg) | 12 | 18,910 | 20.0% | 100.0% | 50.0% | 229ms |
| Serena | 3 | 5,000 | 100.0% | 100.0% | 25.0% | 3895ms |

### Scenario 7: REFACTOR — Rename SignalDatabaseMigration interface. Find all implementors and callers

**Tool path:** `resolve_usages`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 16 | 6,201 | 20.0% | 100.0% | 100.0% | 39ms |
| AST-Index | 13 | 7,647 | 20.0% | 100.0% | 66.7% | 84ms |
| Graphify | 11 | 7,507 | 20.0% | 100.0% | 66.7% | 3508ms |
| Vanilla (rg) | 12 | 6,458 | 0.0% | 100.0% | 0.0% | 140ms |
| Serena | 4 | 113 | 100.0% | 100.0% | 33.3% | 7729ms |

### Scenario 8: IMPACT — Who calls Recipient? Show me the blast radius of changing the Recipient model

**Tool path:** `resolve_usages`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 16 | 14,081 | 20.0% | 33.3% | 100.0% | 47ms |
| AST-Index | 13 | 32,070 | 10.0% | 30.0% | 33.3% | 55ms |
| Graphify | 11 | 35,476 | 10.0% | 20.0% | 33.3% | 3886ms |
| Vanilla (rg) | 12 | 29,699 | 0.0% | 0.0% | 0.0% | 141ms |
| Serena | 5 | 11,232 | 100.0% | 100.0% | 33.3% | 42459ms |

### Scenario 9: INFO — How does the chat backup encryption and passphrase system work?

**Tool path:** `context_pack_then_resolve`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 5 | 1,674 | 100.0% | 100.0% | 100.0% | 959ms |
| AST-Index | 15 | 22,340 | 20.0% | 20.0% | 66.7% | 305ms |
| Graphify | 11 | 18,938 | 20.0% | 30.0% | 66.7% | 5066ms |
| Vanilla (rg) | 13 | 25,622 | 20.0% | 20.0% | 66.7% | 573ms |
| Serena | 4 | 2,794 | 100.0% | 100.0% | 66.7% | 4134ms |

### Scenario 10: DEBUG — Trace how push notifications are received and processed by the app

**Tool path:** `context_pack_then_resolve`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 6 | 1,921 | 75.0% | 100.0% | 100.0% | 691ms |
| AST-Index | 17 | 16,539 | 30.0% | 70.0% | 100.0% | 398ms |
| Graphify | 11 | 21,382 | 30.0% | 60.0% | 100.0% | 4288ms |
| Vanilla (rg) | 13 | 28,710 | 20.0% | 40.0% | 66.7% | 570ms |
| Serena | 7 | 2,508 | 75.0% | 100.0% | 100.0% | 6023ms |

## Per-Category Summary

### ARCH (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 2,319 | 100.0% | 100.0% |
| AST-Index | 14,523 | 30.0% | 100.0% |
| Graphify | 17,265 | 30.0% | 100.0% |
| Vanilla (rg) | 19,613 | 20.0% | 66.7% |
| Serena | 2,828 | 100.0% | 100.0% |

### DEBUG (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,921 | 75.0% | 100.0% |
| AST-Index | 16,539 | 30.0% | 100.0% |
| Graphify | 21,382 | 30.0% | 100.0% |
| Vanilla (rg) | 28,710 | 20.0% | 66.7% |
| Serena | 2,508 | 75.0% | 100.0% |

### FEATURE (2 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,578 | 100.0% | 100.0% |
| AST-Index | 16,769 | 28.8% | 100.0% |
| Graphify | 15,304 | 10.0% | 41.7% |
| Vanilla (rg) | 24,559 | 10.0% | 41.7% |
| Serena | 3,491 | 100.0% | 83.3% |

### IMPACT (2 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 9,608 | 23.6% | 87.5% |
| AST-Index | 28,314 | 10.0% | 29.2% |
| Graphify | 27,937 | 5.0% | 16.7% |
| Vanilla (rg) | 24,304 | 10.0% | 25.0% |
| Serena | 8,116 | 100.0% | 29.2% |

### INFO (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,674 | 100.0% | 100.0% |
| AST-Index | 22,340 | 20.0% | 66.7% |
| Graphify | 18,938 | 20.0% | 66.7% |
| Vanilla (rg) | 25,622 | 20.0% | 66.7% |
| Serena | 2,794 | 100.0% | 66.7% |

### MIGRATION (2 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,171 | 83.3% | 83.3% |
| AST-Index | 6,476 | 26.6% | 66.7% |
| Graphify | 10,999 | 15.0% | 66.7% |
| Vanilla (rg) | 13,296 | 25.0% | 16.7% |
| Serena | 1,454 | 75.0% | 66.7% |

### REFACTOR (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 6,201 | 20.0% | 100.0% |
| AST-Index | 7,647 | 20.0% | 66.7% |
| Graphify | 7,507 | 20.0% | 66.7% |
| Vanilla (rg) | 6,458 | 0.0% | 0.0% |
| Serena | 113 | 100.0% | 33.3% |
