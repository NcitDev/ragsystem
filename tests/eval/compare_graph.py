#!/usr/bin/env python3
"""Compare Graphify vs RAG (using CodeGraph + ast-index enrichment)."""

import json
import shutil
import subprocess
import time
import sys
from pathlib import Path

# Add src to path so we can import rag
sys.path.append(str(Path(__file__).parent.parent.parent / "src"))

from rag.core.graph import CodeGraph
from rag.core.chunker import chunk_code, ChunkType

def setup_test_repo(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    (path / "utils.py").write_text('''
def helper():
    """A helper function."""
    print("hello")

class Base:
    def method(self):
        print("base method")
''')
    (path / "main.py").write_text('''
from utils import helper, Base

def process():
    """Process something."""
    helper()

class Runner(Base):
    def run(self):
        process()
        self.method()

if __name__ == "__main__":
    Runner().run()
''')

def run_graphify(repo_path: Path):
    print(f"Running Graphify on {repo_path}...")
    start = time.perf_counter()
    subprocess.run(["graphify", "extract", str(repo_path), "--no-cluster"], check=True, capture_output=True)
    elapsed = time.perf_counter() - start
    
    graph_path = repo_path / "graphify-out" / "graph.json"
    with open(graph_path) as f:
        data = json.loads(f.read())
    
    return {
        "nodes": len(data["nodes"]),
        "edges": len(data["edges"]),
        "calls": sum(1 for e in data["edges"] if e["relation"] == "calls"),
        "latency_ms": elapsed * 1000
    }

def build_rag_graph(repo_path: Path):
    print(f"Building RAG CodeGraph for {repo_path}...")
    start = time.perf_counter()
    
    # 1. Rebuild ast-index
    subprocess.run(["ast-index", "rebuild"], cwd=repo_path, check=True, capture_output=True)
    
    # 2. Chunk all files
    all_chunks = []
    for fp in repo_path.glob("**/*.py"):
        if "graphify-out" in str(fp): continue
        rel = str(fp.relative_to(repo_path))
        content = fp.read_text()
        chunks = chunk_code(content, rel, "python")
        all_chunks.extend(chunks)
    
    # 3. Enrich with ast-index (simulating LSP enrichment for calls)
    enriched_payloads = []
    for chunk in all_chunks:
        payload = chunk.to_index_metadata()
        if chunk.chunk_type in (ChunkType.FUNCTION, ChunkType.METHOD):
            # Find callers
            cp = subprocess.run(["ast-index", "callers", chunk.name, "--format", "json"], 
                               cwd=repo_path, capture_output=True, text=True)
            # ast-index callers return a list of locations. 
            # We'll just count how many unique locations there are as 'called_by'
            try:
                # If json fails, we'll skip for this simple demo
                callers = json.loads(cp.stdout)
                payload["called_by"] = [f"{c['path']}:{c['line']}" for c in callers]
            except:
                pass
        
        # Simple import enrichment
        if chunk.chunk_type == ChunkType.FILE_SUMMARY:
            cp = subprocess.run(["ast-index", "imports", chunk.file_path], 
                               cwd=repo_path, capture_output=True, text=True)
            # Parse text output since json is flaky
            payload["imports"] = [line.strip() for line in cp.stdout.splitlines() if line.strip()]
            
        enriched_payloads.append(payload)
    
    # 4. Build CodeGraph
    graph = CodeGraph()
    graph.build_from_chunks(enriched_payloads)
    
    elapsed = time.perf_counter() - start
    stats = graph.stats()
    
    return {
        "nodes": stats["nodes"],
        "edges": stats["edges"],
        "calls": stats["edges"], # In CodeGraph, most edges are calls/imports
        "latency_ms": elapsed * 1000
    }

def main():
    repo_path = Path("temp_compare_repo")
    if repo_path.exists():
        shutil.rmtree(repo_path)
    
    setup_test_repo(repo_path)
    
    try:
        graphify_results = run_graphify(repo_path)
        rag_results = build_rag_graph(repo_path)
        
        print("\n=== Graph Comparison Result ===")
        print(f"{'Metric':<15} | {'Graphify':<10} | {'RAG (ast-index enriched)':<15}")
        print("-" * 55)
        print(f"{'Nodes':<15} | {graphify_results['nodes']:<10} | {rag_results['nodes']:<15}")
        print(f"{'Edges (Total)':<15} | {graphify_results['edges']:<10} | {rag_results['edges']:<15}")
        print(f"{'Latency (ms)':<15} | {graphify_results['latency_ms']:<10.1f} | {rag_results['latency_ms']:<15.1f}")
        
    finally:
        if repo_path.exists():
            shutil.rmtree(repo_path)

if __name__ == "__main__":
    main()
