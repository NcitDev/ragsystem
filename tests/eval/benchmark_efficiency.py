#!/usr/bin/env python3
"""High-fidelity token efficiency benchmark ported from Graphify's own standards."""

import json
import subprocess
import time
from pathlib import Path

# Project-specific paths
PROJECT_ROOT = Path("/Users/nikitaf/development/projects/dodo-mobile-android/project")
GRAPH_PATH = PROJECT_ROOT / "full_graph_out" / "graphify-out" / "graph.json"

# Ported from graphify/benchmark.py
def estimate_tokens(text: str) -> int:
    return len(text) // 4

def get_corpus_size(project_root: Path) -> int:
    total_chars = 0
    for fp in project_root.glob("**/*.kt"):
        if "build/" in str(fp) or "graphify-out" in str(fp): continue
        try:
            total_chars += fp.stat().st_size
        except: pass
    for fp in project_root.glob("**/*.java"):
        if "build/" in str(fp) or "graphify-out" in str(fp): continue
        try:
            total_chars += fp.stat().st_size
        except: pass
    return total_chars // 4

# Dodo Navigation Tasks as Benchmark Questions
QUESTIONS = [
    "Find suspend/async checkout functions related to waiting for paid orders.",
    "Trace ifSuccess_andOrderStateIsAlmostOk_shouldSetupAppStateForNewOrder.",
    "Find deprecated code pointing to CheckoutService::setupAppStateForNewOrder.",
    "Verify analytics tracking for successful payment completion.",
    "Find profile locale list dependency interface and owning module.",
    "Find code-only deferred-time symbols to review for rename.",
    "Explain how checkout state is coordinated across context/order and context/core.",
    "Find state-changing checkout payment functions and nearby tests.",
    "Find actual paid order response VO/model names and call sites.",
    "Plan smallest patch so paid order handling resets state before analytics."
]

def run_graphify_query(question: str) -> int:
    """Measure tokens returned by graphify query."""
    proc = subprocess.run(
        ["graphify", "query", question, "--graph", str(GRAPH_PATH), "--budget", "2000"],
        capture_output=True, text=True
    )
    return estimate_tokens(proc.stdout)

def run_rag_tokens(question: str) -> int:
    """Mock/Call RAG server to get total_source_tokens."""
    import urllib.request
    token_path = Path.home() / ".rag" / "token"
    token = token_path.read_text().strip() if token_path.exists() else ""
    
    payload = json.dumps({
        "query": question,
        "repo": "dodo",
        "max_source_tokens": 6000,
        "use_ast_index": True
    }).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:7890/context-pack",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return data.get("total_source_tokens", 0)
    except Exception as e:
        print(f"RAG Error: {e}")
        return 0

def main():
    print("Calculating Naive Corpus Size...")
    corpus_tokens = get_corpus_size(PROJECT_ROOT)
    print(f"Corpus Size: ~{corpus_tokens:,} tokens")
    
    results = []
    for q in QUESTIONS:
        print(f"Benchmarking: {q[:50]}...")
        g_tokens = run_graphify_query(q)
        rag_tokens = run_rag_tokens(q)
        results.append({
            "question": q,
            "graphify": g_tokens,
            "rag": rag_tokens
        })
    
    print("\n=== Token Efficiency Benchmark (Dodo Android) ===")
    print(f"{'Method':<15} | {'Avg Tokens':<12} | {'Reduction Ratio':<15}")
    print("-" * 50)
    
    avg_g = sum(r["graphify"] for r in results) / len(results)
    avg_rag = sum(r["rag"] for r in results) / len(results)
    
    print(f"{'Naive Corpus':<15} | {corpus_tokens:<12,} | 1.0x")
    print(f"{'Graphify':<15} | {avg_g:<12.0f} | {corpus_tokens/avg_g:>6.1f}x fewer")
    print(f"{'RAG (+AST)':<15} | {avg_rag:<12.0f} | {corpus_tokens/avg_rag:>6.1f}x fewer")
    
    print("\nConclusion:")
    if avg_g < avg_rag:
        print(f"Graphify is {avg_rag/avg_g:.1f}x more token-efficient than RAG for these queries.")
    else:
        print(f"RAG is {avg_g/avg_rag:.1f}x more token-efficient than Graphify for these queries.")

if __name__ == "__main__":
    main()
