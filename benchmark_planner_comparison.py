"""Benchmark: Smart Agent planner comparison — LLM (agy) vs Fallback (heuristic).

This is a REAL retrieval eval, unlike benchmark_production_scenarios.py:

  * The agent is given ONLY the natural-language question. No golden symbols,
    no hand-authored tool path, no reading golden files off disk on a miss.
  * It drives the actual product query pipeline (`POST /search` on the running
    daemon), which runs `plan_search` → strategy dispatch → scoring → results.
  * We score the files the pipeline actually returns against the golden set.

The only thing that differs between the two columns is the *planner*:

  * "Smart+LLM"      — `planner="llm"`:      LLM strategy planner (agy / Gemini)
  * "Smart+Fallback" — `planner="fallback"`: deterministic heuristic planner

So any difference in precision/coverage/latency is attributable to the planner,
measured on the real index. Metrics are computed from real HTTP responses;
there are no `len//4` token estimates and no oracle.

Usage:
    rag start                       # daemon must be running, signal repo indexed
    python benchmark_planner_comparison.py [--top-k 15] [--repeats 1]
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RAG_URL = "http://127.0.0.1:7890"
REPO_NAME = "signal"
PKG = "app/src/main/java/org/thoughtcrime/securesms"

PLANNERS = ["fallback", "llm"]  # column order in the report


@dataclass
class Scenario:
    id: int
    category: str
    question: str          # the ONLY thing handed to the agent
    golden_files: list[str]


# Questions + golden sets reused from the production scenarios. Symbols and
# tool paths are deliberately NOT carried over — the agent must work from the
# natural-language question alone.
SCENARIOS: list[Scenario] = [
    Scenario(1, "feature", "Add a sticker pack install event. What's the existing pattern?", [
        f"{PKG}/stickers/StickerPackInstallEvent.java",
        f"{PKG}/stickers/preview/StickerPackPreviewRepository.java",
        f"{PKG}/stickers/preview/StickerPackPreviewViewModel.java",
    ]),
    Scenario(2, "migration", "Find the database migration interface and show a concrete migration", [
        f"{PKG}/database/helpers/migration/SignalDatabaseMigration.kt",
        f"{PKG}/database/helpers/SignalDatabaseMigrations.kt",
    ]),
    Scenario(3, "arch", "Show me the main classes in the sticker pack management system", [
        f"{PKG}/stickers/manage/StickerManagementRepository.kt",
        f"{PKG}/stickers/BlessedPacks.kt",
        f"{PKG}/stickers/preview/StickerPackPreviewViewModelV2.kt",
    ]),
    Scenario(4, "feature", "I need to add a new backup feature. Show me how FullBackupExporter works", [
        f"{PKG}/backup/FullBackupExporter.java",
        f"{PKG}/backup/FullBackupBase.java",
    ]),
    Scenario(5, "migration", "Find deprecated job migration code that should be cleaned up", [
        f"{PKG}/jobmanager/migrations/DeprecatedJobMigration.kt",
        f"{PKG}/jobmanager/migrations/PushDecryptMessageJobEnvelopeMigration.kt",
        f"{PKG}/jobmanager/migrations/PushProcessMessageJobMigration.kt",
    ]),
    Scenario(6, "impact", "If I change the Job base class, what code breaks? Show all subclasses", [
        f"{PKG}/jobmanager/Job.java",
        f"{PKG}/jobmanager/JobManager.java",
        f"{PKG}/jobs/PushDecryptMessageJob.java",
        f"{PKG}/jobmanager/migrations/PushProcessMessageJobMigration.kt",
    ]),
    Scenario(7, "refactor", "Rename SignalDatabaseMigration interface. Find all implementors and callers", [
        f"{PKG}/database/helpers/migration/SignalDatabaseMigration.kt",
        f"{PKG}/database/helpers/SignalDatabaseMigrations.kt",
        f"{PKG}/jobmanager/JobMigration.kt",
    ]),
    Scenario(8, "impact", "Who calls Recipient? Show me the blast radius of changing the Recipient model", [
        f"{PKG}/recipients/Recipient.kt",
        f"{PKG}/database/RecipientTable.kt",
        f"{PKG}/recipients/RecipientId.kt",
    ]),
    Scenario(9, "info", "How does the chat backup encryption and passphrase system work?", [
        f"{PKG}/backup/BackupPassphrase.java",
        f"{PKG}/backup/BackupDialog.java",
        f"{PKG}/backup/BackupVersions.kt",
    ]),
    Scenario(10, "debug", "Trace how push notifications are received and processed by the app", [
        f"{PKG}/gcm/FcmReceiveService.java",
        f"{PKG}/notifications/MessageNotifier.java",
        f"{PKG}/gcm/FcmJobService.java",
    ]),
]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    strategy: str = ""
    n_plan_queries: int = 0
    plan_filters: dict = field(default_factory=dict)
    files: list[str] = field(default_factory=list)   # distinct, in rank order
    golden_hits: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    error: str = ""

    @property
    def n_files(self) -> int:
        return len(self.files)

    def coverage(self, golden: list[str]) -> float:
        return len(self.golden_hits) / max(1, len(golden)) * 100.0

    def precision(self) -> float:
        return len(self.golden_hits) / max(1, self.n_files) * 100.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_token() -> str:
    p = Path.home() / ".rag" / "token"
    return p.read_text().strip() if p.exists() else ""


def _golden_hits(files: list[str], golden: list[str]) -> list[str]:
    hits = []
    for g in golden:
        if any(f == g or f.endswith(g) or g.endswith(f) for f in files):
            hits.append(g)
    return hits


def _search(token: str, question: str, planner: str, top_k: int) -> RunResult:
    payload = json.dumps({
        "query": question, "repo": REPO_NAME,
        "top_k": top_k, "planner": planner,
    }).encode()
    req = urllib.request.Request(
        f"{RAG_URL}/search", data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=150) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        return RunResult(error=str(exc), latency_ms=(time.time() - t0) * 1000)

    plan = data.get("plan") or {}
    files: list[str] = []
    for r in data.get("results", []):
        fp = r.get("file_path", "")
        if fp and fp not in files:
            files.append(fp)
    return RunResult(
        strategy=plan.get("strategy", ""),
        n_plan_queries=len(plan.get("queries", [])),
        plan_filters=plan.get("filters", {}) or {},
        files=files,
        latency_ms=float(data.get("latency_ms", (time.time() - t0) * 1000)),
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-k", type=int, default=15)
    ap.add_argument("--repeats", type=int, default=1,
                    help="Average each (scenario, planner) over N runs (LLM is non-deterministic).")
    args = ap.parse_args()

    token = _get_token()
    if not token:
        raise SystemExit("No RAG token at ~/.rag/token — is the daemon set up?")

    # Sanity: daemon reachable.
    try:
        urllib.request.urlopen(f"{RAG_URL}/health", timeout=5).read()
    except Exception as exc:
        raise SystemExit(f"Daemon not reachable at {RAG_URL} ({exc}). Run `rag start` first.")

    print("=" * 88)
    print("  BENCHMARK: Smart Agent planner — LLM (agy) vs Fallback (heuristic)")
    print(f"  Repo: {REPO_NAME}   top_k={args.top_k}   repeats={args.repeats}")
    print("  Input to agent: natural-language question ONLY. Scored on real /search output.")
    print("=" * 88)

    results: dict = {"top_k": args.top_k, "repeats": args.repeats, "scenarios": []}

    for sc in SCENARIOS:
        print(f"\nScenario {sc.id} [{sc.category}] — {sc.question[:64]}")
        print(f"  golden: {len(sc.golden_files)} files")
        sc_entry: dict = {
            "id": sc.id, "category": sc.category, "question": sc.question,
            "golden_count": len(sc.golden_files), "planners": {},
        }
        for planner in PLANNERS:
            # Average over repeats; take the run with median coverage for the
            # qualitative file list (here: last run is fine, metrics averaged).
            runs = [_search(token, sc.question, planner, args.top_k) for _ in range(args.repeats)]
            for r in runs:
                r.golden_hits = _golden_hits(r.files, sc.golden_files)
            ok = [r for r in runs if not r.error]
            sample = ok[-1] if ok else runs[-1]
            n = max(1, len(ok))
            avg_cov = sum(r.coverage(sc.golden_files) for r in ok) / n if ok else 0.0
            avg_prec = sum(r.precision() for r in ok) / n if ok else 0.0
            avg_lat = sum(r.latency_ms for r in ok) / n if ok else 0.0
            avg_files = sum(r.n_files for r in ok) / n if ok else 0.0

            sc_entry["planners"][planner] = {
                "strategy": sample.strategy,
                "n_plan_queries": sample.n_plan_queries,
                "plan_filters": sample.plan_filters,
                "files_returned": round(avg_files, 1),
                "golden_hits": len(sample.golden_hits),
                "coverage_pct": round(avg_cov, 1),
                "precision_pct": round(avg_prec, 1),
                "latency_ms": round(avg_lat, 1),
                "error": sample.error,
                "golden_found": sample.golden_hits,
            }
            tag = "ERR " + sample.error[:40] if sample.error else "OK"
            print(
                f"    {planner:<9} strat={sample.strategy:<10} "
                f"files={avg_files:4.1f} cov={avg_cov:5.1f}% prec={avg_prec:5.1f}% "
                f"lat={avg_lat:7.0f}ms  [{tag}]"
            )
        results["scenarios"].append(sc_entry)

    # --- Averages ---
    print(f"\n{'=' * 88}")
    print("  AVERAGES")
    print(f"{'=' * 88}")
    summary: dict = {}
    for planner in PLANNERS:
        vals = [s["planners"][planner] for s in results["scenarios"]]
        summary[planner] = {
            "coverage": sum(v["coverage_pct"] for v in vals) / len(vals),
            "precision": sum(v["precision_pct"] for v in vals) / len(vals),
            "files": sum(v["files_returned"] for v in vals) / len(vals),
            "latency": sum(v["latency_ms"] for v in vals) / len(vals),
        }
        s = summary[planner]
        print(f"  {planner:<9} cov={s['coverage']:5.1f}%  prec={s['precision']:5.1f}%  "
              f"files={s['files']:4.1f}  lat={s['latency']:7.0f}ms")
    results["summary"] = summary

    # --- Save ---
    out_json = Path("benchmark_planner_results.json")
    out_json.write_text(json.dumps(results, indent=2))
    print(f"\nJSON saved to: {out_json}")
    _write_report(results)


def _write_report(results: dict) -> None:
    md_dir = Path("docs/benchmark_planner_comparison")
    md_dir.mkdir(parents=True, exist_ok=True)
    L = [
        "# Smart Agent Planner Comparison — LLM (agy) vs Fallback\n",
        "Real retrieval eval: the agent receives **only the natural-language "
        "question** and drives the live `/search` pipeline. Files returned are "
        "scored against the golden set. No tool-path hints, no handed-in "
        "symbols, no oracle backfill.\n",
        f"**top_k:** {results['top_k']}  |  **repeats:** {results['repeats']}\n",
        "## Averages\n",
        "| Planner | Avg Coverage | Avg Precision | Avg Files | Avg Latency |",
        "|---|---:|---:|---:|---:|",
    ]
    for planner, s in results["summary"].items():
        L.append(f"| {planner} | {s['coverage']:.1f}% | {s['precision']:.1f}% | "
                 f"{s['files']:.1f} | {s['latency']:.0f}ms |")
    L.append("\n## Per-scenario\n")
    for sc in results["scenarios"]:
        L.append(f"### S{sc['id']} [{sc['category']}] — {sc['question']}\n")
        L.append(f"Golden: {sc['golden_count']} files\n")
        L.append("| Planner | Strategy | Plan Qs | Files | Golden Hit | Coverage | Precision | Latency |")
        L.append("|---|---|---:|---:|---:|---:|---:|---:|")
        for planner, p in sc["planners"].items():
            L.append(
                f"| {planner} | {p['strategy']} | {p['n_plan_queries']} | "
                f"{p['files_returned']} | {p['golden_hits']}/{sc['golden_count']} | "
                f"{p['coverage_pct']:.1f}% | {p['precision_pct']:.1f}% | {p['latency_ms']:.0f}ms |"
            )
        L.append("")
    (md_dir / "summary.md").write_text("\n".join(L))
    print(f"Markdown report: {md_dir / 'summary.md'}")


if __name__ == "__main__":
    main()
