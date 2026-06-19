# Production Scenarios Benchmark

**Scenarios:** 10  
**Agents:** Smart Agent (production skill), AST-Index, Graphify, Naive Agent (context-pack only), Vanilla (rg)

## Overall Averages

| Agent | Avg Turns | Avg Tokens | Avg Precision | Avg Signal% | Avg Coverage | Avg Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 6.7 | 4,155 | 73.3% | 91.9% | 94.2% | 152ms |
| AST-Index | 13.9 | 16,793 | 23.1% | 64.9% | 72.5% | 133ms |
| Graphify | 11.0 | 18,775 | 15.0% | 48.0% | 54.2% | 3703ms |
| Vanilla (rg) | 11.4 | 21,597 | 15.0% | 48.0% | 36.7% | 216ms |

## Per-Scenario Results

### Scenario 1: FEATURE — Add a sticker pack install event. What's the existing pattern?

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 4 | 1,933 | 100.0% | 100.0% | 100.0% | 58ms |
| AST-Index | 13 | 15,537 | 37.5% | 62.5% | 100.0% | 290ms |
| Graphify | 11 | 19,839 | 20.0% | 20.0% | 66.7% | 4114ms |
| Vanilla (rg) | 12 | 30,734 | 10.0% | 20.0% | 33.3% | 127ms |

### Scenario 2: MIGRATION — Find the database migration interface and show a concrete migration

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 3 | 1,142 | 100.0% | 100.0% | 100.0% | 54ms |
| AST-Index | 15 | 7,647 | 20.0% | 100.0% | 100.0% | 82ms |
| Graphify | 11 | 6,674 | 20.0% | 100.0% | 100.0% | 3064ms |
| Vanilla (rg) | 12 | 21,486 | 0.0% | 50.0% | 0.0% | 116ms |

### Scenario 3: ARCH — Show me the main classes in the sticker pack management system

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 4 | 2,319 | 100.0% | 100.0% | 100.0% | 69ms |
| AST-Index | 17 | 14,523 | 30.0% | 60.0% | 100.0% | 141ms |
| Graphify | 11 | 14,942 | 30.0% | 40.0% | 100.0% | 3591ms |
| Vanilla (rg) | 12 | 19,613 | 20.0% | 100.0% | 66.7% | 115ms |

### Scenario 4: FEATURE — I need to add a new backup feature. Show me how FullBackupExporter works

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 3 | 1,224 | 100.0% | 100.0% | 100.0% | 45ms |
| AST-Index | 15 | 18,001 | 20.0% | 70.0% | 100.0% | 206ms |
| Graphify | 11 | 20,093 | 10.0% | 10.0% | 50.0% | 3802ms |
| Vanilla (rg) | 12 | 19,025 | 10.0% | 50.0% | 50.0% | 254ms |

### Scenario 5: MIGRATION — Find deprecated job migration code that should be cleaned up

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 4 | 1,200 | 66.7% | 100.0% | 66.7% | 42ms |
| AST-Index | 8 | 5,305 | 33.3% | 66.7% | 33.3% | 112ms |
| Graphify | 11 | 16,445 | 0.0% | 10.0% | 0.0% | 3729ms |
| Vanilla (rg) | 4 | 5,106 | 50.0% | 50.0% | 33.3% | 213ms |

### Scenario 6: IMPACT — If I change the Job base class, what code breaks? Show all subclasses

**Tool path:** `resolve_usages`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 15 | 12,232 | 21.4% | 85.7% | 75.0% | 47ms |
| AST-Index | 13 | 24,559 | 10.0% | 70.0% | 25.0% | 49ms |
| Graphify | 11 | 30,350 | 10.0% | 90.0% | 25.0% | 3827ms |
| Vanilla (rg) | 12 | 18,563 | 20.0% | 100.0% | 50.0% | 244ms |

### Scenario 7: REFACTOR — Rename SignalDatabaseMigration interface. Find all implementors and callers

