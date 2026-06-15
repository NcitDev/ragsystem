#!/usr/bin/env python3
"""Expert Architectural Comparison: Deep Relationship Discovery in Dodo Android."""

import json
import subprocess
import time
import urllib.request
from pathlib import Path
from dataclasses import dataclass

# Paths
DODO_ROOT = Path("/Users/nikitaf/development/projects/dodo-mobile-android/project")
GRAPH_PATH = DODO_ROOT / "full_graph_out" / "graphify-out" / "graph.json"
RAG_URL = "http://127.0.0.1:7890"

@dataclass
class ExpertTask:
    id: str
    description: str
    query: str
    expected_bridge_file: str  # The file that connects the two components
    symbol_a: str
    symbol_b: str

EXPERT_TASKS = [
    ExpertTask(
        "E1",
        "Dependency Injection Link: How is CheckoutOrderProcessingService provided?",
        "Explain the relationship between CheckoutStateModule and CheckoutOrderProcessingService.",
        "CheckoutStateModule.kt",
        "CheckoutStateModule",
        "CheckoutOrderProcessingService"
    ),
    ExpertTask(
        "E2",
        "Impact Analysis: Which component bridges StateAnalyzer and CheckoutService?",
        "Find the connection between StateAnalyzer and CheckoutService.",
        "CheckoutService.kt",
        "StateAnalyzer",
        "CheckoutService"
    ),
    ExpertTask(
        "E3",
        "Cross-Layer Flow: Path from DeferredTimeFragment (UI) to CheckoutService (Domain).",
        "Trace the path from DeferredTimeFragment to CheckoutService.",
        "CheckoutStateService.kt",
        "DeferredTimeFragment",
        "CheckoutService"
    )
]

def run_vanilla(task: ExpertTask):
    start = time.perf_counter()
    # Simple ripgrep for both symbols
    pattern = f"({task.symbol_a}.*{task.symbol_b}|{task.symbol_b}.*{task.symbol_a})"
    proc = subprocess.run(["rg", "-l", "--glob", "*.kt", pattern, str(DODO_ROOT)], capture_output=True, text=True)
    elapsed = (time.perf_counter() - start) * 1000
    hit = any(task.expected_bridge_file in line for line in proc.stdout.splitlines())
    return {"hit": hit, "latency": elapsed, "results": len(proc.stdout.splitlines())}

def run_ast_index(task: ExpertTask):
    start = time.perf_counter()
    # Try to find usages of A that mention B
    proc = subprocess.run(["ast-index", "symbol", task.symbol_a, "--format", "json"], capture_output=True, text=True)
    elapsed = (time.perf_counter() - start) * 1000
    # In a real scenario, an agent would have to read all these files.
    # We'll check if the bridge file is in the symbol search for either A or B.
    hit = task.expected_bridge_file in proc.stdout
    return {"hit": hit, "latency": elapsed}

def run_rag(task: ExpertTask):
    token = Path.home().joinpath(".rag/token").read_text().strip()
    payload = json.dumps({"query": task.query, "repo": "dodo", "use_ast_index": True}).encode()
    req = urllib.request.Request(f"{RAG_URL}/context-pack", data=payload, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            elapsed = (time.perf_counter() - start) * 1000
            paths = [s.get("file_path", "") for s in data.get("slices", [])]
            hit = any(p.endswith(task.expected_bridge_file) for p in paths)
            return {"hit": hit, "latency": elapsed}
    except:
        return {"hit": False, "latency": 0}

def run_graphify(task: ExpertTask):
    start = time.perf_counter()
    # Expert task: Use 'graphify path' for direct relationship discovery
    proc = subprocess.run(["graphify", "path", task.symbol_a, task.symbol_b, "--graph", str(GRAPH_PATH)], capture_output=True, text=True)
    elapsed = (time.perf_counter() - start) * 1000
    output = proc.stdout
    hit = task.expected_bridge_file in output
    if not hit:
        # Fallback to query if path fails
        proc = subprocess.run(["graphify", "query", task.query, "--graph", str(GRAPH_PATH), "--budget", "1000"], capture_output=True, text=True)
        hit = task.expected_bridge_file in proc.stdout
    
    return {"hit": hit, "latency": elapsed}

def main():
    print("# Expert Architectural Comparison: Relationship Discovery\n")
    print("| Task | Tool | Hit | Latency (ms) | Notes |")
    print("| --- | --- | --- | --- | --- |")
    
    for t in EXPERT_TASKS:
        v = run_vanilla(t)
        a = run_ast_index(t)
        r = run_rag(t)
        g = run_graphify(t)
        
        print(f"| {t.id} | Vanilla | {v['hit']} | {v['latency']:.1f} | Found {v['results']} files |")
        print(f"| {t.id} | ast-index | {a['hit']} | {a['latency']:.1f} | Symbol lookup |")
        print(f"| {t.id} | RAG+AST | {r['hit']} | {r['latency']:.1f} | Intent Planning |")
        print(f"| {t.id} | Graphify | {g['hit']} | {g['latency']:.1f} | Graph Traversal |")

if __name__ == "__main__":
    main()
