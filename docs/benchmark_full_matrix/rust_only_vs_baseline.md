# Rust-only benchmark vs saved Python baseline

Rust daemon (:7890) run 2026-07-18 after the perf work (startup model warm-up +
`keep_alive` VRAM pin). Python column is `bench/python_baseline.json` captured
the same day before Python removal — no live Python daemon required. Rerun with
`python bench/benchmark_rust_only.py`.

## Quality + latency

| Mode | py cov | rs cov | py prec | rs prec | py lat | rs lat |
|---|---:|---:|---:|---:|---:|---:|
| vanilla | 50.8% | 50.8% | 16.1% | 16.1% | 236ms | 122ms |
| rag_llm | 13.3% | 33.3% | 4.0% | 8.5% | 16612ms | 17901ms |
| smart | 62.5% | 67.5% | 9.2% | 9.7% | 564ms | 235ms |
| ast | 53.3% | 54.2% | 23.3% | 23.2% | 73ms | 34ms |
| graph | 50.8% | 56.7% | 18.3% | 19.1% | 244ms | 178ms |
| ask | 55.8% | 55.8% | 26.9% | 26.9% | 14241ms | 5938ms |

## Resources (python baseline → rust)

| Metric | python | rust |
|---|---:|---:|
| RSS (MB) | 153.9 | 34.2 |
| Peak RSS (MB) | 154.1 | 35.5 |
| CPU seconds (run) | 7.52 | 2.24 |
| Threads / FDs | 14 / 13 | 14 / 11 |
| Cold start to /health (ms) | 1300 | 40 |
| Install footprint (MB) | 232 (venv) | 30 (binary) |

Cold start dropped 1300ms → 40ms; the model is pre-warmed at boot so the first
real query is ~250ms instead of the former ~6.8s cold-load.
