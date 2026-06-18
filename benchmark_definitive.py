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
    # Fixed Task 5: AppDependencies is where it is defined/provided; dependents are elsewhere.
    Task("5", "Blast Radius", "What depends on SignalServiceAccountManager? Find calling screens or helpers.", ["CallQualityScreens.kt", "HelpScreenEvents.kt", "RegistrationService.java"], ["SignalServiceAccountManager"]),
    # Fixed Task 6: Better coverage of migration tests.
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
    files = proc.stdout.splitlines()
    total_text = ""
    for f in files[:8]:
        full_path = PROJECT_ROOT / f
        if full_path.exists():
            content = full_path.read_text(errors='replace')
            if use_headroom: content = compress_output(content, f)
            total_text += content
    latency = (time.perf_counter() - start) * 1000
    hit = any(any(e in f for e in task.expected_files) for f in files)
    return {"hit": hit, "tokens": estimate_tokens(total_text), "latency": latency}

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
    return {"hit": hit, "tokens": estimate_tokens(total_text), "latency": latency}

def run_rag(task: Task, use_headroom=False, deep_retrieval=False):
    # This calls our REFACTORED repo-agent command which now has LLM Pruning built-in
    start = time.perf_counter()
    
    # We use the CLI to trigger the real pipeline: Planner -> Retrieval -> LLM Pruning
    # The --json flag gives us the final context tokens
    cmd = ["uv", "run", "python", "-m", "rag", "repo-agent", task.prompt, "--repo", "signal", "--json"]
    if deep_retrieval:
        cmd += ["--max-slices", "40", "--max-source-tokens", "15000"]
    
    proc = subprocess.run(cmd, capture_output=True, text=True)
    try:
        data = json.loads(proc.stdout)
        slices = data.get("slices", [])
        hit = any(any(e in s['file_path'] for e in task.expected_files) for s in slices)
        tokens = data.get("total_source_tokens", 0)
    except:
        return {"hit": False, "tokens": 0, "latency": 0}
    
    latency = (time.perf_counter() - start) * 1000
    return {"hit": hit, "tokens": tokens, "latency": latency}

def run_graphify(task: Task, use_headroom=False):
    start = time.perf_counter()
    env = {**os.environ, "GRAPHIFY_MAX_GRAPH_BYTES": "2GB", "GRAPHIFY_BACKEND": "gemini", "GRAPHIFY_MODEL": "gemini-3-flash-preview"}
    proc = subprocess.run(["graphify", "query", task.prompt, "--graph", str(GRAPH_PATH), "--budget", "3000"], capture_output=True, text=True, env=env)
    output = proc.stdout
    if use_headroom: output = compress_output(output)
    latency = (time.perf_counter() - start) * 1000
    hit = any(e.lower() in proc.stdout.lower() for e in task.expected_files)
    return {"hit": hit, "tokens": estimate_tokens(output), "latency": latency}

def main():
    print("# Final Multi-Instrument Comparison (Signal-Android)")
    print("## Benchmarking Vanilla, AST-Index, RAG+AST (Deep+Pruning), and Graphify\n")
    print("| Task | Tool | Hit | Tokens | Latency (ms) |")
    print("| --- | --- | --- | --- | --- |")
    
    for t in TASKS:
        # Vanilla (Normal)
        v_n = run_vanilla(t, False)
        print(f"| {t.id}. {t.name} | Vanilla (Baseline) | {v_n['hit']} | {v_n['tokens']} | {v_n['latency']:.1f} |")
        
        # AST (Normal)
        a_n = run_ast(t, False)
        print(f"| {t.id}. {t.name} | AST-Index | {a_n['hit']} | {a_n['tokens']} | {a_n['latency']:.1f} |")
        
        # RAG+AST+H (New Architecture: Deep Retrieval + Gemini 3 Pruning + Headroom)
        r_h = run_rag(t, use_headroom=True, deep_retrieval=True)
        print(f"| {t.id}. {t.name} | **RAG+AST+H (Deep)** | **{r_h['hit']}** | **{r_h['tokens']}** | **{r_h['latency']:.1f}** |")
        
        # Graphify
        g_n = run_graphify(t, False)
        print(f"| {t.id}. {t.name} | Graphify (Normal) | {g_n['hit']} | {g_n['tokens']} | {g_n['latency']:.1f} |")
        
        # Graphify + Headroom
        g_h = run_graphify(t, True)
        print(f"| {t.id}. {t.name} | Graphify + Headroom | {g_h['hit']} | {g_h['tokens']} | {g_h['latency']:.1f} |")
        print("| | | | | |")

if __name__ == "__main__":
    main()
