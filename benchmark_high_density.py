import json
import subprocess
import time
import urllib.request
import os
from pathlib import Path
from dataclasses import dataclass
from headroom.transforms.code_compressor import CodeAwareCompressor, CodeCompressorConfig, DocstringMode

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

# Initialize Headroom Compressor
config = CodeCompressorConfig(docstring_mode=DocstringMode.REMOVE)
compressor = CodeAwareCompressor(config=config)

def estimate_tokens(text: str) -> int:
    return len(text) // 4

def compress_output(text: str, file_path: str = "") -> str:
    lang = "java"
    if file_path.endswith(".kt"): lang = "kotlin"
    elif file_path.endswith(".py"): lang = "python"
    
    try:
        # Use target_rate to keep only 10% of the code
        result = compressor.compress(text, language=lang)
        return result.compressed
    except:
        return text

def run_vanilla(task: Task):
    start = time.perf_counter()
    pattern = "|".join(task.symbols)
    proc = subprocess.run(["rg", "-l", "--glob", "*.kt", "--glob", "*.java", pattern, str(PROJECT_ROOT)], capture_output=True, text=True)
    files = proc.stdout.splitlines()
    
    total_text = ""
    # With Headroom, we can afford to read MORE files in fewer turns
    for f in files[:10]:
        full_path = PROJECT_ROOT / f
        if full_path.exists():
            content = full_path.read_text(errors='replace')
            total_text += compress_output(content, f)

    latency = (time.perf_counter() - start) * 1000
    hit = any(task.expected_file in f for f in files)
    # Turns = 1 search + 1 multi-file compressed read
    return {"hit": hit, "turns": 2, "tokens": estimate_tokens(total_text), "latency": latency}

def run_ast(task: Task):
    start = time.perf_counter()
    proc = subprocess.run(["ast-index", "symbol", task.symbols[0], "--format", "json"], cwd=PROJECT_ROOT, capture_output=True, text=True)
    try:
        data = json.loads(proc.stdout)
    except:
        data = []
    
    total_text = ""
    for row in data[:10]:
        path = row.get("path") or ""
        content = row.get("signature", "")
        total_text += compress_output(content, path)

    hit = any(task.expected_file in (row.get("path") or "") for row in data)
    latency = (time.perf_counter() - start) * 1000
    # Turns = 1 index call + 1 multi-read
    return {"hit": hit, "turns": 2, "tokens": estimate_tokens(total_text), "latency": latency}

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
    
    hit = False
    total_text = ""
    
    # 1. Resolve (AST)
    all_symbols = list(set(plan.symbols + task.symbols))
    payload = json.dumps({"repo": "signal", "symbols": all_symbols, "definitions_limit": 20}).encode()
    req = urllib.request.Request(f"{RAG_URL}/resolve", data=payload, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            for d in data.get('definitions', []):
                if task.expected_file in d['file_path']: hit = True
                total_text += compress_output(d['code'], d['file_path'])
    except: pass

    # 2. Context Pack (Semantic) - DEEP RETRIEVAL (40 slices)
    payload = json.dumps({
        "query": plan.context_query, 
        "repo": "signal", 
        "use_ast_index": True,
        "max_slices": 40,
        "max_source_tokens": 15000
    }).encode()
    req = urllib.request.Request(f"{RAG_URL}/context-pack", data=payload, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            for s in data.get('slices', []):
                if task.expected_file in s['file_path']: hit = True
                total_text += compress_output(s['code'], s['file_path'])
    except: pass
    
    latency = (time.perf_counter() - start) * 1000
    return {"hit": hit, "turns": 1, "tokens": estimate_tokens(total_text), "latency": latency}

def run_graphify(task: Task):
    start = time.perf_counter()
    env = {**os.environ, "GRAPHIFY_MAX_GRAPH_BYTES": "2GB", "GRAPHIFY_BACKEND": "gemini", "GRAPHIFY_MODEL": "gemini-3-flash-preview"}
    # Deep budget for Graphify (4000 tokens)
    proc = subprocess.run(["graphify", "query", task.prompt, "--graph", str(GRAPH_PATH), "--budget", "4000"], capture_output=True, text=True, env=env)
    
    output = compress_output(proc.stdout)
    latency = (time.perf_counter() - start) * 1000
    hit = task.expected_file.lower() in proc.stdout.lower()
    return {"hit": hit, "turns": 1, "tokens": estimate_tokens(output), "latency": latency}

def main():
    print("# High-Density Multi-Instrument Efficiency Benchmark (+Headroom)\n")
    print("| Task | Tool | Hit | Turns | Context Tokens | Latency (ms) |")
    print("| --- | --- | --- | --- | --- | --- |")
    
    for t in TASKS:
        v = run_vanilla(t)
        print(f"| {t.id}. {t.name} | Vanilla+H | {v['hit']} | {v['turns']} | {v['tokens']} | {v['latency']:.1f} |")
        
        a = run_ast(t)
        print(f"| {t.id}. {t.name} | AST-Index+H | {a['hit']} | {a['turns']} | {a['tokens']} | {a['latency']:.1f} |")
        
        r = run_rag(t)
        print(f"| {t.id}. {t.name} | **RAG+AST+H** | **{r['hit']}** | **{r['turns']}** | **{r['tokens']}** | **{r['latency']:.1f}** |")
        
        g = run_graphify(t)
        print(f"| {t.id}. {t.name} | Graphify+H | {g['hit']} | {g['turns']} | {g['tokens']} | {g['latency']:.1f} |")
        print("| | | | | | |")

if __name__ == "__main__":
    main()
