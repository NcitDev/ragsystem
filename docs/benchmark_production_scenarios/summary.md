# Production Scenarios Benchmark

**Scenarios:** 10  
**Agents:** Smart Agent (production skill), AST-Index, Graphify, Naive Agent (context-pack only), Vanilla (rg)

## Overall Averages

| Agent | Avg Turns | Avg Tokens | Avg Precision | Avg Signal% | Avg Coverage | Avg Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 7.7 | 4,904 | 70.2% | 89.5% | 94.2% | 123ms |
| AST-Index | 13.9 | 16,372 | 23.1% | 64.9% | 72.5% | 112ms |
| Graphify | 11.0 | 16,942 | 13.0% | 52.0% | 48.3% | 4431ms |
| Naive Agent | 38.1 | 13,954 | 7.3% | 10.5% | 94.2% | 1482ms |
| Vanilla (rg) | 11.4 | 21,985 | 15.0% | 50.0% | 36.7% | 141ms |

## Per-Scenario Results

### Scenario 1: FEATURE — Add a sticker pack install event. What's the existing pattern?

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 4 | 1,933 | 100.0% | 100.0% | 100.0% | 61ms |
| AST-Index | 13 | 15,537 | 37.5% | 62.5% | 100.0% | 182ms |
| Graphify | 11 | 17,209 | 20.0% | 50.0% | 66.7% | 4808ms |
| Naive Agent | 42 | 15,195 | 7.3% | 7.3% | 100.0% | 643ms |
| Vanilla (rg) | 12 | 32,985 | 10.0% | 30.0% | 33.3% | 165ms |

### Scenario 2: MIGRATION — Find the database migration interface and show a concrete migration

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 3 | 1,142 | 100.0% | 100.0% | 100.0% | 31ms |
| AST-Index | 15 | 7,647 | 20.0% | 100.0% | 100.0% | 78ms |
| Graphify | 11 | 6,953 | 20.0% | 100.0% | 100.0% | 3783ms |
| Naive Agent | 29 | 13,466 | 7.1% | 7.1% | 100.0% | 604ms |
| Vanilla (rg) | 12 | 21,486 | 0.0% | 50.0% | 0.0% | 124ms |

### Scenario 3: ARCH — Show me the main classes in the sticker pack management system

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 4 | 2,319 | 100.0% | 100.0% | 100.0% | 54ms |
| AST-Index | 17 | 14,523 | 30.0% | 60.0% | 100.0% | 161ms |
| Graphify | 11 | 19,158 | 30.0% | 60.0% | 100.0% | 4427ms |
| Naive Agent | 43 | 14,919 | 7.1% | 7.1% | 100.0% | 754ms |
| Vanilla (rg) | 12 | 19,613 | 20.0% | 100.0% | 66.7% | 116ms |

### Scenario 4: FEATURE — I need to add a new backup feature. Show me how FullBackupExporter works

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 3 | 1,224 | 100.0% | 100.0% | 100.0% | 30ms |
| AST-Index | 15 | 18,001 | 20.0% | 70.0% | 100.0% | 106ms |
| Graphify | 11 | 10,611 | 10.0% | 10.0% | 50.0% | 4560ms |
| Naive Agent | 41 | 10,399 | 5.0% | 10.0% | 100.0% | 616ms |
| Vanilla (rg) | 12 | 19,025 | 10.0% | 50.0% | 50.0% | 137ms |

### Scenario 5: MIGRATION — Find deprecated job migration code that should be cleaned up

**Tool path:** `resolve_defs`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 4 | 1,200 | 66.7% | 100.0% | 66.7% | 37ms |
| AST-Index | 8 | 5,305 | 33.3% | 66.7% | 33.3% | 120ms |
| Graphify | 11 | 7,228 | 0.0% | 10.0% | 0.0% | 4191ms |
| Naive Agent | 40 | 10,617 | 5.1% | 5.1% | 66.7% | 721ms |
| Vanilla (rg) | 4 | 5,106 | 50.0% | 50.0% | 33.3% | 126ms |

### Scenario 6: IMPACT — If I change the Job base class, what code breaks? Show all subclasses

**Tool path:** `resolve_usages`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 14 | 14,245 | 23.1% | 61.5% | 75.0% | 38ms |
| AST-Index | 13 | 24,559 | 10.0% | 70.0% | 25.0% | 46ms |
| Graphify | 11 | 19,843 | 0.0% | 80.0% | 0.0% | 4283ms |
| Naive Agent | 40 | 17,484 | 7.7% | 7.7% | 75.0% | 8497ms |
| Vanilla (rg) | 12 | 18,563 | 20.0% | 100.0% | 50.0% | 76ms |

### Scenario 7: REFACTOR — Rename SignalDatabaseMigration interface. Find all implementors and callers

