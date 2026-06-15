#!/usr/bin/env python3
import json
import subprocess
import time
import urllib.request
from pathlib import Path
from dataclasses import dataclass

DODO_ROOT = Path("/Users/nikitaf/development/projects/dodo-mobile-android/project")
GRAPH_PATH = DODO_ROOT / "full_graph_out" / "graphify-out" / "graph.json"
RAG_URL = "http://127.0.0.1:7890"

@dataclass
class Task:
    id: str
    name: str
    prompt: str
    expected: list[str]
    symbols: list[str] # for ast-index and vanilla

TASKS = [
    Task("1", "Exact Symbol", "Find the definition of CheckoutOrderProcessingService.", ["CheckoutOrderProcessingService.kt"], ["CheckoutOrderProcessingService"]),
    Task("2", "Semantic Intent", "Find where the app waits for a paid order to complete and resets the state.", ["CheckoutOrderProcessingService.kt"], ["waitForPayedOrder", "setupAppStateForNewOrder"]),
    Task("3", "Deep Architecture", "Trace the path from DeferredTimeFragment to CheckoutService.", ["CheckoutStateService.kt", "CheckoutServiceImpl.kt"], ["DeferredTimeFragment", "CheckoutService"]),
    Task("4", "Dependency Injection", "How is CheckoutOrderProcessingService provided to the DI graph?", ["CheckoutStateModule.kt"], ["CheckoutOrderProcessingService"]),
    Task("5", "Blast Radius", "If I change the StateAnalyzer interface, what feature modules are impacted?", ["ShoppingCartFeatureDependencies.kt", "FoodMenuFeatureDependencies.kt", "OrderTypeSwitcherFeatureDependencies.kt"], ["StateAnalyzer"]),
    Task("6", "Test Coverage", "Find the state-changing checkout payment functions and their nearby unit tests.", ["WhenChargePayment.kt", "CheckoutOrderProcessingService.kt"], ["chargePayment"]),
    Task("7", "Deprecation Hunt", "Find all deprecated code pointing to setupAppStateForNewOrder.", ["CheckoutService.kt"], ["setupAppStateForNewOrder"])
]

def estimate_tokens(text: str) -> int:
    return len(text) // 4

def run_vanilla(task: Task):
    start = time.perf_counter()
    pattern = "|".join(task.symbols)
    proc = subprocess.run(["rg", "-l", "--glob", "*.kt", pattern, str(DODO_ROOT)], capture_output=True, text=True)
    elapsed = (time.perf_counter() - start) * 1000
    hit = any(any(e in line for e in task.expected) for line in proc.stdout.splitlines())
    return {"hit": hit, "latency": elapsed, "tokens": estimate_tokens(proc.stdout)}

def run_ast_index(task: Task):
    start = time.perf_counter()
    hit = False
    tokens = 0
    for symbol in task.symbols:
        proc = subprocess.run(["ast-index", "symbol", symbol, "--format", "json"], cwd=DODO_ROOT, capture_output=True, text=True)
        tokens += estimate_tokens(proc.stdout)
        try:
            data = json.loads(proc.stdout)
            for row in data:
                path = row.get("path") or row.get("file_path", "")
                if any(e in path for e in task.expected):
                    hit = True
        except:
            if any(e in proc.stdout for e in task.expected):
                hit = True
    elapsed = (time.perf_counter() - start) * 1000
    return {"hit": hit, "latency": elapsed, "tokens": tokens}

def run_rag(task: Task):
    import sys
    sys.path.append(str(Path.cwd() / "src"))
    import asyncio
    from rag.agents.retrieval import plan_search
    from rag.agents.repo_agent import build_repo_agent_plan
    
    start = time.perf_counter()
    
    # 1. Run the local LLM planner
    async def _plan():
        return await plan_search(task.prompt)
    planner = asyncio.run(_plan())
    plan = build_repo_agent_plan(task.prompt, planner)
    
    token = Path.home().joinpath(".rag/token").read_text().strip()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    tokens = 0
    hit = False
    
    # 2. Try precise resolution first
    if plan.symbols:
        payload = json.dumps({"repo": "dodo", "symbols": plan.symbols, "definitions_limit": 5, "usages_limit": 5}).encode()
        req = urllib.request.Request(f"{RAG_URL}/resolve", data=payload, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                paths = [s.get("file_path", "") for s in data.get("definitions", []) + data.get("usages", [])]
                if any(any(p.endswith(e) for e in task.expected) for p in paths):
                    hit = True
        except:
            pass

    # 3. Fallback to Context Pack
    payload = json.dumps({
        "query": plan.context_query, 
        "repo": "dodo", 
        "use_ast_index": True, 
        "strategy": plan.planner.strategy
    }).encode()
    req = urllib.request.Request(f"{RAG_URL}/context-pack", data=payload, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            paths = [s.get("file_path", "") for s in data.get("slices", [])]
            if any(any(p.endswith(e) for e in task.expected) for p in paths):
                hit = True
            tokens += data.get("total_source_tokens", 0)
    except:
        pass
        
    elapsed = (time.perf_counter() - start) * 1000
    return {"hit": hit, "tokens": tokens, "latency": elapsed}

def run_graphify(task: Task):
    start = time.perf_counter()
    output = ""
    hit = False
    if task.id in ["3", "4", "5"] and len(task.symbols) >= 2:
        proc = subprocess.run(["graphify", "path", task.symbols[0], task.symbols[1], "--graph", str(GRAPH_PATH)], capture_output=True, text=True)
        output = proc.stdout
        hit = any(e.lower() in output.lower() for e in task.expected)
    
    if not hit:
        proc = subprocess.run(["graphify", "query", task.prompt, "--graph", str(GRAPH_PATH), "--budget", "2000"], capture_output=True, text=True)
        output += proc.stdout
        hit = any(e.lower() in output.lower() for e in task.expected)
        
    elapsed = (time.perf_counter() - start) * 1000
    return {"hit": hit, "tokens": estimate_tokens(output), "latency": elapsed}

def main():
    print("# Article Benchmark Data (Dodo Android Project)\n")
    print("| Task | Tool | Hit | Tokens | Latency (ms) |")
    print("| --- | --- | --- | --- | --- |")
    
    for t in TASKS:
        print(f"\nRunning Task {t.id}: {t.name}...", flush=True)
        v = run_vanilla(t)
        print(f"| {t.id}. {t.name} | Vanilla (ripgrep) | {v['hit']} | {v['tokens']} | {v['latency']:.1f} |")
        
        a = run_ast_index(t)
        print(f"| {t.id}. {t.name} | ast-index | {a['hit']} | {a['tokens']} | {a['latency']:.1f} |")
        
        r = run_rag(t)
        print(f"| {t.id}. {t.name} | RAG + AST | {r['hit']} | {r['tokens']} | {r['latency']:.1f} |")
        
        g = run_graphify(t)
        print(f"| {t.id}. {t.name} | Graphify | {g['hit']} | {g['tokens']} | {g['latency']:.1f} |")

if __name__ == "__main__":
    main()
