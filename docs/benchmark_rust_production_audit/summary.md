# Audited Rust benchmark — previous Rust and Python comparison

Date: 2026-07-18

## Outcome

The production-hardened Rust daemon preserved the saved Rust retrieval quality
on all six comparable modes. Against the saved Python baseline it matched or
improved coverage on every mode and matched or improved precision on five of
six (AST differed by 0.1 percentage point).

The older saved Rust run reported much lower smart/AST/graph latency. A
contemporaneous control run of the installed previous Rust binary on the exact
same host and state reproduced the audited binary's current timings to within
2%. The historical latency gap is therefore a run-condition/cache difference,
not a regression attributable to the production-audit changes.

The first one-shot `/ask` run contained one stochastic
`INSUFFICIENT_CONTEXT` response. A dedicated 30-answer run restored the saved
55.8% coverage and 26.9% precision with zero errors or refusals. Model-backed
latency varied widely, so the stability-run distribution is the meaningful
number for `/ask`.

## Comparable quality

Coverage and precision are macro-averages across the same ten Signal-Android
scenarios and golden file sets. The `/ask` audited column uses the dedicated
three-repeat stability run; other audited modes use the exact historical
repeat policy.

| Mode | Coverage Python | Coverage saved Rust | Coverage audited Rust | Precision Python | Precision saved Rust | Precision audited Rust |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| vanilla | 50.8% | 50.8% | 50.8% | 16.1% | 16.1% | 16.1% |
| rag_llm | 13.3% | 33.3% | 33.3% | 4.0% | 8.5% | 8.5% |
| smart | 62.5% | 67.5% | 67.5% | 9.2% | 9.7% | 9.7% |
| ast | 53.3% | 54.2% | 54.2% | 23.3% | 23.2% | 23.2% |
| graph | 50.8% | 56.7% | 56.7% | 18.3% | 19.1% | 19.1% |
| ask (30 answers) | 55.8% | 55.8% | 55.8% | 26.9% | 26.9% | 26.9% |

This metric measures whether returned file citations intersect a small golden
set. It is not an end-to-end answer-correctness score and does not measure
recall outside those annotated files.

## Latency

The exact run used two repetitions for deterministic/fast modes and one for
`rag_llm` and `/ask`, matching the saved matrix. `/ask` below uses its stronger
30-answer stability run. Negative deltas are faster.

| Mode | Python mean | Saved Rust mean | Audited Rust mean | Audited vs Python | Audited vs saved Rust |
| --- | ---: | ---: | ---: | ---: | ---: |
| vanilla | 235.5 ms | 122.7 ms | 114.6 ms | -51.3% | -6.6% |
| rag_llm | 16,612.3 ms | 16,081.5 ms | 17,509.1 ms | +5.4% | +8.9% |
| smart | 563.8 ms | 211.1 ms | 479.9 ms | -14.9% | +127.3% |
| ast | 73.3 ms | 26.1 ms | 83.6 ms | +14.1% | +220.3% |
| graph | 244.4 ms | 158.8 ms | 259.0 ms | +6.0% | +63.1% |
| ask (30 answers) | 14,241.2 ms | 7,012.6 ms | 9,164.1 ms | -35.7% | +30.7% |

The LLM-planner line is one run per scenario and should not be interpreted as
a statistically significant 5–9% regression. Ollama generation dominated its
wall time.

### Controlled previous-binary A/B

The installed previous Rust artifact was run immediately afterward against
the same isolated local databases, repository checkout, Qdrant collection,
Ollama instance, benchmark driver, and host. Quality was identical for every
mode in this control.

| Mode | Previous binary now | Audited binary now | Audited delta |
| --- | ---: | ---: | ---: |
| vanilla | 127.0 ms | 114.6 ms | -9.8% |
| smart | 473.8 ms | 479.9 ms | +1.3% |
| ast | 83.8 ms | 83.6 ms | -0.2% |
| graph | 264.0 ms | 259.0 ms | -1.9% |

This sequential control was not randomized, but it is sufficient to show that
the saved 211/26/159 ms smart/AST/graph timings were not reproducible by either
binary under current conditions. The production-audit code did not create the
apparent gap.

### `/ask` stability

Thirty audited answers (three per scenario) produced:

- mean 9,164.1 ms, p50 6,507.1 ms, p95 18,327.8 ms;
- range 2,820.3–18,404.2 ms;
- 55.8% macro coverage and 26.9% macro precision;
- zero request errors and zero `INSUFFICIENT_CONTEXT` responses.

The exact-comparison run's single refusal reduced that one pass to 49.2%
coverage. The repeated run demonstrates stochastic generation variance, not a
deterministic retrieval-quality loss. Capacity planning should use the p95,
not the fastest or single-run mean.

## Process resources

These figures cover only each daemon process. Qdrant and Ollama were shared
external services and their CPU/GPU/RAM are excluded, matching the saved
methodology.

