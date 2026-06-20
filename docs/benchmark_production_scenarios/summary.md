# Production Scenarios Benchmark

**Scenarios:** 10  
**Agents:** Smart Agent (production skill), AST-Index, Graphify, Naive Agent (context-pack only), Vanilla (rg)

## Overall Averages

| Agent | Avg Turns | Avg Tokens | Avg Precision | Avg Signal% | Avg Coverage | Avg Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 6.5 | 3,279 | 73.7% | 93.3% | 94.2% | 211ms |
| AST-Index | 13.9 | 16,417 | 23.1% | 64.9% | 72.5% | 147ms |
| Graphify | 11.0 | 18,491 | 13.0% | 47.0% | 48.3% | 3835ms |
| Vanilla (rg) | 11.4 | 21,841 | 15.0% | 50.0% | 36.7% | 256ms |
| Serena | 4.5 | 3,436 | 92.5% | 100.0% | 65.8% | 11228ms |

## Per-Scenario Results

### Scenario 1: FEATURE — Add a sticker pack install event. What's the existing pattern?

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 4 | 1,933 | 100.0% | 100.0% | 100.0% | 58ms |
| AST-Index | 13 | 15,537 | 37.5% | 62.5% | 100.0% | 359ms |
| Graphify | 11 | 9,729 | 10.0% | 30.0% | 33.3% | 3592ms |
| Vanilla (rg) | 12 | 32,985 | 10.0% | 30.0% | 33.3% | 425ms |
| Serena | 4 | 1,726 | 100.0% | 100.0% | 66.7% | 32026ms |

### Scenario 2: MIGRATION — Find the database migration interface and show a concrete migration

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 3 | 1,142 | 100.0% | 100.0% | 100.0% | 53ms |
| AST-Index | 15 | 7,647 | 20.0% | 100.0% | 100.0% | 78ms |
| Graphify | 11 | 7,043 | 20.0% | 100.0% | 100.0% | 4097ms |
| Vanilla (rg) | 12 | 21,486 | 0.0% | 50.0% | 0.0% | 205ms |
| Serena | 4 | 2,652 | 100.0% | 100.0% | 100.0% | 3947ms |

### Scenario 3: ARCH — Show me the main classes in the sticker pack management system

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 4 | 2,319 | 100.0% | 100.0% | 100.0% | 78ms |
| AST-Index | 17 | 14,523 | 30.0% | 60.0% | 100.0% | 151ms |
| Graphify | 11 | 21,188 | 30.0% | 30.0% | 100.0% | 3633ms |
| Vanilla (rg) | 12 | 19,613 | 20.0% | 100.0% | 66.7% | 160ms |
| Serena | 6 | 2,828 | 100.0% | 100.0% | 100.0% | 5839ms |

### Scenario 4: FEATURE — I need to add a new backup feature. Show me how FullBackupExporter works

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 3 | 1,224 | 100.0% | 100.0% | 100.0% | 57ms |
| AST-Index | 15 | 18,001 | 20.0% | 70.0% | 100.0% | 136ms |
| Graphify | 11 | 25,026 | 10.0% | 20.0% | 50.0% | 3849ms |
| Vanilla (rg) | 12 | 19,025 | 10.0% | 50.0% | 50.0% | 175ms |
| Serena | 4 | 5,256 | 100.0% | 100.0% | 100.0% | 3933ms |

### Scenario 5: MIGRATION — Find deprecated job migration code that should be cleaned up

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 4 | 1,200 | 66.7% | 100.0% | 66.7% | 46ms |
| AST-Index | 8 | 5,305 | 33.3% | 66.7% | 33.3% | 136ms |
| Graphify | 11 | 19,825 | 10.0% | 20.0% | 33.3% | 3326ms |
| Vanilla (rg) | 4 | 5,106 | 50.0% | 50.0% | 33.3% | 144ms |
| Serena | 4 | 256 | 50.0% | 100.0% | 33.3% | 3950ms |

### Scenario 6: IMPACT — If I change the Job base class, what code breaks? Show all subclasses

**Tool path:** `resolve_usages`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 13 | 5,655 | 25.0% | 100.0% | 75.0% | 58ms |
| AST-Index | 13 | 24,559 | 10.0% | 70.0% | 25.0% | 52ms |
| Graphify | 11 | 29,498 | 0.0% | 60.0% | 0.0% | 3522ms |
| Vanilla (rg) | 12 | 18,563 | 20.0% | 100.0% | 50.0% | 265ms |
| Serena | 3 | 5,000 | 100.0% | 100.0% | 25.0% | 4060ms |

### Scenario 7: REFACTOR — Rename SignalDatabaseMigration interface. Find all implementors and callers

