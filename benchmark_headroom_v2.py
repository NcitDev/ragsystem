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
        # Headroom code compression
        # We use a custom budget to force compression
        result = compressor.compress(text, language=lang, token_budget=max(100, estimate_tokens(text) // 2))
        return result.compressed
    except:
        return text

def run_vanilla(task: Task, use_headroom=False):
    start = time.perf_counter()
    pattern = "|".join(task.symbols)
    proc = subprocess.run(["rg", "-l", "--glob", "*.kt", "--glob", "*.java", pattern, str(PROJECT_ROOT)], capture_output=True, text=True)
    files = proc.stdout.splitlines()
    
    total_text = ""
    for f in files[:3]:
        full_path = PROJECT_ROOT / f
        if full_path.exists():
            content = full_path.read_text(errors='replace')
            if use_headroom:
                content = compress_output(content, f)
            total_text += content

    latency = (time.perf_counter() - start) * 1000
    hit = any(task.expected_file in f for f in files)
    return {"hit": hit, "tokens": estimate_tokens(total_text), "latency": latency}

def run_ast(task: Task, use_headroom=False):
    start = time.perf_counter()
    proc = subprocess.run(["ast-index", "symbol", task.symbols[0], "--format", "json"], cwd=PROJECT_ROOT, capture_output=True, text=True)
    try:
        data = json.loads(proc.stdout)
    except:
        data = []
    
    total_text = ""
    for row in data[:3]:
        path = row.get("path") or ""
        # Simulate fetching the code for the symbol
        content = row.get("signature", "") # Simplified for AST baseline
        if use_headroom:
            content = compress_output(content, path)
        total_text += content

    hit = any(task.expected_file in (row.get("path") or "") for row in data)
    latency = (time.perf_counter() - start) * 1000
    return {"hit": hit, "tokens": estimate_tokens(total_text), "latency": latency}

def run_rag(task: Task, use_headroom=False):
    import sys
    sys.path.append("/Users/nikitaf/production/ragsystem/src")
    import asyncio
    from rag.agents.retrieval import plan_search
    from rag.agents.repo_agent import build_repo_agent_plan
    
    start = time.perf_counter()
    try:
        planner = asyncio.run(plan_search(task.prompt))
        plan = build_repo_agent_plan(task.prompt, planner)
    except: return {"hit": False, "tokens": 0, "latency": 0}
    
    token = Path.home().joinpath(".rag/token").read_text().strip()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    hit = False
    total_text = ""
    
    # Combined RAG + AST Logic
    all_symbols = list(set(plan.symbols + task.symbols))
    payload = json.dumps({"repo": "signal", "symbols": all_symbols}).encode()
    req = urllib.request.Request(f"{RAG_URL}/resolve", data=payload, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            for d in data.get('definitions', []):
                if task.expected_file in d['file_path']: hit = True
                code = d['code']
                if use_headroom: code = compress_output(code, d['file_path'])
                total_text += code
    except: pass

    if not hit:
        payload = json.dumps({"repo": "signal", "query": plan.context_query, "use_ast_index": True}).encode()
        req = urllib.request.Request(f"{RAG_URL}/context-pack", data=payload, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode())
                for s in data.get('slices', []):
                    if task.expected_file in s['file_path']: hit = True
                    code = s['code']
                    if use_headroom: code = compress_output(code, s['file_path'])
                    total_text += code
        except: pass
    
    latency = (time.perf_counter() - start) * 1000
    return {"hit": hit, "tokens": estimate_tokens(total_text), "latency": latency}

def run_graphify(task: Task, use_headroom=False):
    start = time.perf_counter()
    env = {**os.environ, "GRAPHIFY_MAX_GRAPH_BYTES": "2GB", "GRAPHIFY_BACKEND": "gemini", "GRAPHIFY_MODEL": "gemini-3-flash-preview"}
    proc = subprocess.run(["graphify", "query", task.prompt, "--graph", str(GRAPH_PATH), "--budget", "2000"], capture_output=True, text=True, env=env)
    
    output = proc.stdout
    if use_headroom:
        output = compress_output(output)
        
    latency = (time.perf_counter() - start) * 1000
    hit = task.expected_file.lower() in proc.stdout.lower()
    return {"hit": hit, "tokens": estimate_tokens(output), "latency": latency}

def main():
    print("# Multi-Instrument Headroom Efficiency Benchmark (Forced Compression)\n")
    print("| Task | Tool | Hit | Tokens (Normal) | Tokens (Headroom) | Savings |")
    print("| --- | --- | --- | --- | --- | --- |")
    
    for t in TASKS:
        v_norm = run_vanilla(t, False)
        v_head = run_vanilla(t, True)
        savings_v = (1 - v_head['tokens']/v_norm['tokens'])*100 if v_norm['tokens'] > 0 else 0
        print(f"| {t.id}. {t.name} | Vanilla | {v_norm['hit']} | {v_norm['tokens']} | {v_head['tokens']} | {savings_v:.1f}% |")
        
        a_norm = run_ast(t, False)
        a_head = run_ast(t, True)
        savings_a = (1 - a_head['tokens']/a_norm['tokens'])*100 if a_norm['tokens'] > 0 else 0
        print(f"| {t.id}. {t.name} | AST-Index | {a_norm['hit']} | {a_norm['tokens']} | {a_head['tokens']} | {savings_a:.1f}% |")

        r_norm = run_rag(t, False)
        r_head = run_rag(t, True)
        savings_r = (1 - r_head['tokens']/r_norm['tokens'])*100 if r_norm['tokens'] > 0 else 0
        print(f"| {t.id}. {t.name} | **RAG+AST** | **{r_norm['hit']}** | **{r_norm['tokens']}** | **{r_head['tokens']}** | **{savings_r:.1f}%** |")
        
        g_norm = run_graphify(t, False)
        g_head = run_graphify(t, True)
        savings_g = (1 - g_head['tokens']/g_norm['tokens'])*100 if g_norm['tokens'] > 0 else 0
        print(f"| {t.id}. {t.name} | Graphify | {g_norm['hit']} | {g_norm['tokens']} | {g_head['tokens']} | {savings_g:.1f}% |")
        print("| | | | | | |")

if __name__ == "__main__":
    main()
