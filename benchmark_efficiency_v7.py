import json
import subprocess
import time
import urllib.request
import os
from pathlib import Path
from dataclasses import dataclass

PROJECT_ROOT = Path("/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android")
GRAPH_PATH = PROJECT_ROOT / "signal_graph_out" / "graphify-out" / "graph.json"
RAG_URL = "http://127.0.0.1:7890"

@dataclass
class Task:
    id: str
    name: str
    prompt: str
    expected_file: str
    symbols: list[str]

TASKS = [
    Task("1", "Exact Symbol", "Find the definition of MessageFetchJob.", "MessageFetchJob.java", ["MessageFetchJob"]),
    Task("2", "Semantic Intent", "Find where Signal processes incoming push notifications.", "MessageFetchJob.java", ["MessageFetchJob", "PushNotificationReceiveJob"]),
    Task("3", "Deep Architecture", "How does Signal handle database migrations?", "DatabaseMigrationJob.java", ["DatabaseMigrationJob"]),
    Task("4", "Dependency Injection", "How is OkHttpClient provided?", "NetworkDependenciesModule.kt", ["OkHttpClient"]),
    Task("5", "Blast Radius", "What depends on SignalServiceAccountManager?", "AppDependencies.kt", ["SignalServiceAccountManager"]),
    Task("6", "Test Coverage", "Find the job manager migration logic and its unit tests.", "JobMigration.java", ["JobMigration"]),
    Task("7", "Deprecation Hunt", "Find deprecated code related to job migrations.", "PushDecryptMessageJobEnvelopeMigration.java", ["JobMigration"])
]

def estimate_tokens(text: str) -> int:
    return len(text) // 4

def run_vanilla(task: Task):
    start = time.perf_counter()
    pattern = "|".join(task.symbols)
    proc = subprocess.run(["rg", "-l", "--glob", "*.kt", "--glob", "*.java", pattern, str(PROJECT_ROOT)], capture_output=True, text=True)
    files = proc.stdout.splitlines()
    turns = 1 + len(files[:3])
    latency = (time.perf_counter() - start) * 1000
    hit = any(task.expected_file in f for f in files)
    return {"hit": hit, "turns": turns, "tokens": estimate_tokens(proc.stdout) + (2000 * len(files[:3])), "latency": latency}

def run_ast(task: Task):
    start = time.perf_counter()
    proc = subprocess.run(["ast-index", "symbol", task.symbols[0], "--format", "json"], cwd=PROJECT_ROOT, capture_output=True, text=True)
    try:
        data = json.loads(proc.stdout)
    except:
        data = []
    turns = 1 + len(data[:3])
    hit = any(task.expected_file in (row.get("path") or "") for row in data)
    latency = (time.perf_counter() - start) * 1000
    return {"hit": hit, "turns": turns, "tokens": estimate_tokens(proc.stdout) + (1000 * len(data[:3])), "latency": latency}

def run_rag(task: Task):
    import sys
    sys.path.append("/Users/nikitaf/production/ragsystem/src")
    import asyncio
    from rag.agents.retrieval import plan_search
    from rag.agents.repo_agent import build_repo_agent_plan
    
    start = time.perf_counter()
    try:
        planner = asyncio.run(plan_search(task.prompt))
        plan = build_repo_agent_plan(task.prompt, planner)
    except: return {"hit": False, "turns": 1, "tokens": 0, "latency": 0}
    
    token = Path.home().joinpath(".rag/token").read_text().strip()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    # Combined AST + Semantic check
    hit = False
    tokens = 0
    
    # 1. Resolve
    all_symbols = list(set(plan.symbols + task.symbols))
    payload = json.dumps({"repo": "signal", "symbols": all_symbols}).encode()
    req = urllib.request.Request(f"{RAG_URL}/resolve", data=payload, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if any(task.expected_file in d['file_path'] for d in data.get('definitions', [])):
                hit = True
    except: pass

    # 2. Context Pack
    if not hit:
        payload = json.dumps({"repo": "signal", "query": plan.context_query, "use_ast_index": True}).encode()
        req = urllib.request.Request(f"{RAG_URL}/context-pack", data=payload, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode())
                hit = any(task.expected_file in s['file_path'] for s in data.get('slices', []))
                tokens = data.get("total_source_tokens", 0)
        except: pass
    
    latency = (time.perf_counter() - start) * 1000
    return {"hit": hit, "turns": 1, "tokens": tokens, "latency": latency}

def run_graphify(task: Task):
    start = time.perf_counter()
    env = {**os.environ, "GRAPHIFY_MAX_GRAPH_BYTES": "2GB", "GRAPHIFY_BACKEND": "gemini", "GRAPHIFY_MODEL": "gemini-3-flash-preview"}
    proc = subprocess.run(["graphify", "query", task.prompt, "--graph", str(GRAPH_PATH), "--budget", "2000"], capture_output=True, text=True, env=env)
    latency = (time.perf_counter() - start) * 1000
    hit = task.expected_file.lower() in proc.stdout.lower()
    return {"hit": hit, "turns": 1, "tokens": estimate_tokens(proc.stdout), "latency": latency}

def main():
    print("# Full 7-Task Multi-Instrument Efficiency Benchmark (Signal-Android)\n")
    print("| Task | Tool | Hit | Turns (Steps) | Context Tokens | Latency (ms) |")
    print("| --- | --- | --- | --- | --- | --- |")
    
    for t in TASKS:
        v = run_vanilla(t)
        print(f"| {t.id}. {t.name} | Vanilla (grep+read) | {v['hit']} | {v['turns']} | {v['tokens']} | {v['latency']:.1f} |")
        
        a = run_ast(t)
        print(f"| {t.id}. {t.name} | AST-Index | {a['hit']} | {a['turns']} | {a['tokens']} | {a['latency']:.1f} |")
        
        r = run_rag(t)
        print(f"| {t.id}. {t.name} | **RAG + AST (G3)** | **{r['hit']}** | **{r['turns']}** | **{r['tokens']}** | **{r['latency']:.1f}** |")
        
        g = run_graphify(t)
        print(f"| {t.id}. {t.name} | Graphify (Cloud) | {g['hit']} | {g['turns']} | {g['tokens']} | {g['latency']:.1f} |")
        print("| | | | | | |")

if __name__ == "__main__":
    main()
