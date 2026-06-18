# Multi-Task Benchmark Summary

**Repo:** `/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android`
**Tasks:** 6
**Agents:** RAG+AST, AST-Index, Graphify, Vanilla (rg)

## Overall Effort (averaged across tasks)

| Agent | Avg Turns | Avg Tokens | Avg Precision | Avg Signal% | Avg Coverage |
|---|---:|---:|---:|---:|---:|
| RAG+AST | 5.7 | 6,709 | 91.7% | 100.0% | 100.0% |
| AST-Index | 51.2 | 114,549 | 19.9% | 63.4% | 100.0% |
| Graphify | 4.5 | 10,228 | 100.0% | 100.0% | 100.0% |
| Vanilla (rg) | 209.2 | 499,056 | 5.4% | 56.0% | 100.0% |

## Per-Task Breakdown

### Task 1: Refactor JobManager (Semantic)

| Agent | Tokens | Golden | Related | Noise | Precision | Signal% |
|---|---:|---:|---:|---:|---:|---:|
| RAG+AST | 16,669 | 4 | 4 | 0 | 50.0% | 100.0% |
| AST-Index | 146,296 | 4 | 10 | 15 | 13.8% | 48.3% |
| Graphify | 17,777 | 4 | 0 | 0 | 100.0% | 100.0% |
| Vanilla (rg) | 370,158 | 4 | 58 | 51 | 3.5% | 54.9% |

### Task 2: Database Migration Logic (Symbol)

| Agent | Tokens | Golden | Related | Noise | Precision | Signal% |
|---|---:|---:|---:|---:|---:|---:|
| RAG+AST | 1,300 | 3 | 0 | 0 | 100.0% | 100.0% |
| AST-Index | 80,801 | 3 | 67 | 11 | 3.7% | 86.4% |
| Graphify | 1,471 | 3 | 0 | 0 | 100.0% | 100.0% |
| Vanilla (rg) | 230,501 | 3 | 246 | 13 | 1.1% | 95.0% |

### Task 3: Push Notification Pipeline (Flow)

| Agent | Tokens | Golden | Related | Noise | Precision | Signal% |
|---|---:|---:|---:|---:|---:|---:|
| RAG+AST | 15,586 | 4 | 0 | 0 | 100.0% | 100.0% |
| AST-Index | 87,205 | 4 | 15 | 7 | 15.4% | 73.1% |
| Graphify | 11,984 | 4 | 0 | 0 | 100.0% | 100.0% |
| Vanilla (rg) | 89,635 | 4 | 17 | 7 | 14.3% | 75.0% |

### Task 4: Dependency Injection Wiring (Symbols)

| Agent | Tokens | Golden | Related | Noise | Precision | Signal% |
|---|---:|---:|---:|---:|---:|---:|
| RAG+AST | 2,039 | 3 | 0 | 0 | 100.0% | 100.0% |
| AST-Index | 174,332 | 3 | 2 | 41 | 6.5% | 10.9% |
| Graphify | 16,204 | 3 | 0 | 0 | 100.0% | 100.0% |
| Vanilla (rg) | 1,915,567 | 3 | 5 | 675 | 0.4% | 1.2% |

### Task 5: Blast Radius: Job Base Class (Graph)

| Agent | Tokens | Golden | Related | Noise | Precision | Signal% |
|---|---:|---:|---:|---:|---:|---:|
| RAG+AST | 2,473 | 4 | 0 | 0 | 100.0% | 100.0% |
| AST-Index | 186,427 | 4 | 66 | 11 | 4.9% | 86.4% |
| Graphify | 12,638 | 4 | 0 | 0 | 100.0% | 100.0% |
| Vanilla (rg) | 235,180 | 4 | 119 | 0 | 3.3% | 100.0% |

### Task 6: Deprecated Job Migrations (Text)

| Agent | Tokens | Golden | Related | Noise | Precision | Signal% |
|---|---:|---:|---:|---:|---:|---:|
| RAG+AST | 2,188 | 3 | 0 | 0 | 100.0% | 100.0% |
| AST-Index | 12,231 | 3 | 0 | 1 | 75.0% | 75.0% |
| Graphify | 1,293 | 3 | 0 | 0 | 100.0% | 100.0% |
| Vanilla (rg) | 153,298 | 3 | 0 | 27 | 10.0% | 10.0% |

## Token Efficiency Ranking (per task, lowest = best)

- Task 1: **RAG+AST** (16,669) > **Graphify** (17,777) > **AST-Index** (146,296) > **Vanilla (rg)** (370,158)
- Task 2: **RAG+AST** (1,300) > **Graphify** (1,471) > **AST-Index** (80,801) > **Vanilla (rg)** (230,501)
- Task 3: **Graphify** (11,984) > **RAG+AST** (15,586) > **AST-Index** (87,205) > **Vanilla (rg)** (89,635)
- Task 4: **RAG+AST** (2,039) > **Graphify** (16,204) > **AST-Index** (174,332) > **Vanilla (rg)** (1,915,567)
- Task 5: **RAG+AST** (2,473) > **Graphify** (12,638) > **AST-Index** (186,427) > **Vanilla (rg)** (235,180)
- Task 6: **Graphify** (1,293) > **RAG+AST** (2,188) > **AST-Index** (12,231) > **Vanilla (rg)** (153,298)

## Precision Ranking (per task, highest = best)

- Task 1: **Graphify** (100.0%) > **RAG+AST** (50.0%) > **AST-Index** (13.8%) > **Vanilla (rg)** (3.5%)
- Task 2: **RAG+AST** (100.0%) > **Graphify** (100.0%) > **AST-Index** (3.7%) > **Vanilla (rg)** (1.1%)
- Task 3: **RAG+AST** (100.0%) > **Graphify** (100.0%) > **AST-Index** (15.4%) > **Vanilla (rg)** (14.3%)
- Task 4: **RAG+AST** (100.0%) > **Graphify** (100.0%) > **AST-Index** (6.5%) > **Vanilla (rg)** (0.4%)
- Task 5: **RAG+AST** (100.0%) > **Graphify** (100.0%) > **AST-Index** (4.9%) > **Vanilla (rg)** (3.3%)
- Task 6: **RAG+AST** (100.0%) > **Graphify** (100.0%) > **AST-Index** (75.0%) > **Vanilla (rg)** (10.0%)
