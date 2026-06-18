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
    expected_files: list[str]
    symbols: list[str]

TASKS = [
    Task("1", "Exact Symbol", "Find the definition of MessageFetchJob.", ["MessageFetchJob.java"], ["MessageFetchJob"]),
    Task("2", "Semantic Intent", "Find where Signal processes incoming push notifications.", ["MessageFetchJob.java", "PushNotificationReceiveJob.java", "FcmFetchManager.kt"], ["MessageFetchJob", "PushNotificationReceiveJob"]),
    Task("3", "Deep Architecture", "How does Signal handle database migrations?", ["DatabaseMigrationJob.java", "DatabaseMigrations.java"], ["DatabaseMigrationJob"]),
    Task("4", "Dependency Injection", "How is OkHttpClient provided?", ["NetworkDependenciesModule.kt", "AppDependencies.kt"], ["OkHttpClient"]),
    Task("5", "Blast Radius", "What depends on SignalServiceAccountManager? Find calling screens or helpers.", ["CallQualityScreens.kt", "HelpScreenEvents.kt", "RegistrationService.java"], ["SignalServiceAccountManager"]),
    Task("6", "Test Coverage", "Find job migration logic and its unit tests.", ["JobMigration.java", "JobMigrationTest.java", "DatabaseMigrationJob.java"], ["JobMigration"]),
    Task("7", "Deprecation Hunt", "Find deprecated code related to job migrations.", ["PushDecryptMessageJobEnvelopeMigration.java", "DatabaseMigrationJob.java"], ["JobMigration"])
]

# Initialize Headroom
config = CodeCompressorConfig(docstring_mode=DocstringMode.REMOVE)
compressor = CodeAwareCompressor(config=config)

def estimate_tokens(text: str) -> int:
    return len(text) // 4

def compress_output(text: str, file_path: str = "") -> str:
    lang = "java"
    if file_path.endswith(".kt"): lang = "kotlin"
    elif file_path.endswith(".py"): lang = "python"
    try:
        result = compressor.compress(text, language=lang)
        return result.compressed
    except:
        return text

def run_vanilla(task: Task, use_headroom=False):
    start = time.perf_counter()
    pattern = "|".join(task.symbols)
    proc = subprocess.run(["rg", "-l", "--glob", "*.kt", "--glob", "*.java", pattern, str(PROJECT_ROOT)], capture_output=True, text=True)
    files = [f for f in proc.stdout.splitlines() if not any(x in f for x in ["/build/", "/bin/"])]
    
    total_text = ""
    for f in files[:8]:
        full_path = PROJECT_ROOT / f
        if full_path.exists():
            content = full_path.read_text(errors='replace')
            if use_headroom: content = compress_output(content, f)
            total_text += content

    hit = any(any(e in f for e in task.expected_files) for f in files)
    latency = (time.perf_counter() - start) * 1000
    turns = 1 + min(len(files), 3) 
    return {"hit": hit, "turns": turns, "tokens": estimate_tokens(total_text), "latency": latency}

def run_ast(task: Task, use_headroom=False):
    start = time.perf_counter()
    proc = subprocess.run(["ast-index", "symbol", task.symbols[0], "--format", "json"], cwd=PROJECT_ROOT, capture_output=True, text=True)
    try: data = json.loads(proc.stdout)
    except: data = []
    
    total_text = ""
    for row in data[:8]:
        path = row.get("path") or ""
        content = row.get("signature", "")
        if use_headroom: content = compress_output(content, path)
        total_text += content

    hit = any(any(e in (row.get("path") or "") for e in task.expected_files) for row in data)
    latency = (time.perf_counter() - start) * 1000
    turns = 1 + min(len(data), 3)
    return {"hit": hit, "turns": turns, "tokens": estimate_tokens(total_text), "latency": latency}

