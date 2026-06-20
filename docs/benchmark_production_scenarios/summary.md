# Production Scenarios Benchmark

**Scenarios:** 10  
**Agents:** Smart Agent (production skill), AST-Index, Graphify, Naive Agent (context-pack only), Vanilla (rg)

## Overall Averages

| Agent | Avg Turns | Avg Tokens | Avg Precision | Avg Signal% | Avg Coverage | Avg Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 7.4 | 3,501 | 70.7% | 93.3% | 94.2% | 242ms |
| AST-Index | 13.9 | 16,417 | 23.1% | 64.9% | 72.5% | 127ms |
| Graphify | 11.0 | 16,549 | 16.0% | 47.0% | 58.3% | 4260ms |
| Vanilla (rg) | 11.4 | 20,484 | 15.0% | 48.0% | 36.7% | 287ms |
| Serena | 4.5 | 3,436 | 92.5% | 100.0% | 65.8% | 11185ms |

## Per-Scenario Results

### Scenario 1: FEATURE — Add a sticker pack install event. What's the existing pattern?

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 4 | 1,933 | 100.0% | 100.0% | 100.0% | 112ms |
| AST-Index | 13 | 15,537 | 37.5% | 62.5% | 100.0% | 185ms |
| Graphify | 11 | 19,186 | 20.0% | 20.0% | 66.7% | 4463ms |
| Vanilla (rg) | 12 | 30,734 | 10.0% | 20.0% | 33.3% | 161ms |
| Serena | 4 | 1,726 | 100.0% | 100.0% | 66.7% | 28439ms |

### Scenario 2: MIGRATION — Find the database migration interface and show a concrete migration

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 3 | 1,142 | 100.0% | 100.0% | 100.0% | 84ms |
| AST-Index | 15 | 7,647 | 20.0% | 100.0% | 100.0% | 84ms |
| Graphify | 11 | 7,213 | 20.0% | 100.0% | 100.0% | 4639ms |
| Vanilla (rg) | 12 | 21,486 | 0.0% | 50.0% | 0.0% | 211ms |
| Serena | 4 | 2,652 | 100.0% | 100.0% | 100.0% | 4039ms |

### Scenario 3: ARCH — Show me the main classes in the sticker pack management system

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 4 | 2,319 | 100.0% | 100.0% | 100.0% | 82ms |
| AST-Index | 17 | 14,523 | 30.0% | 60.0% | 100.0% | 168ms |
| Graphify | 11 | 14,999 | 30.0% | 30.0% | 100.0% | 3916ms |
| Vanilla (rg) | 12 | 19,613 | 20.0% | 100.0% | 66.7% | 520ms |
| Serena | 6 | 2,828 | 100.0% | 100.0% | 100.0% | 6122ms |

### Scenario 4: FEATURE — I need to add a new backup feature. Show me how FullBackupExporter works

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 3 | 1,224 | 100.0% | 100.0% | 100.0% | 62ms |
| AST-Index | 15 | 18,001 | 20.0% | 70.0% | 100.0% | 153ms |
| Graphify | 11 | 24,354 | 10.0% | 20.0% | 50.0% | 4079ms |
| Vanilla (rg) | 12 | 19,025 | 10.0% | 50.0% | 50.0% | 202ms |
| Serena | 4 | 5,256 | 100.0% | 100.0% | 100.0% | 3903ms |

### Scenario 5: MIGRATION — Find deprecated job migration code that should be cleaned up

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 4 | 1,200 | 66.7% | 100.0% | 66.7% | 73ms |
| AST-Index | 8 | 5,305 | 33.3% | 66.7% | 33.3% | 116ms |
| Graphify | 11 | 14,675 | 10.0% | 20.0% | 33.3% | 4103ms |
| Vanilla (rg) | 4 | 5,106 | 50.0% | 50.0% | 33.3% | 155ms |
| Serena | 4 | 256 | 50.0% | 100.0% | 33.3% | 3918ms |

### Scenario 6: IMPACT — If I change the Job base class, what code breaks? Show all subclasses

**Tool path:** `resolve_usages`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 13 | 3,313 | 25.0% | 100.0% | 75.0% | 66ms |
| AST-Index | 13 | 24,559 | 10.0% | 70.0% | 25.0% | 49ms |
| Graphify | 11 | 13,395 | 0.0% | 100.0% | 0.0% | 4237ms |
| Vanilla (rg) | 12 | 18,563 | 20.0% | 100.0% | 50.0% | 394ms |
| Serena | 3 | 5,000 | 100.0% | 100.0% | 25.0% | 4182ms |

### Scenario 7: REFACTOR — Rename SignalDatabaseMigration interface. Find all implementors and callers

