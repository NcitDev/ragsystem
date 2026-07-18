"""Rust-only benchmark vs saved Python and previous-Rust baselines.

Runs every retrieval mode against a configurable Rust daemon, samples its
resources, and prints each result next to the saved full-matrix baselines. The
URL and token path flags allow an isolated benchmark daemon rather than the
user's live service.

Usage:
    python benchmark_rust_only.py --rust-url http://127.0.0.1:17890 \
        --token-file /tmp/bench-rag-home/token --output /tmp/results.json
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import platform
import statistics
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

from benchmark_planner_comparison import SCENARIOS, _golden_hits
from benchmark_full_matrix import (
    MODES, SLOW_MODES, SYMBOLS, run_mode, _pctl,
    _pid_for_port, _proc_metrics, _gpu_snapshot, _post,
)

RUST = "http://127.0.0.1:7890"
REPO = "signal"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_output(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], check=True, capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _saved_summary(data: dict, mode: str, target: str | None = None) -> dict:
    entry = data.get("modes", {}).get(mode, {})
    summary = entry.get("summary", entry)
    if target is not None:
        summary = summary.get(target, {})
    return summary if isinstance(summary, dict) else {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--modes", type=str, default=",".join(MODES))
    ap.add_argument("--rust-url", default=RUST)
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--token-file", type=Path, default=Path.home() / ".rag" / "token")
    ap.add_argument(
        "--python-baseline", type=Path,
        default=Path(__file__).with_name("python_baseline.json"),
    )
    ap.add_argument(
        "--previous-rust", type=Path,
        default=Path(__file__).with_name("benchmark_full_matrix_results.json"),
    )
    ap.add_argument(
        "--output", type=Path,
        default=Path(__file__).with_name("benchmark_rust_only_results.json"),
    )
    ap.add_argument("--rust-binary", type=Path)
    ap.add_argument("--rust-cold-ms", type=float, default=None,
                    help="Externally measured Rust cold-start to /health, ms.")
    ap.add_argument("--rust-live-ms", type=float, default=None)
    ap.add_argument("--rust-ready-ms", type=float, default=None)
    ap.add_argument("--corpus-revision", default="")
    ap.add_argument("--index-points", type=int)
    ap.add_argument("--qdrant-version", default="")
    ap.add_argument("--embedding-model", default="")
    args = ap.parse_args()
    modes = [m for m in args.modes.split(",") if m in MODES]
    if not modes:
        raise SystemExit("No recognized benchmark modes selected")
    if args.repeats < 1:
        raise SystemExit("--repeats must be at least 1")

    baseline = json.loads(args.python_baseline.read_text())
    previous = json.loads(args.previous_rust.read_text())
    token = args.token_file.read_text().strip()
    if not token:
        raise SystemExit(f"Empty benchmark token: {args.token_file}")
    parsed_url = urlparse(args.rust_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
        raise SystemExit("--rust-url must be an absolute HTTP(S) URL")
    port = parsed_url.port or (443 if parsed_url.scheme == "https" else 80)
    pid = _pid_for_port(port)
    if pid is None:
        raise SystemExit(f"No listening Rust process found for {args.rust_url}")

    _, _, warmup_error = _post(
        args.rust_url, "/search",
        {"query": "warmup", "repo": args.repo, "top_k": 3, "planner": "fallback"},
        token,
    )
    if warmup_error:
        raise SystemExit(f"Rust benchmark daemon is not usable: {warmup_error}")

    print(f"rust={args.rust_url}   repo={args.repo}   repeats={args.repeats}")
    print(f"{'mode':<9} {'coverage py/prev/new':>24} | {'precision py/prev/new':>25} | "
          f"{'latency py/prev/new':>25}")
    print("-" * 91)

    started = time.monotonic()
    binary = args.rust_binary.resolve() if args.rust_binary else None
    out: dict = {
        "schema_version": 2,
        "captured": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "provenance": {
            "git_head": _git_output("rev-parse", "HEAD"),
            "git_dirty": bool(_git_output("status", "--porcelain")),
            "rust_url": args.rust_url,
            "server_pid": pid,
            "repo": args.repo,
            "corpus_revision": args.corpus_revision or None,
            "index_points": args.index_points,
            "qdrant_version": args.qdrant_version or None,
            "embedding_model": args.embedding_model or None,
            "scenario_count": len(SCENARIOS),
            "repeats": args.repeats,
            "slow_mode_repeats": 1,
            "modes": modes,
            "python_baseline_sha256": _sha256(args.python_baseline),
            "previous_rust_results_sha256": _sha256(args.previous_rust),
            "rust_binary": str(binary) if binary else None,
            "rust_binary_sha256": _sha256(binary) if binary and binary.is_file() else None,
            "rust_binary_bytes": binary.stat().st_size if binary and binary.is_file() else None,
            "platform": platform.platform(),
            "logical_cpus": os.cpu_count(),
        },
        "startup_ms": {
            "live": args.rust_live_ms,
            "ready": args.rust_ready_ms,
            "health": args.rust_cold_ms,
        },
        "comparisons": {},
        "modes": {},
        "resources": {},
    }
    res_start = _proc_metrics(pid) if pid else {}
    for mode in modes:
        repeats = 1 if mode in SLOW_MODES else args.repeats
        cov_sum = prec_sum = 0.0
        lats: list[float] = []
        errors = 0
        files_sum = 0
        scenarios: list[dict] = []
        for sc in SCENARIOS:
            runs = [
                run_mode(mode, args.rust_url, token, sc, SYMBOLS[sc.id], repo=args.repo)
                for _ in range(repeats)
            ]
            ok = [r for r in runs if not r[2]]
            sample = ok[-1] if ok else runs[-1]
            hits = _golden_hits(sample[0], sc.golden_files)
            cov_sum += len(hits) / len(sc.golden_files) * 100
            prec_sum += len(hits) / max(1, len(sample[0])) * 100
            files_sum += len(sample[0])
            lats += [r[1] for r in ok]
            run_errors = [r[2] for r in runs if r[2]]
            errors += len(run_errors)
            scenarios.append({
                "id": sc.id,
                "symbol": SYMBOLS[sc.id],
                "files": len(sample[0]),
                "golden_hits": len(hits),
                "coverage_pct": round(len(hits) / len(sc.golden_files) * 100, 1),
                "precision_pct": round(len(hits) / max(1, len(sample[0])) * 100, 1),
                "latencies_ms": [round(r[1], 1) for r in ok],
                "errors": run_errors,
                **sample[3],
            })
        rs = {
            "coverage": round(cov_sum / len(SCENARIOS), 1),
            "precision": round(prec_sum / len(SCENARIOS), 1),
            "files": round(files_sum / len(SCENARIOS), 1),
            "latency_mean": round(statistics.mean(lats), 1) if lats else 0.0,
            "latency_p50": round(_pctl(lats, 0.5), 1),
            "latency_p95": round(_pctl(lats, 0.95), 1),
            "errors": errors,
        }
        out["modes"][mode] = {"summary": rs, "scenarios": scenarios}
        py = _saved_summary(baseline, mode)
        prev = _saved_summary(previous, mode, "rust")
        out["comparisons"][mode] = {
            "python": py,
            "previous_rust": prev,
            "new_rust": rs,
        }
        print(
            f"{mode:<9} {py.get('coverage', 0):5.1f}/{prev.get('coverage', 0):5.1f}/{rs['coverage']:5.1f}% | "
            f"{py.get('precision', 0):6.1f}/{prev.get('precision', 0):6.1f}/{rs['precision']:6.1f}% | "
            f"{py.get('latency_mean', 0):6.0f}/{prev.get('latency_mean', 0):6.0f}/{rs['latency_mean']:6.0f}ms"
        )

    res_end = _proc_metrics(pid) if pid else {}
    out["resources"] = {
        "rss_mb": res_end.get("rss_mb"),
        "peak_rss_mb": res_end.get("peak_rss_mb"),
        "cpu_seconds_total": round(res_end.get("cpu_seconds", 0) - res_start.get("cpu_seconds", 0), 2),
        "threads": res_end.get("threads"),
        "open_fds": res_end.get("open_fds"),
        "cold_start_ms": args.rust_cold_ms,
        "binary_mb": round(binary.stat().st_size / 1048576, 1)
            if binary and binary.is_file() else None,
        "gpu": _gpu_snapshot(),
        "benchmark_wall_seconds": round(time.monotonic() - started, 2),
    }

    print("\n=== RESOURCES  (python baseline → rust now)")
    pbr = baseline.get("resources", {})
    penv = baseline.get("environment", {})
    r = out["resources"]
    print(f"  RSS (MB)        {pbr.get('rss_mb', '?'):>8}  →  {r['rss_mb']:>8}")
    print(f"  Peak RSS (MB)   {pbr.get('peak_rss_mb', '?'):>8}  →  {r['peak_rss_mb']:>8}")
    print(f"  CPU sec (run)   {pbr.get('cpu_seconds_total', '?'):>8}  →  {r['cpu_seconds_total']:>8}")
    print(f"  Threads / FDs   {pbr.get('threads', '?')}/{pbr.get('open_fds', '?'):<6} → "
          f"  {r['threads']}/{r['open_fds']}")
    print(f"  Cold start (ms) {penv.get('cold_start_ms', '?'):>8}  →  {r['cold_start_ms']}")
    print(f"  Footprint (MB)  {penv.get('install_footprint_mb', '?')} venv  →  "
          f"{r['binary_mb']} binary")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2) + "\n")
    print(f"\nJSON: {args.output}")


if __name__ == "__main__":
    main()
