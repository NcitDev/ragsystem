import json
import urllib.request
from pathlib import Path

RAG_URL = "http://127.0.0.1:7890"

def analyze_rag_density(query, expected_file):
    token = Path.home().joinpath(".rag/token").read_text().strip()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    payload = json.dumps({
        "query": query, 
        "repo": "signal", 
        "max_slices": 40,
        "max_source_tokens": 20000
    }).encode()
    
    req = urllib.request.Request(f"{RAG_URL}/context-pack", data=payload, headers=headers)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())
        slices = data.get("slices", [])
        
        print(f"QUERY: {query}")
        print(f"TOTAL SLICES: {len(slices)}")
        
        # Check for expected file
        found_at = -1
        for i, s in enumerate(slices):
            if expected_file in s['file_path']:
                found_at = i + 1
                break
        
        if found_at != -1:
            print(f"✅ TARGET FOUND at rank {found_at}/40")
        else:
            print(f"❌ TARGET NOT FOUND in top 40")
            
        # Relevance analysis of top 5
        print("\nTOP 5 RELEVANCE ANALYSIS:")
        for s in slices[:5]:
            print(f" - {s['file_path']} ({s['why_included']})")

if __name__ == "__main__":
    print("--- TASK 5: BLAST RADIUS (SignalServiceAccountManager) ---")
    analyze_rag_density("What depends on SignalServiceAccountManager?", "AppDependencies.kt")
    print("\n--- TASK 6: TEST COVERAGE (JobMigration) ---")
    analyze_rag_density("Find the job manager migration logic and its unit tests.", "JobMigrationTest.java")