**Tool path:** `resolve_usages`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 16 | 6,201 | 20.0% | 100.0% | 100.0% | 48ms |
| AST-Index | 13 | 7,647 | 20.0% | 100.0% | 66.7% | 93ms |
| Graphify | 11 | 7,213 | 20.0% | 100.0% | 66.7% | 3754ms |
| Vanilla (rg) | 12 | 21,486 | 0.0% | 50.0% | 0.0% | 172ms |
| Serena | 4 | 113 | 100.0% | 100.0% | 33.3% | 7766ms |

### Scenario 8: IMPACT — Who calls Recipient? Show me the blast radius of changing the Recipient model

**Tool path:** `resolve_usages`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 16 | 14,081 | 20.0% | 33.3% | 100.0% | 58ms |
| AST-Index | 13 | 32,070 | 10.0% | 30.0% | 33.3% | 58ms |
| Graphify | 11 | 17,711 | 0.0% | 0.0% | 0.0% | 4205ms |
| Vanilla (rg) | 12 | 19,698 | 0.0% | 0.0% | 0.0% | 490ms |
| Serena | 5 | 11,232 | 100.0% | 100.0% | 33.3% | 41478ms |

### Scenario 9: INFO — How does the chat backup encryption and passphrase system work?

**Tool path:** `context_pack_then_resolve`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 5 | 1,674 | 100.0% | 100.0% | 100.0% | 991ms |
| AST-Index | 15 | 22,340 | 20.0% | 20.0% | 66.7% | 97ms |
| Graphify | 11 | 22,937 | 20.0% | 30.0% | 66.7% | 4983ms |
| Vanilla (rg) | 13 | 25,622 | 20.0% | 20.0% | 66.7% | 255ms |
| Serena | 4 | 2,794 | 100.0% | 100.0% | 66.7% | 4654ms |

### Scenario 10: DEBUG — Trace how push notifications are received and processed by the app

**Tool path:** `context_pack_then_resolve`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 6 | 1,921 | 75.0% | 100.0% | 100.0% | 840ms |
| AST-Index | 17 | 16,539 | 30.0% | 70.0% | 100.0% | 265ms |
| Graphify | 11 | 23,806 | 30.0% | 50.0% | 100.0% | 4217ms |
| Vanilla (rg) | 13 | 23,502 | 20.0% | 40.0% | 66.7% | 314ms |
| Serena | 7 | 2,508 | 75.0% | 100.0% | 100.0% | 7351ms |

## Per-Category Summary

### ARCH (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 2,319 | 100.0% | 100.0% |
| AST-Index | 14,523 | 30.0% | 100.0% |
| Graphify | 14,999 | 30.0% | 100.0% |
| Vanilla (rg) | 19,613 | 20.0% | 66.7% |
| Serena | 2,828 | 100.0% | 100.0% |

### DEBUG (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,921 | 75.0% | 100.0% |
| AST-Index | 16,539 | 30.0% | 100.0% |
| Graphify | 23,806 | 30.0% | 100.0% |
| Vanilla (rg) | 23,502 | 20.0% | 66.7% |
| Serena | 2,508 | 75.0% | 100.0% |

### FEATURE (2 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,578 | 100.0% | 100.0% |
| AST-Index | 16,769 | 28.8% | 100.0% |
| Graphify | 21,770 | 15.0% | 58.3% |
| Vanilla (rg) | 24,880 | 10.0% | 41.7% |
| Serena | 3,491 | 100.0% | 83.3% |

### IMPACT (2 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 8,697 | 22.5% | 87.5% |
| AST-Index | 28,314 | 10.0% | 29.2% |
| Graphify | 15,553 | 0.0% | 0.0% |
| Vanilla (rg) | 19,130 | 10.0% | 25.0% |
| Serena | 8,116 | 100.0% | 29.2% |

### INFO (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,674 | 100.0% | 100.0% |
| AST-Index | 22,340 | 20.0% | 66.7% |
| Graphify | 22,937 | 20.0% | 66.7% |
| Vanilla (rg) | 25,622 | 20.0% | 66.7% |
| Serena | 2,794 | 100.0% | 66.7% |

### MIGRATION (2 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,171 | 83.3% | 83.3% |
| AST-Index | 6,476 | 26.6% | 66.7% |
| Graphify | 10,944 | 15.0% | 66.7% |
| Vanilla (rg) | 13,296 | 25.0% | 16.7% |
| Serena | 1,454 | 75.0% | 66.7% |

### REFACTOR (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 6,201 | 20.0% | 100.0% |
| AST-Index | 7,647 | 20.0% | 66.7% |
| Graphify | 7,213 | 20.0% | 66.7% |
| Vanilla (rg) | 21,486 | 0.0% | 0.0% |
| Serena | 113 | 100.0% | 33.3% |
