#!/usr/bin/env python3
"""Mac vocabulary summarizer via the `mimo` (mimocode) CLI, model mimo/mimo-auto.

Cloud-backed and genuinely parallel (unlike the GPU-bound gemma4). Resumable,
rel-path keyed so it merges with the agy + gemma4 outputs. Supports an explicit
[--start, --end] slice over the SORTED full file list so it can run on a DISJOINT
partition from gemma4 (no double work).

Usage:
  python3 vocab_summarize_mimo.py --parallel 8 --start 1300 [--end N] [--out FILE]
"""
import argparse
import glob
import json
import os
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

SRC = "/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android"
SUBDIR = "app/src/main"
MODEL = "mimo/mimo-auto"
PROMPT_HEAD = (
    "In ONE sentence, describe this code file for a search index. "
    "Name the main class/interface AND the domain concepts a developer might "
    "search for. Output ONLY the sentence, no preamble. Code:\n"
)
MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def relpath(fp):
    return os.path.relpath(fp, SRC)


def clean_stdout(stdout):
    """mimo prints a couple of chatter lines ('> build · mimo-auto', ANSI resets)
    before the answer. The summary is the last meaningful line."""
    out = []
    for raw in stdout.splitlines():
        line = ANSI.sub("", raw).strip()
        if not line or "mimo-auto" in line or line.startswith(">") or line == "[0m":
            continue
        out.append(line)
    text = out[-1] if out else ""
    return MD_LINK.sub(r"\1", text).strip()


def summarize(fp, timeout, retries):
    code = open(fp, errors="replace").read()[:2800]
    prompt = PROMPT_HEAD + code
    last = ""
    for attempt in range(retries + 1):
        try:
            r = subprocess.run(
                ["mimo", "run", "-m", MODEL, prompt],
                cwd="/tmp", capture_output=True, text=True, timeout=timeout,
            )
            out = clean_stdout(r.stdout)
            if out and len(out) > 20:
                return out
            last = (out or r.stderr or "empty")[:200]
        except subprocess.TimeoutExpired:
            last = f"timeout>{timeout}s"
        except Exception as e:  # noqa: BLE001
            last = f"exc:{e}"[:200]
        time.sleep(1.5 * (attempt + 1))
    return f"ERROR:{last}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parallel", type=int, default=8)
    ap.add_argument("--start", type=int, default=0, help="slice start over sorted full list")
    ap.add_argument("--end", type=int, default=0, help="slice end (0 = to the end)")
    ap.add_argument("--timeout", type=int, default=90)
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--out", default="/Users/nikitaf/production/ragsystem/vocab_summaries_mimo.jsonl")
    a = ap.parse_args()

    files = sorted(
        glob.glob(f"{SRC}/{SUBDIR}/**/*.kt", recursive=True)
        + glob.glob(f"{SRC}/{SUBDIR}/**/*.java", recursive=True)
    )
    end = a.end or len(files)
    sliced = files[a.start:end]

    done = set()
    if os.path.exists(a.out):
        for line in open(a.out):
            try:
                rec = json.loads(line)
                if not str(rec.get("summary", "")).startswith("ERROR"):
                    done.add(rec["file"])
            except Exception:  # noqa: BLE001
                pass

    todo = [f for f in sliced if relpath(f) not in done]
    total = len(sliced)
    n = total - len(todo)
    start_t = time.time()
    print(f"[vocab-mimo] model={MODEL!r} parallel={a.parallel} slice=[{a.start}:{end}] | "
          f"slice_files={total} done={n} todo={len(todo)}", flush=True)

    out = open(a.out, "a")
    lock = threading.Lock()
    errs = 0

    def work(fp):
        return fp, summarize(fp, a.timeout, a.retries)

    with ThreadPoolExecutor(max_workers=a.parallel) as ex:
        for fut in as_completed([ex.submit(work, fp) for fp in todo]):
            fp, s = fut.result()
            with lock:
                out.write(json.dumps({"file": relpath(fp), "summary": s}) + "\n")
                out.flush()
                n += 1
                if s.startswith("ERROR"):
                    errs += 1
                el = time.time() - start_t
                rate = (n - (total - len(todo))) / el if el > 0 else 0
                eta = (total - n) / rate if rate > 0 else 0
                print(f"[{n}/{total} {n/total*100:4.1f}%] {rate:.2f} f/s "
                      f"ETA {int(eta//60)}m{int(eta%60):02d}s errs={errs} | "
                      f"{os.path.basename(fp)[:40]}", flush=True)

    print(f"[vocab-mimo] DONE: {n}/{total} (errs={errs}) -> {a.out}", flush=True)


if __name__ == "__main__":
    main()