def run_rag_full(task: Task, use_headroom=False):
    start = time.perf_counter()
    
    # We call standard context-pack for no headroom, and repo-agent for headroom (pruning+deep)
    if not use_headroom:
        # Standard RAG
        token = Path.home().joinpath(".rag/token").read_text().strip()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = json.dumps({"repo": "signal", "query": task.prompt, "use_ast_index": True}).encode()
        req = urllib.request.Request(f"{RAG_URL}/context-pack", data=payload, headers=headers)
        hit = False
        tokens = 0
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode())
                slices = data.get("slices", [])
                hit = any(any(e in s['file_path'] for e in task.expected_files) for s in slices)
                tokens = data.get("total_source_tokens", 0)
        except: pass
        latency = (time.perf_counter() - start) * 1000
        return {"hit": hit, "turns": 1, "tokens": tokens, "latency": latency}
    else:
        # Deep RAG with LLM Pruning (acts as our Headroom-compressed equivalent here since repo-agent compresses implicitly or limits output)
        # To strictly use the Headroom function on top of RAG output, we will fetch raw RAG and compress it.
        # Wait, the prompt asks for ALL tools with and without Headroom. 
        # Let's fetch RAG deep, then optionally apply headroom locally.
        cmd = ["uv", "run", "python", "-m", "rag", "repo-agent", task.prompt, "--repo", "signal", "--json", "--max-slices", "40"]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        hit = False
        total_text = ""
        try:
            data = json.loads(proc.stdout)
            slices = data.get("slices", [])
            for s in slices:
                code = s.get("code", "")
                path = s.get("file_path", "")
                if any(e in path for e in task.expected_files): hit = True
                if use_headroom: code = compress_output(code, path)
                total_text += code
        except: pass
        latency = (time.perf_counter() - start) * 1000
        return {"hit": hit, "turns": 1, "tokens": estimate_tokens(total_text), "latency": latency}

def run_graphify_full(task: Task, use_headroom=False):
    start = time.perf_counter()
    env = {**os.environ, "GRAPHIFY_MAX_GRAPH_BYTES": "2GB", "GRAPHIFY_BACKEND": "gemini", "GRAPHIFY_MODEL": "gemini-3-flash-preview"}
    proc = subprocess.run(["graphify", "query", task.prompt, "--graph", str(GRAPH_PATH), "--budget", "3000"], capture_output=True, text=True, env=env)
    output = proc.stdout
    if use_headroom: output = compress_output(output)
    latency = (time.perf_counter() - start) * 1000
    hit = any(any(e.lower() in proc.stdout.lower() for e in task.expected_files) for p in [1])
    return {"hit": hit, "turns": 1, "tokens": estimate_tokens(output), "latency": latency}

def main():
    print("# Full Exhaustive Benchmark (All 7 Tasks, All Tools, With/Without Headroom)")
    print("| Task | Tool | Hit | Turns | Tokens | Latency (ms) |")
    print("| :--- | :--- | :---: | :---: | :---: | :--- |")
    
    for t in TASKS:
        v_n = run_vanilla(t, False)
        print(f"| {t.id}. {t.name} | Vanilla | {v_n['hit']} | {v_n['turns']} | {v_n['tokens']} | {v_n['latency']:.1f} |")
        v_h = run_vanilla(t, True)
        print(f"| | Vanilla + Headroom | {v_h['hit']} | {v_h['turns']} | {v_h['tokens']} | {v_h['latency']:.1f} |")
        
        a_n = run_ast(t, False)
        print(f"| | AST-Index | {a_n['hit']} | {a_n['turns']} | {a_n['tokens']} | {a_n['latency']:.1f} |")
        a_h = run_ast(t, True)
        print(f"| | AST-Index + Headroom | {a_h['hit']} | {a_h['turns']} | {a_h['tokens']} | {a_h['latency']:.1f} |")
        
        r_n = run_rag_full(t, False)
        print(f"| | RAG+AST | {r_n['hit']} | {r_n['turns']} | {r_n['tokens']} | {r_n['latency']:.1f} |")
        r_h = run_rag_full(t, True)
        print(f"| | RAG+AST + Headroom | {r_h['hit']} | {r_h['turns']} | {r_h['tokens']} | {r_h['latency']:.1f} |")
        
        g_n = run_graphify_full(t, False)
        print(f"| | Graphify | {g_n['hit']} | {g_n['turns']} | {g_n['tokens']} | {g_n['latency']:.1f} |")
        g_h = run_graphify_full(t, True)
        print(f"| | Graphify + Headroom | {g_h['hit']} | {g_h['turns']} | {g_h['tokens']} | {g_h['latency']:.1f} |")
        print("| | | | | | |")

if __name__ == "__main__":
    main()
