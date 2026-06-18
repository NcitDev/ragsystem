import json
import subprocess
import time
import os
from pathlib import Path
from dataclasses import dataclass

PROJECT_ROOT = Path("/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android")
GRAPH_PATH = PROJECT_ROOT / "signal_graph_out" / "graphify-out" / "graph.json"

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

def run_vanilla(task: Task, use_headroom=False):
    start = time.perf_counter()
    pattern = "|".join(task.symbols)
    proc = subprocess.run(["rg", "-l", "--glob", "*.kt", "--glob", "*.java", pattern, str(PROJECT_ROOT)], capture_output=True, text=True)
    files = [f for f in proc.stdout.splitlines() if not any(x in f for x in ["/build/", "/bin/"])]
    hit = any(any(e in f for e in task.expected_files) for f in files)
    latency = (time.perf_counter() - start) * 1000
    # Simulate turn counting logic
    turns = 1 + min(len(files), 3) 
    return {"hit": hit, "turns": turns, "latency": latency}

def run_rag_full(task: Task):
    start = time.perf_counter()
    cmd = ["uv", "run", "python", "-m", "rag", "repo-agent", task.prompt, "--repo", "signal", "--json", "--max-slices", "40"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    latency = (time.perf_counter() - start) * 1000
    hit = False
    tokens = 0
    try:
        data = json.loads(proc.stdout)
        slices = data.get("slices", [])
        # Check definitions and usage slices too for higher recall
        all_paths = [s['file_path'] for s in slices]
        if data.get("resolve"):
            all_paths += [d['file_path'] for d in data['resolve'].get('definition_slices', [])]
            all_paths += [u['file_path'] for u in data['resolve'].get('usage_slices', [])]
        
        hit = any(any(e in p for e in task.expected_files) for p in all_paths)
        tokens = data.get("total_source_tokens", 0)
    except: pass
    return {"hit": hit, "turns": 1, "tokens": tokens, "latency": latency}

def run_graphify_full(task: Task, use_headroom=False):
    start = time.perf_counter()
    env = {**os.environ, "GRAPHIFY_MAX_GRAPH_BYTES": "2GB", "GRAPHIFY_BACKEND": "gemini", "GRAPHIFY_MODEL": "gemini-3-flash-preview"}
    proc = subprocess.run(["graphify", "query", task.prompt, "--graph", str(GRAPH_PATH), "--budget", "3000"], capture_output=True, text=True, env=env)
    latency = (time.perf_counter() - start) * 1000
    hit = any(any(e.lower() in proc.stdout.lower() for e in task.expected_files) for p in [1])
    return {"hit": hit, "turns": 1, "latency": latency}

def main():
    print("# DEFINITIVE EFFICIENCY BENCHMARK (Signal-Android)")
    print("| Task | Tool | Hit | Turns | Latency (ms) |")
    print("| :--- | :--- | :---: | :---: | :--- |")
    
    for t in TASKS:
        v = run_vanilla(t)
        print(f"| {t.id}. {t.name} | Vanilla (grep+read) | {v['hit']} | {v['turns']} | {v['latency']:.1f} |")
        
        r = run_rag_full(t)
        print(f"| {t.id}. {t.name} | **RAG+AST+G3 (New)** | **{r['hit']}** | **{r['turns']}** | **{r['latency']:.1f}** |")
        
        g = run_graphify_full(t)
        print(f"| {t.id}. {t.name} | Graphify (Cloud) | {g['hit']} | {g['turns']} | {g['latency']:.1f} |")
        print("| | | | | |")

if __name__ == "__main__":
    main()
