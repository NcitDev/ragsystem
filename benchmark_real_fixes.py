#!/usr/bin/env python3
"""Real-world fix benchmark.

Instead of synthetic scenarios, this uses 3 REAL bug fixes merged into
Signal-Android (ancestors of our indexed commit d6871f8 / v8.15.3). The NL
"task" is the actual fix description; the golden set is the exact source files
that commit changed. We then ask each retrieval tool the task and measure
whether it surfaces the files a developer actually had to touch — plus the
context tokens it would dump into the agent.

Tools: rag-agentic-pool, rag-agentic, graphify, ast-index, vanilla-rg, serena.

Run on the box that hosts the daemon + ast-index + graph.json + serena:
  RAG_BENCH_ROOT=/home/nikita/development/Signal-Android python3 benchmark_real_fixes.py
"""
import os
import sys

import benchmark_all_tools as B

PKG = "app/src/main/java/org/thoughtcrime/securesms"

# (commit, NL task = real fix description, golden files actually changed)
REAL = [
    ("16232e2f", "Transfer control is showing stale data or not responding", [
        f"{PKG}/components/transfercontrols/TransferControlView.kt",
        f"{PKG}/components/transfercontrols/TransferControls.kt",
    ]),
    ("4cdd1f70", "Contact search list flickers when the query changes", [
        f"{PKG}/contacts/ContactRepository.java",
        f"{PKG}/contacts/paged/ContactSearchPagedDataSource.kt",
        f"{PKG}/contacts/paged/ContactSearchPagedDataSourceRepository.kt",
        f"{PKG}/contacts/paged/ContactSearchViewModel.kt",
    ]),
    ("f7eaa1cb", "Outgoing group calls show as incoming when someone joins", [
        f"{PKG}/service/webrtc/GroupConnectedActionProcessor.java",
    ]),
]

TOOLS = ["vanilla-rg", "ast-index", "graphify", "serena", "rag-agentic", "rag-agentic-pool"]


def main():
    global TOOLS
    if len(sys.argv) > 1:
        TOOLS = [t.strip() for t in sys.argv[1].split(",")]
    token = B._get_token()
    scenarios = [B.Scenario(i + 1, "real-fix", task, golden)
                 for i, (_sha, task, golden) in enumerate(REAL)]
    agg = {t: {"hits": 0, "golden": 0, "files": 0, "tokens": 0, "lat": 0.0, "n": 0, "err": 0}
           for t in TOOLS}
    for (sha, task, golden), sc in zip(REAL, scenarios):
        print(f"\n{'='*100}\n[{sha}] {task}\n  golden ({len(golden)}): "
              f"{', '.join(g.split('/')[-1] for g in golden)}\n{'-'*100}")
        for t in TOOLS:
            r = B.DRIVERS[t](sc, token)
            r.score(sc.golden_files)
            a = agg[t]
            a["golden"] += len(golden); a["n"] += 1
            if r.error:
                a["err"] += 1
                print(f"  {t:<17} ERROR {r.error[:60]}")
                continue
            a["hits"] += len(r.golden_hits); a["files"] += len(r.files)
            a["tokens"] += r.tokens; a["lat"] += r.latency_ms
            hit_names = ", ".join(h.split('/')[-1] for h in r.golden_hits) or "-"
            print(f"  {t:<17} hit={len(r.golden_hits)}/{len(golden)} files={len(r.files):<3} "
                  f"tok={r.tokens:6d} cov={r.coverage(golden):5.1f}% lat={r.latency_ms:6.0f}ms  [{hit_names}]")

    print(f"\n{'='*100}\n  TOTALS (3 real fixes)\n{'='*100}")
    print(f"  {'tool':<17} {'coverage':>9} {'golden':>8} {'files':>6} {'tokens':>8} {'tok/fix':>8} {'lat':>7}")
    for t in TOOLS:
        a = agg[t]
        cov = a["hits"] / a["golden"] * 100 if a["golden"] else 0
        nfix = max(1, a["n"] - a["err"])
        print(f"  {t:<17} {cov:8.1f}% {a['hits']:>3}/{a['golden']:<3} {a['files']:>6} "
              f"{a['tokens']:>8} {a['tokens']//nfix:>8} {a['lat']/nfix:>6.0f}ms"
              + ("  (errors)" if a["err"] else ""))


if __name__ == "__main__":
    main()
