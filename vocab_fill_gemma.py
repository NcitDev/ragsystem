#!/usr/bin/env python3
"""Remote tail-filler: summarize files the Mac/agy run did NOT cover, with gemma4.

Reads an existing REL-PATH-keyed JSONL (the agy output, scp'd over) to learn what
is already done, then summarizes only the missing/ERROR files and APPENDS them to
the SAME merged JSONL — keyed by rel path so agy + gemma4 entries interleave.

Usage:
  python3 vocab_fill_gemma.py --merged /home/nikita/development/vocab_merged.jsonl \
      --model gemma4:12b --parallel 3 [--limit N]
"""
import argparse
import glob
import json
import os
import re
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = "/home/nikita/development/Signal-Android"
SUBDIR = "app/src/main"
OLLAMA = "http://localhost:11434/api/generate"
MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
PROMPT_HEAD = (
    "In ONE sentence, describe this code file for a search index. "
    "Name the main class/interface AND the domain concepts a developer might "
    "search for. Code:\n"
)


def relpath(fp):
    return os.path.relpath(fp, ROOT)


def summarize(model, fp):
    code = open(fp, errors="replace").read()[:2800]
    nothink = "/no_think " if "qwen" in model else ""
    body = json.dumps({"model": model, "prompt": nothink + PROMPT_HEAD + code,
                       "stream": False,
                       "options": {"temperature": 0.1, "num_ctx": 4096}}).encode()
    r = urllib.request.urlopen(urllib.request.Request(
        OLLAMA, data=body, headers={"Content-Type": "application/json"}), timeout=300)
    txt = json.loads(r.read())["response"]
    txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.DOTALL)
    return MD_LINK.sub(r"\1", txt).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merged", default="/home/nikita/development/vocab_merged.jsonl")
    ap.add_argument("--model", default="gemma4:12b")
    ap.add_argument("--parallel", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--start", type=int, default=0, help="slice start over sorted full list")
    ap.add_argument("--end", type=int, default=0, help="slice end (0 = to the end)")
    ap.add_argument("--files-from", default="",
                    help="explicit newline-separated rel-paths to process (overrides slice)")
    a = ap.parse_args()

    files = sorted(glob.glob(f"{ROOT}/{SUBDIR}/**/*.kt", recursive=True)
                   + glob.glob(f"{ROOT}/{SUBDIR}/**/*.java", recursive=True))
    if a.files_from:
        wanted = {l.strip() for l in open(a.files_from) if l.strip()}
        files = [p for p in files if relpath(p) in wanted]
    else:
        end = a.end or len(files)
        files = files[a.start:end]
    if a.limit:
        files = files[: a.limit]

    done = set()
    if os.path.exists(a.merged):
        for line in open(a.merged):
            try:
                rec = json.loads(line)
                if not str(rec.get("summary", "")).startswith("ERROR"):
                    done.add(rec["file"])
            except Exception:
                pass

    todo = [f for f in files if relpath(f) not in done]
    total = len(files)
    print(f"[fill] model={a.model} | files={total} done={len(done)} todo={len(todo)}", flush=True)
    if not todo:
        print("[fill] nothing to do — agy covered everything.", flush=True)
        return

    out = open(a.merged, "a")
    lock = threading.Lock()
    n = len(done)
    errs = 0

    def work(fp):
        try:
            return fp, summarize(a.model, fp)
        except Exception as e:
            return fp, f"ERROR:{e}"

    with ThreadPoolExecutor(max_workers=a.parallel) as ex:
        for fut in as_completed([ex.submit(work, fp) for fp in todo]):
            fp, s = fut.result()
            with lock:
                out.write(json.dumps({"file": relpath(fp), "summary": s}) + "\n")
                out.flush()
                n += 1
                if s.startswith("ERROR"):
                    errs += 1
                print(f"[{n}/{total}] errs={errs} | {os.path.basename(fp)[:40]}", flush=True)
    print(f"[fill] DONE: {n}/{total} (errs={errs}) -> {a.merged}", flush=True)


if __name__ == "__main__":
    main()
