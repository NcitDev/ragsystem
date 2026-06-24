#!/usr/bin/env python3
"""Measure gemma4 throughput at different parallelism on this GPU."""
import glob, json, os, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = "/home/nikita/development/Signal-Android"
SUBDIR = "app/src/main"
MERGED = "/home/nikita/development/vocab_merged.jsonl"
OLLAMA = "http://localhost:11434/api/generate"
MODEL = "gemma4:12b"
HEAD = ("In ONE sentence, describe this code file for a search index. Name the "
        "main class/interface AND the domain concepts a developer might search for. Code:\n")

def call(fp):
    code = open(fp, errors="replace").read()[:2800]
    body = json.dumps({"model": MODEL, "prompt": HEAD + code, "stream": False,
                       "options": {"temperature": 0.1, "num_ctx": 4096}}).encode()
    r = urllib.request.urlopen(urllib.request.Request(
        OLLAMA, data=body, headers={"Content-Type": "application/json"}), timeout=300)
    return len(json.loads(r.read())["response"])

files = sorted(glob.glob(f"{ROOT}/{SUBDIR}/**/*.kt", recursive=True)
               + glob.glob(f"{ROOT}/{SUBDIR}/**/*.java", recursive=True))
done = set()
for line in open(MERGED):
    try: done.add(json.loads(line)["file"])
    except Exception: pass
undone = [f for f in files if os.path.relpath(f, ROOT) not in done]
print(f"undone files available: {len(undone)}")

# warmup (load model into VRAM)
call(undone[0]); print("warmed up")

N = 6
for par in (1, 3, 5):
    batch = undone[1 + (par*N) : 1 + (par*N) + N]  # distinct files per run
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=par) as ex:
        list(ex.map(call, batch))
    el = time.time() - t0
    print(f"parallel={par}: {N} files in {el:5.1f}s -> {N/el:.3f} files/s ({el/N:.1f}s/file)")