| Metric | Saved Python | Saved Rust | Audited Rust |
| --- | ---: | ---: | ---: |
| RSS after exact matrix | 153.9 MiB | 30.6 MiB | 23.1 MiB |
| Peak RSS | 154.1 MiB | 30.6 MiB | 23.1 MiB |
| Daemon CPU seconds during matrix | 7.52 s | 2.15 s | 2.02 s |
| Threads | 14 | 14 | 14 |
| Open file descriptors | 13 | 15 | 11 |
| Install artifact | 232.0 MiB venv | 30.0 MiB binary | 30.5 MiB binary |
| Process start to `/health` | 1,300 ms | 22 ms | 27 ms |

The 27 ms startup measurement is a single warm-host process-start sample with
Qdrant and Ollama already running; its five-millisecond difference from the
saved Rust value is noise, not a cold-machine benchmark. The audited binary is
32,012,944 bytes.

## Methodology and provenance

- Host: Linux 7.0 x86-64, 12 logical CPUs, 30 GiB system RAM; shared NVIDIA GPU
  reported 12,288 MiB total.
- Corpus: Signal-Android commit
  `d6871f8dc2d12a5b74ac0501bcf73ccec38064fd`, clean tracked worktree.
- Index: Qdrant 1.18.2, green `repo_signal` collection, 46,121 indexed points.
- Models: existing `qwen3-embedding:latest` 4096-dimensional index and
  `qwen3:8b` generation/planning. The older embedding tag was retained only so
  this run addressed the exact same index; new installations use the corrected
  `qwen3-embedding:4b`/2560 default.
- Audited daemon: source head
  `e2b730ad15150a1196d82d106f6d1625aa893412`; binary SHA-256
  `8cf60a3e237fa3781946b51de442dd546fa24cbe28c0c15180063ca160440d1d`.
- Installed previous binary control: SHA-256
  `537d53c5692d70dd16c97811db00d3278032870c1c7d4ddec071e60909d80d3f`.
  The saved report did not record its artifact hash, so the installed artifact
  cannot be cryptographically proven identical; the control is used only to
  isolate current run conditions.
- Saved Python baseline SHA-256:
  `f70e0e6f59bbd287588ad8e75699125643b3eff7e1603f775a151c2f9f2ab3bc`.
- Saved full-matrix SHA-256:
  `7aa4f2fc7ad967f8eb9a256d6462b77610639a23d2e6a126d4a8e25392b52c8d`.
- The audited daemon used a temporary copied `RAG_HOME` and port 17890. Its
  SQLite files and logs were isolated; `quick_check` passed before the run.
  Qdrant was read-only for these search scenarios. No model was pulled, no
  collection was created/reset/written, and the original daemon/checkouts were
  not stopped or modified. The temporary state, including its token copy, was
  removed after shutdown.
- An exploratory high-rate repeat hit the expected protected-route limit of
  120 requests/minute and returned 429s. Those contaminated samples are not in
  any table or committed result artifact.

Exact comparison command shape:

```text
python3 bench/benchmark_rust_only.py \
  --repeats 2 \
  --rust-url http://127.0.0.1:17890 \
  --repo signal \
  --token-file <isolated-home>/token \
  --rust-binary target/release/rag-rs \
  --corpus-revision d6871f8dc2d12a5b74ac0501bcf73ccec38064fd \
  --index-points 46121 \
  --qdrant-version 1.18.2 \
  --embedding-model qwen3-embedding:latest
```

The stability run added `--modes ask --slow-repeats 3`.

## Raw evidence

- `bench/benchmark_rust_production_audit_results.json`: exact historical
  repeat policy, all six modes, per-scenario results, resources, and embedded
  saved-Python/saved-Rust comparisons. SHA-256
  `388e563f69dfbbcf6dc92c1d69db653f7a1d88879acdcf811a42f8bf85ce86a1`.
- `bench/benchmark_rust_production_audit_ask_stability_results.json`: all 30
  `/ask` outcomes. SHA-256
  `75a6a056759cf47ca444a18bf6ba14ea9ca8b541b058e96700b5b1cdd48830b1`.
- `bench/benchmark_rust_production_audit_previous_binary_results.json`:
  contemporaneous installed-previous-binary control. SHA-256
  `dc726dfcbb1157a09788ab050f386e07dd3189bbaa60421fb3d187532ff41b13`.

## Limitations and next benchmark

- Python was not rerun live; its immutable saved scenario-level baseline was
  used. The baseline and saved Rust run lack binary/service-state fingerprints
  now captured by the improved runner.
- Service and OS caches were warm, mode order was fixed, and the A/B was
  sequential. Future performance work should alternate binaries, randomize
  scenario order, use multiple fresh processes, and report confidence
  intervals.
- Shared Ollama introduces model and GPU-load variance. Pin sampling/model
  settings where supported and report model-process resources separately.
- The test covers retrieval from an existing index. It does not benchmark
  indexing throughput, full-rebuild availability, cancellation, concurrent
  clients, or the corrected 2560-dimensional default model.
- Add a larger versioned corpus with relevance judgments, recall@k, MRR/nDCG,
  citation correctness, and agent-task success before treating these ten
  golden-file scenarios as a release-quality gate.
