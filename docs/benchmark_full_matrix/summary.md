# Full retrieval-mode matrix — Python vs Rust daemon

Same `~/.rag` state, same Docker-hosted Qdrant, identical requests.

## Mode averages

| Mode | py cov | rs cov | py prec | rs prec | py lat | rs lat | py p95 | rs p95 | errs (py/rs) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| vanilla | 50.8% | 50.8% | 16.1% | 16.1% | 236ms | 123ms | 354ms | 335ms | 0/0 |
| rag_llm | 13.3% | 33.3% | 4.0% | 8.5% | 16612ms | 16082ms | 19293ms | 17912ms | 0/0 |
| smart | 62.5% | 67.5% | 9.2% | 9.7% | 564ms | 211ms | 678ms | 331ms | 0/0 |
| ast | 53.3% | 54.2% | 23.3% | 23.2% | 73ms | 26ms | 127ms | 83ms | 0/0 |
| graph | 50.8% | 56.7% | 18.3% | 19.1% | 244ms | 159ms | 345ms | 211ms | 0/0 |
| ask | 55.8% | 55.8% | 26.9% | 26.9% | 14241ms | 7013ms | 16212ms | 17146ms | 0/0 |

## Resource usage (whole matrix run)

| Metric | python | rust |
|---|---:|---:|
| RSS after run (MB) | 153.9 | 30.6 |
| Peak RSS (MB) | 154.1 | 30.6 |
| Threads | 14 | 14 |
| Open FDs | 13 | 15 |
| CPU seconds (run total) | 7.52 | 2.15 |
| Disk read (MB) | 163.3 | 15.1 |
| Disk write (MB) | 33.9 | 35.8 |
| Install footprint (MB) | 232.0 (venv) | 30.0 (binary) |
| Cold start to /health (ms) | 1300 | 22 |