**Tool path:** `resolve_usages`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 7 | 1,641 | 50.0% | 100.0% | 100.0% | 43ms |
| AST-Index | 13 | 7,647 | 20.0% | 100.0% | 66.7% | 130ms |
| Graphify | 11 | 7,043 | 20.0% | 100.0% | 66.7% | 3280ms |
| Vanilla (rg) | 12 | 21,486 | 0.0% | 50.0% | 0.0% | 245ms |
| Serena | 4 | 113 | 100.0% | 100.0% | 33.3% | 7501ms |

### Scenario 8: IMPACT — Who calls Recipient? Show me the blast radius of changing the Recipient model

**Tool path:** `resolve_usages`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 16 | 14,081 | 20.0% | 33.3% | 100.0% | 52ms |
| AST-Index | 13 | 32,070 | 10.0% | 30.0% | 33.3% | 53ms |
| Graphify | 11 | 30,168 | 0.0% | 40.0% | 0.0% | 3983ms |
| Vanilla (rg) | 12 | 27,695 | 0.0% | 10.0% | 0.0% | 188ms |
| Serena | 5 | 11,232 | 100.0% | 100.0% | 33.3% | 41202ms |

### Scenario 9: INFO — How does the chat backup encryption and passphrase system work?

**Tool path:** `context_pack_then_resolve`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 5 | 1,674 | 100.0% | 100.0% | 100.0% | 970ms |
| AST-Index | 15 | 22,340 | 20.0% | 20.0% | 66.7% | 126ms |
| Graphify | 11 | 15,906 | 10.0% | 10.0% | 33.3% | 5203ms |
| Vanilla (rg) | 13 | 25,622 | 20.0% | 20.0% | 66.7% | 466ms |
| Serena | 4 | 2,794 | 100.0% | 100.0% | 66.7% | 3974ms |

### Scenario 10: DEBUG — Trace how push notifications are received and processed by the app

**Tool path:** `context_pack_then_resolve`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 6 | 1,921 | 75.0% | 100.0% | 100.0% | 697ms |
| AST-Index | 17 | 16,539 | 30.0% | 70.0% | 100.0% | 252ms |
| Graphify | 11 | 19,480 | 20.0% | 60.0% | 66.7% | 3865ms |
| Vanilla (rg) | 13 | 26,831 | 20.0% | 40.0% | 66.7% | 289ms |
| Serena | 7 | 2,508 | 75.0% | 100.0% | 100.0% | 5850ms |

## Per-Category Summary

### ARCH (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 2,319 | 100.0% | 100.0% |
| AST-Index | 14,523 | 30.0% | 100.0% |
| Graphify | 21,188 | 30.0% | 100.0% |
| Vanilla (rg) | 19,613 | 20.0% | 66.7% |
| Serena | 2,828 | 100.0% | 100.0% |

### DEBUG (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,921 | 75.0% | 100.0% |
| AST-Index | 16,539 | 30.0% | 100.0% |
| Graphify | 19,480 | 20.0% | 66.7% |
| Vanilla (rg) | 26,831 | 20.0% | 66.7% |
| Serena | 2,508 | 75.0% | 100.0% |

### FEATURE (2 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,578 | 100.0% | 100.0% |
| AST-Index | 16,769 | 28.8% | 100.0% |
| Graphify | 17,378 | 10.0% | 41.7% |
| Vanilla (rg) | 26,005 | 10.0% | 41.7% |
| Serena | 3,491 | 100.0% | 83.3% |

### IMPACT (2 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 9,868 | 22.5% | 87.5% |
| AST-Index | 28,314 | 10.0% | 29.2% |
| Graphify | 29,833 | 0.0% | 0.0% |
| Vanilla (rg) | 23,129 | 10.0% | 25.0% |
| Serena | 8,116 | 100.0% | 29.2% |

### INFO (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,674 | 100.0% | 100.0% |
| AST-Index | 22,340 | 20.0% | 66.7% |
| Graphify | 15,906 | 10.0% | 33.3% |
| Vanilla (rg) | 25,622 | 20.0% | 66.7% |
| Serena | 2,794 | 100.0% | 66.7% |

### MIGRATION (2 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,171 | 83.3% | 83.3% |
| AST-Index | 6,476 | 26.6% | 66.7% |
| Graphify | 13,434 | 15.0% | 66.7% |
| Vanilla (rg) | 13,296 | 25.0% | 16.7% |
| Serena | 1,454 | 75.0% | 66.7% |

### REFACTOR (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,641 | 50.0% | 100.0% |
| AST-Index | 7,647 | 20.0% | 66.7% |
| Graphify | 7,043 | 20.0% | 66.7% |
| Vanilla (rg) | 21,486 | 0.0% | 0.0% |
| Serena | 113 | 100.0% | 33.3% |