**Tool path:** `resolve_usages`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 7 | 3,827 | 50.0% | 100.0% | 100.0% | 51ms |
| AST-Index | 13 | 7,647 | 20.0% | 100.0% | 66.7% | 83ms |
| Graphify | 11 | 6,674 | 20.0% | 100.0% | 66.7% | 3638ms |
| Vanilla (rg) | 12 | 21,486 | 0.0% | 50.0% | 0.0% | 443ms |

### Scenario 8: IMPACT — Who calls Recipient? Show me the blast radius of changing the Recipient model

**Tool path:** `resolve_usages`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 16 | 14,081 | 20.0% | 33.3% | 100.0% | 54ms |
| AST-Index | 13 | 35,828 | 10.0% | 30.0% | 33.3% | 51ms |
| Graphify | 11 | 27,897 | 10.0% | 70.0% | 33.3% | 3860ms |
| Vanilla (rg) | 12 | 27,500 | 0.0% | 0.0% | 0.0% | 302ms |

### Scenario 9: INFO — How does the chat backup encryption and passphrase system work?

**Tool path:** `context_pack_then_resolve`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 5 | 1,674 | 100.0% | 100.0% | 100.0% | 610ms |
| AST-Index | 15 | 22,340 | 20.0% | 20.0% | 66.7% | 129ms |
| Graphify | 11 | 24,609 | 20.0% | 20.0% | 66.7% | 4046ms |
| Vanilla (rg) | 13 | 25,622 | 20.0% | 20.0% | 66.7% | 175ms |

### Scenario 10: DEBUG — Trace how push notifications are received and processed by the app

**Tool path:** `context_pack_then_resolve`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 6 | 1,921 | 75.0% | 100.0% | 100.0% | 488ms |
| AST-Index | 17 | 16,539 | 30.0% | 70.0% | 100.0% | 192ms |
| Graphify | 11 | 20,226 | 10.0% | 20.0% | 33.3% | 3358ms |
| Vanilla (rg) | 13 | 26,831 | 20.0% | 40.0% | 66.7% | 172ms |

## Per-Category Summary

### ARCH (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 2,319 | 100.0% | 100.0% |
| AST-Index | 14,523 | 30.0% | 100.0% |
| Graphify | 14,942 | 30.0% | 100.0% |
| Vanilla (rg) | 19,613 | 20.0% | 66.7% |

### DEBUG (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,921 | 75.0% | 100.0% |
| AST-Index | 16,539 | 30.0% | 100.0% |
| Graphify | 20,226 | 10.0% | 33.3% |
| Vanilla (rg) | 26,831 | 20.0% | 66.7% |

### FEATURE (2 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,578 | 100.0% | 100.0% |
| AST-Index | 16,769 | 28.8% | 100.0% |
| Graphify | 19,966 | 15.0% | 58.3% |
| Vanilla (rg) | 24,880 | 10.0% | 41.7% |

### IMPACT (2 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 13,156 | 20.7% | 87.5% |
| AST-Index | 30,194 | 10.0% | 29.2% |
| Graphify | 29,124 | 10.0% | 29.2% |
| Vanilla (rg) | 23,032 | 10.0% | 25.0% |

### INFO (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,674 | 100.0% | 100.0% |
| AST-Index | 22,340 | 20.0% | 66.7% |
| Graphify | 24,609 | 20.0% | 66.7% |
| Vanilla (rg) | 25,622 | 20.0% | 66.7% |

### MIGRATION (2 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,171 | 83.3% | 83.3% |
| AST-Index | 6,476 | 26.6% | 66.7% |
| Graphify | 11,560 | 10.0% | 50.0% |
| Vanilla (rg) | 13,296 | 25.0% | 16.7% |

### REFACTOR (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 3,827 | 50.0% | 100.0% |
| AST-Index | 7,647 | 20.0% | 66.7% |
| Graphify | 6,674 | 20.0% | 66.7% |
| Vanilla (rg) | 21,486 | 0.0% | 0.0% |
