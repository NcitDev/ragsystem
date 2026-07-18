"""Full retrieval-mode matrix: Python daemon vs Rust daemon, with resources.

Modes (identical HTTP requests to both stacks, same ~/.rag state, same Qdrant):
  vanilla  POST /search        planner=fallback  — dense multi-query pipeline
  rag_llm  POST /search        planner=llm       — LLM (qwen3:8b) strategy plan
  smart    POST /smart-search                    — RAG + AST + vocab buckets
  ast      POST /resolve                         — exact symbol defs/usages
  graph    POST /graph/impact                    — blast radius (graphify)
  ask      POST /ask                             — grounded generation

Also samples per-daemon resource use (RSS/peak/threads/FDs/CPU-seconds/IO),
install footprint, GPU, and (externally-supplied) cold-start.

Usage:
    # Python daemon on :7891 and Rust daemon on :7890 must both be running
    python benchmark_full_matrix.py [--repeats 2] [--startup-json '{"python":..,"rust":..}']
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from benchmark_planner_comparison import SCENARIOS, _get_token, _golden_hits

TARGETS = [("python", "http://127.0.0.1:7891"), ("rust", "http://127.0.0.1:7890")]
REPO = "signal"

SYMBOLS = {
    1: "StickerPackInstallEvent",
    2: "SignalDatabaseMigration",
    3: "StickerManagementRepository",
    4: "FullBackupExporter",
    5: "DeprecatedJobMigration",
    6: "Job",
    7: "SignalDatabaseMigration",
    8: "Recipient",
    9: "BackupPassphrase",
    10: "FcmReceiveService",
}

SLOW_MODES = {"rag_llm", "ask"}
MODES = ["vanilla", "rag_llm", "smart", "ast", "graph", "ask"]


# --------------------------------------------------------------------------
# Process resource metrics (Linux /proc; daemons run as the current user)
# --------------------------------------------------------------------------

def _pid_for_port(port: int) -> int | None:
    try:
        out = subprocess.run(
            ["ss", "-ltnp", f"sport = :{port}"], capture_output=True, text=True, timeout=5
        ).stdout
        return int(out.split("pid=")[1].split(",")[0])
    except (IndexError, ValueError, subprocess.SubprocessError):
        return None


def _proc_metrics(pid: int) -> dict:
    try:
        status = Path(f"/proc/{pid}/status").read_text()
        fields = {}
        for line in status.splitlines():
            key = line.split(":")[0]
            if key in ("VmRSS", "VmHWM", "Threads"):
                fields[key] = int(line.split()[1])
        stat = Path(f"/proc/{pid}/stat").read_text()
        after_comm = stat.rsplit(")", 1)[1].split()
        clk = os.sysconf("SC_CLK_TCK")
        cpu_seconds = (int(after_comm[11]) + int(after_comm[12])) / clk
        io: dict = {}
        try:
            for line in Path(f"/proc/{pid}/io").read_text().splitlines():
                key, _, value = line.partition(":")
                if key in ("read_bytes", "write_bytes"):
                    io[key] = int(value)
        except OSError:
            pass
        fd_count = len(os.listdir(f"/proc/{pid}/fd"))
        return {
            "pid": pid,
            "rss_mb": round(fields.get("VmRSS", 0) / 1024, 1),
            "peak_rss_mb": round(fields.get("VmHWM", 0) / 1024, 1),
            "threads": fields.get("Threads", 0),
            "cpu_seconds": round(cpu_seconds, 2),
            "read_mb": round(io.get("read_bytes", 0) / 1048576, 1),
            "write_mb": round(io.get("write_bytes", 0) / 1048576, 1),
            "open_fds": fd_count,
        }
    except (OSError, IndexError, ValueError):
        return {"pid": pid}


def _install_footprint() -> dict:
    out: dict = {}
    rust_bin = Path.home() / ".local" / "bin" / "rag"
    if rust_bin.exists():
        out["rust_binary_mb"] = round(rust_bin.stat().st_size / 1048576, 1)
    venv = Path(__file__).resolve().parent.parent / ".venv"
    if venv.exists():
        try:
            size = subprocess.run(
                ["du", "-sm", str(venv)], capture_output=True, text=True, timeout=60
            ).stdout.split()[0]
            out["python_venv_mb"] = float(size)
        except (subprocess.SubprocessError, IndexError, ValueError):
            pass
    return out


def _gpu_snapshot() -> str:
    try:
        return subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except subprocess.SubprocessError:
        return ""


def _post(base: str, path: str, payload: dict, token: str, timeout: int = 300):
    req = urllib.request.Request(
        f"{base}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        return data, (time.time() - t0) * 1000, ""
    except Exception as exc:  # noqa: BLE001
        return {}, (time.time() - t0) * 1000, f"{type(exc).__name__}: {exc}"


def _files_from(items) -> list[str]:
    out: list[str] = []
    for item in items or []:
        fp = item if isinstance(item, str) else (item.get("file_path", "") if isinstance(item, dict) else "")
        if fp and fp not in out:
            out.append(fp)
    return out


def run_mode(mode: str, base: str, token: str, sc, symbol: str):
    if mode in ("vanilla", "rag_llm"):
        planner = "fallback" if mode == "vanilla" else "llm"
        data, wall, err = _post(base, "/search", {
            "query": sc.question, "repo": REPO, "top_k": 15, "planner": planner}, token)
        return (_files_from(data.get("results")), float(data.get("latency_ms", wall)), err, {})
    if mode == "smart":
        data, wall, err = _post(base, "/smart-search", {
            "question": sc.question, "repo": REPO, "top_k": 15}, token)
        files: list[str] = []
        for bucket in ("definitions", "usages", "semantic", "related", "vocab_files", "candidates"):
            for fp in _files_from(data.get(bucket)):
                if fp not in files:
                    files.append(fp)
        return (files, float(data.get("latency_ms", wall)), err, {})
    if mode == "ast":
        data, wall, err = _post(base, "/resolve", {
            "repo": REPO, "symbols": [symbol], "definitions_limit": 20, "usages_limit": 20}, token)
        files = _files_from(data.get("definitions"))
        for fp in _files_from(data.get("usages")):
            if fp not in files:
                files.append(fp)
        return (files, float(data.get("latency_ms", wall)), err, {})
    if mode == "graph":
        data, wall, err = _post(base, "/graph/impact", {
            "repo": REPO, "symbol": symbol, "limit": 50}, token)
        files = []
        for bucket in ("definitions", "usages", "callers", "affected_files", "tests"):
            for fp in _files_from(data.get(bucket)):
                if fp not in files:
                    files.append(fp)
        return (files, float(data.get("latency_ms", wall)), err, {})
    if mode == "ask":
        data, wall, err = _post(base, "/ask", {
            "question": sc.question, "repo": REPO, "top_k": 8}, token)
        files = _files_from(data.get("citations"))
        extra = {"insufficient": bool(data.get("insufficient_context", False)),
                 "answer_chars": len(data.get("answer", "") or "")}
        return (files, float(data.get("latency_ms", wall)), err, extra)
    raise ValueError(mode)


def _pctl(values, q):
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--modes", type=str, default=",".join(MODES))
    ap.add_argument("--startup-json", type=str, default="")
    args = ap.parse_args()
    modes = [m for m in args.modes.split(",") if m in MODES]

    token = _get_token()
    for label, base in TARGETS:
        _, _, err = _post(base, "/search", {"query": "warmup", "repo": REPO, "top_k": 3,
                                            "planner": "fallback"}, token)
        if err:
            raise SystemExit(f"{label} daemon not usable at {base}: {err}")
    print(f"targets: {', '.join(f'{l}={u}' for l, u in TARGETS)}   repeats={args.repeats}")

    pids = {label: _pid_for_port(int(base.rsplit(':', 1)[1])) for label, base in TARGETS}
    results: dict = {
        "repeats": args.repeats,
        "startup_ms": json.loads(args.startup_json) if args.startup_json else {},
        "modes": {},
        "resources": {
            "footprint": _install_footprint(),
            "gpu_before": _gpu_snapshot(),
            "start": {label: _proc_metrics(pid) for label, pid in pids.items() if pid},
        },
    }
    for mode in modes:
        repeats = 1 if mode in SLOW_MODES else args.repeats
        print(f"\n=== MODE {mode} (repeats={repeats})")
        cpu_before = {label: _proc_metrics(pid).get("cpu_seconds", 0.0)
                      for label, pid in pids.items() if pid}
        mode_entry: dict = {"scenarios": [], "summary": {}}
        for sc in SCENARIOS:
            symbol = SYMBOLS[sc.id]
            row: dict = {"id": sc.id, "question": sc.question, "symbol": symbol, "targets": {}}
            for label, base in TARGETS:
                runs = [run_mode(mode, base, token, sc, symbol) for _ in range(repeats)]
                ok = [r for r in runs if not r[2]]
                sample = ok[-1] if ok else runs[-1]
                files = sample[0]
                hits = _golden_hits(files, sc.golden_files)
                lats = [r[1] for r in ok]
                row["targets"][label] = {
                    "files": len(files),
                    "golden_hits": len(hits),
                    "coverage_pct": round(len(hits) / len(sc.golden_files) * 100, 1),
                    "precision_pct": round(len(hits) / max(1, len(files)) * 100, 1),
                    "latencies_ms": [round(v, 1) for v in lats],
                    "errors": [r[2] for r in runs if r[2]],
                    **sample[3],
                }
            mode_entry["scenarios"].append(row)
            py, rs = row["targets"]["python"], row["targets"]["rust"]
            print(f"  S{sc.id:<3} py cov={py['coverage_pct']:5.1f} prec={py['precision_pct']:5.1f} "
                  f"lat={statistics.mean(py['latencies_ms']) if py['latencies_ms'] else 0:7.0f}ms | "
                  f"rs cov={rs['coverage_pct']:5.1f} prec={rs['precision_pct']:5.1f} "
                  f"lat={statistics.mean(rs['latencies_ms']) if rs['latencies_ms'] else 0:7.0f}ms")
        for label, _ in TARGETS:
            rows = [r["targets"][label] for r in mode_entry["scenarios"]]
            lats = [v for r in rows for v in r["latencies_ms"]]
            mode_entry["summary"][label] = {
                "coverage": round(sum(r["coverage_pct"] for r in rows) / len(rows), 1),
                "precision": round(sum(r["precision_pct"] for r in rows) / len(rows), 1),
                "files": round(sum(r["files"] for r in rows) / len(rows), 1),
                "latency_mean": round(statistics.mean(lats), 1) if lats else 0.0,
                "latency_p50": round(_pctl(lats, 0.5), 1),
                "latency_p95": round(_pctl(lats, 0.95), 1),
                "errors": sum(len(r["errors"]) for r in rows),
            }
        for label, pid in pids.items():
            if not pid:
                continue
            snap = _proc_metrics(pid)
            mode_entry["summary"][label]["cpu_seconds"] = round(
                snap.get("cpu_seconds", 0.0) - cpu_before.get(label, 0.0), 2)
            mode_entry["summary"][label]["rss_mb_after"] = snap.get("rss_mb", 0.0)
        results["modes"][mode] = mode_entry
        s = mode_entry["summary"]
        print(f"  AVG  py cov={s['python']['coverage']:5.1f} prec={s['python']['precision']:5.1f} "
              f"lat={s['python']['latency_mean']:7.0f}ms | "
              f"rs cov={s['rust']['coverage']:5.1f} prec={s['rust']['precision']:5.1f} "
              f"lat={s['rust']['latency_mean']:7.0f}ms")

    results["resources"]["end"] = {label: _proc_metrics(pid) for label, pid in pids.items() if pid}
    results["resources"]["gpu_after"] = _gpu_snapshot()
    print("\n=== RESOURCES")
    for label in ("python", "rust"):
        start = results["resources"]["start"].get(label, {})
        end = results["resources"]["end"].get(label, {})
        print(f"  {label:<7} rss={end.get('rss_mb', 0):8.1f}MB peak={end.get('peak_rss_mb', 0):8.1f}MB "
              f"threads={end.get('threads', 0):3} fds={end.get('open_fds', 0):4} "
              f"cpu_total={end.get('cpu_seconds', 0) - start.get('cpu_seconds', 0):7.1f}s "
              f"io_r={end.get('read_mb', 0):7.1f}MB io_w={end.get('write_mb', 0):7.1f}MB")
    print(f"  footprint: {results['resources']['footprint']}")

    out = Path(__file__).with_name("benchmark_full_matrix_results.json")
    out.write_text(json.dumps(results, indent=2))
    print(f"\nJSON: {out}")
    _write_report(results)


def _write_report(results: dict) -> None:
    md_dir = Path(__file__).resolve().parent.parent / "docs" / "benchmark_full_matrix"
    md_dir.mkdir(parents=True, exist_ok=True)
    L = [
        "# Full retrieval-mode matrix — Python vs Rust daemon\n",
        "Same `~/.rag` state, same Docker-hosted Qdrant, identical requests.\n",
        "## Mode averages\n",
        "| Mode | py cov | rs cov | py prec | rs prec | py lat | rs lat | py p95 | rs p95 | errs (py/rs) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for mode, entry in results["modes"].items():
        p, r = entry["summary"]["python"], entry["summary"]["rust"]
        L.append(f"| {mode} | {p['coverage']:.1f}% | {r['coverage']:.1f}% | "
                 f"{p['precision']:.1f}% | {r['precision']:.1f}% | "
                 f"{p['latency_mean']:.0f}ms | {r['latency_mean']:.0f}ms | "
                 f"{p['latency_p95']:.0f}ms | {r['latency_p95']:.0f}ms | {p['errors']}/{r['errors']} |")
    res = results.get("resources", {})
    if res:
        L.append("\n## Resource usage (whole matrix run)\n")
        L.append("| Metric | python | rust |")
        L.append("|---|---:|---:|")
        start, end = res.get("start", {}), res.get("end", {})
        rows = [("RSS after run (MB)", "rss_mb", None), ("Peak RSS (MB)", "peak_rss_mb", None),
                ("Threads", "threads", None), ("Open FDs", "open_fds", None),
                ("CPU seconds (run total)", "cpu_seconds", "delta"),
                ("Disk read (MB)", "read_mb", "delta"), ("Disk write (MB)", "write_mb", "delta")]
        for title, key, kind in rows:
            vals = []
            for label in ("python", "rust"):
                v = end.get(label, {}).get(key, 0)
                if kind == "delta":
                    v = round(v - start.get(label, {}).get(key, 0), 2)
                vals.append(v)
            L.append(f"| {title} | {vals[0]} | {vals[1]} |")
        fp = res.get("footprint", {})
        if fp:
            L.append(f"| Install footprint (MB) | {fp.get('python_venv_mb', '—')} (venv) "
                     f"| {fp.get('rust_binary_mb', '—')} (binary) |")
        if su := results.get("startup_ms"):
            L.append(f"| Cold start to /health (ms) | {su.get('python', '—')} | {su.get('rust', '—')} |")
    (md_dir / "summary.md").write_text("\n".join(L))
    print(f"Markdown: {md_dir / 'summary.md'}")


if __name__ == "__main__":
    main()
