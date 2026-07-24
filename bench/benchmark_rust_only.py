"""Rust-only benchmark vs the saved Python baseline (no live Python daemon).

Runs every retrieval mode against the Rust daemon (:7890), samples its
resources, and prints each result next to `bench/python_baseline.json` — the
Python numbers captured on 2026-07-18 before Python was removed.

Usage:
    python benchmark_rust_only.py [--repeats 2] [--rust-cold-ms N]
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from benchmark_planner_comparison import SCENARIOS, _get_token, _golden_hits
from benchmark_full_matrix import (
    MODES, SLOW_MODES, SYMBOLS, run_mode, _pctl,
    _pid_for_port, _proc_metrics, _install_footprint, _gpu_snapshot,
)

RUST = "http://127.0.0.1:7890"
REPO = "signal"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--modes", type=str, default=",".join(MODES))
    ap.add_argument("--rust-cold-ms", type=float, default=None,
                    help="Externally measured Rust cold-start to /health, ms.")
    args = ap.parse_args()
    modes = [m for m in args.modes.split(",") if m in MODES]

    baseline_path = Path(__file__).with_name("python_baseline.json")
    baseline = json.loads(baseline_path.read_text()) if baseline_path.exists() else {"modes": {}}
    token = _get_token()
    pid = _pid_for_port(7890)

    print(f"rust={RUST}   repeats={args.repeats}   baseline={baseline.get('captured', '?')}")
    print(f"{'mode':<9} {'py cov':>7} {'rs cov':>7} | {'py prec':>8} {'rs prec':>8} | "
          f"{'py lat':>8} {'rs lat':>8}")
    print("-" * 66)

    out: dict = {"modes": {}, "resources": {}}
    res_start = _proc_metrics(pid) if pid else {}
    for mode in modes:
        repeats = 1 if mode in SLOW_MODES else args.repeats
        cov_sum = prec_sum = 0.0
        lats: list[float] = []
        for sc in SCENARIOS:
            runs = [run_mode(mode, RUST, token, sc, SYMBOLS[sc.id]) for _ in range(repeats)]
            ok = [r for r in runs if not r[2]]
            sample = ok[-1] if ok else runs[-1]
            hits = _golden_hits(sample[0], sc.golden_files)
            cov_sum += len(hits) / len(sc.golden_files) * 100
            prec_sum += len(hits) / max(1, len(sample[0])) * 100
            lats += [r[1] for r in ok]
        rs = {
            "coverage": round(cov_sum / len(SCENARIOS), 1),
            "precision": round(prec_sum / len(SCENARIOS), 1),
            "latency_mean": round(statistics.mean(lats), 1) if lats else 0.0,
            "latency_p50": round(_pctl(lats, 0.5), 1),
            "latency_p95": round(_pctl(lats, 0.95), 1),
        }
        out["modes"][mode] = rs
        py = baseline.get("modes", {}).get(mode, {}).get("summary", {})
        print(f"{mode:<9} {py.get('coverage', 0):6.1f}% {rs['coverage']:6.1f}% | "
              f"{py.get('precision', 0):7.1f}% {rs['precision']:7.1f}% | "
              f"{py.get('latency_mean', 0):6.0f}ms {rs['latency_mean']:6.0f}ms")

    res_end = _proc_metrics(pid) if pid else {}
    out["resources"] = {
        "rss_mb": res_end.get("rss_mb"),
        "peak_rss_mb": res_end.get("peak_rss_mb"),
        "cpu_seconds_total": round(res_end.get("cpu_seconds", 0) - res_start.get("cpu_seconds", 0), 2),
        "threads": res_end.get("threads"),
        "open_fds": res_end.get("open_fds"),
        "cold_start_ms": args.rust_cold_ms,
        "footprint": _install_footprint(),
        "gpu": _gpu_snapshot(),
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
          f"{r['footprint'].get('rust_binary_mb')} binary")

    out_path = Path(__file__).with_name("benchmark_rust_only_results.json")
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nJSON: {out_path}")


if __name__ == "__main__":
    main()