**Tool path:** `resolve_usages`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 18 | 10,179 | 17.6% | 100.0% | 100.0% | 33ms |
| AST-Index | 13 | 7,647 | 20.0% | 100.0% | 66.7% | 71ms |
| Graphify | 11 | 6,953 | 20.0% | 100.0% | 66.7% | 4514ms |
| Naive Agent | 37 | 13,017 | 8.3% | 27.8% | 100.0% | 882ms |
| Vanilla (rg) | 12 | 21,486 | 0.0% | 50.0% | 0.0% | 154ms |

### Scenario 8: IMPACT — Who calls Recipient? Show me the blast radius of changing the Recipient model

**Tool path:** `resolve_usages`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 16 | 13,203 | 20.0% | 33.3% | 100.0% | 34ms |
| AST-Index | 13 | 31,618 | 10.0% | 30.0% | 33.3% | 54ms |
| Graphify | 11 | 31,411 | 10.0% | 60.0% | 33.3% | 4665ms |
| Naive Agent | 40 | 20,273 | 7.7% | 15.4% | 100.0% | 604ms |
| Vanilla (rg) | 12 | 32,462 | 0.0% | 10.0% | 0.0% | 133ms |

### Scenario 9: INFO — How does the chat backup encryption and passphrase system work?

**Tool path:** `context_pack_then_resolve`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 5 | 1,674 | 100.0% | 100.0% | 100.0% | 447ms |
| AST-Index | 15 | 22,340 | 20.0% | 20.0% | 66.7% | 110ms |
| Graphify | 11 | 25,634 | 10.0% | 10.0% | 33.3% | 4477ms |
| Naive Agent | 34 | 11,480 | 9.1% | 9.1% | 100.0% | 946ms |
| Vanilla (rg) | 13 | 25,622 | 20.0% | 20.0% | 66.7% | 193ms |

### Scenario 10: DEBUG — Trace how push notifications are received and processed by the app

**Tool path:** `context_pack_then_resolve`

| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Smart Agent | 6 | 1,921 | 75.0% | 100.0% | 100.0% | 468ms |
| AST-Index | 17 | 16,539 | 30.0% | 70.0% | 100.0% | 190ms |
| Graphify | 11 | 24,421 | 10.0% | 40.0% | 33.3% | 4605ms |
| Naive Agent | 35 | 12,695 | 8.8% | 8.8% | 100.0% | 551ms |
| Vanilla (rg) | 13 | 23,502 | 20.0% | 40.0% | 66.7% | 189ms |

## Per-Category Summary

### ARCH (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 2,319 | 100.0% | 100.0% |
| AST-Index | 14,523 | 30.0% | 100.0% |
| Graphify | 19,158 | 30.0% | 100.0% |
| Naive Agent | 14,919 | 7.1% | 100.0% |
| Vanilla (rg) | 19,613 | 20.0% | 66.7% |

### DEBUG (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,921 | 75.0% | 100.0% |
| AST-Index | 16,539 | 30.0% | 100.0% |
| Graphify | 24,421 | 10.0% | 33.3% |
| Naive Agent | 12,695 | 8.8% | 100.0% |
| Vanilla (rg) | 23,502 | 20.0% | 66.7% |

### FEATURE (2 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,578 | 100.0% | 100.0% |
| AST-Index | 16,769 | 28.8% | 100.0% |
| Graphify | 13,910 | 15.0% | 58.3% |
| Naive Agent | 12,797 | 6.2% | 100.0% |
| Vanilla (rg) | 26,005 | 10.0% | 41.7% |

### IMPACT (2 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 13,724 | 21.6% | 87.5% |
| AST-Index | 28,088 | 10.0% | 29.2% |
| Graphify | 25,627 | 5.0% | 16.7% |
| Naive Agent | 18,878 | 7.7% | 87.5% |
| Vanilla (rg) | 25,512 | 10.0% | 25.0% |

### INFO (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,674 | 100.0% | 100.0% |
| AST-Index | 22,340 | 20.0% | 66.7% |
| Graphify | 25,634 | 10.0% | 33.3% |
| Naive Agent | 11,480 | 9.1% | 100.0% |
| Vanilla (rg) | 25,622 | 20.0% | 66.7% |

### MIGRATION (2 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 1,171 | 83.3% | 83.3% |
| AST-Index | 6,476 | 26.6% | 66.7% |
| Graphify | 7,090 | 10.0% | 50.0% |
| Naive Agent | 12,042 | 6.1% | 83.3% |
| Vanilla (rg) | 13,296 | 25.0% | 16.7% |

### REFACTOR (1 scenarios)

| Agent | Avg Tokens | Avg Precision | Avg Coverage |
|---|---:|---:|---:|
| Smart Agent | 10,179 | 17.6% | 100.0% |
| AST-Index | 7,647 | 20.0% | 66.7% |
| Graphify | 6,953 | 20.0% | 66.7% |
| Naive Agent | 13,017 | 8.3% | 100.0% |
| Vanilla (rg) | 21,486 | 0.0% | 0.0% |
