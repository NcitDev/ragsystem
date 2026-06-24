#!/usr/bin/env python3
"""Mac vocabulary summarizer: per-file summaries via the `agy` (Antigravity/Gemini) CLI.

Resumable (skips rel-paths already present with a non-error summary). Parallel workers.
JSONL is keyed by REL PATH (relative to the Signal-Android root) so Mac (agy) and
remote (gemma4) outputs merge cleanly.

Usage:
  python3 vocab_summarize_mac.py --parallel 12 [--limit N] [--out FILE]
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
MODEL = "Gemini 3.5 Flash (High)"
PROMPT_HEAD = (
    "In ONE sentence, describe this code file for a search index. "
    "Name the main class/interface AND the domain concepts a developer might "
    "search for. Code:\n"
)
MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")


def relpath(fp):
    return os.path.relpath(fp, SRC)


def clean(text):
    text = MD_LINK.sub(r"\1", text)            # [Foo](file:///...) -> Foo
    return text.strip()


def summarize(fp, timeout, retries):
    code = open(fp, errors="replace").read()[:2800]
    prompt = PROMPT_HEAD + code
    last = ""
    for attempt in range(retries + 1):
        try:
            r = subprocess.run(
                ["agy", "-p", prompt, "--model", MODEL],
                cwd="/tmp", capture_output=True, text=True, timeout=timeout,
            )
            out = clean(r.stdout)
            # agy occasionally emits chatter on failure; require a plausible sentence
            if out and len(out) > 20 and "command not found" not in out:
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
    ap.add_argument("--parallel", type=int, default=12)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--out", default="/Users/nikitaf/production/ragsystem/vocab_summaries_mac.jsonl")
    a = ap.parse_args()

    files = sorted(
        glob.glob(f"{SRC}/{SUBDIR}/**/*.kt", recursive=True)
        + glob.glob(f"{SRC}/{SUBDIR}/**/*.java", recursive=True)
    )
    if a.limit:
        files = files[: a.limit]

    done = set()
    if os.path.exists(a.out):
        for line in open(a.out):
            try:
                rec = json.loads(line)
                if not str(rec.get("summary", "")).startswith("ERROR"):
                    done.add(rec["file"])
            except Exception:  # noqa: BLE001
                pass

    todo = [f for f in files if relpath(f) not in done]
    total = len(files)
    n = len(done)
    start = time.time()
    print(f"[vocab-mac] model={MODEL!r} parallel={a.parallel} timeout={a.timeout}s | "
          f"files={total} done={len(done)} todo={len(todo)}", flush=True)

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
                el = time.time() - start
                rate = (n - len(done)) / el if el > 0 else 0
                eta = (total - n) / rate if rate > 0 else 0
                print(f"[{n}/{total} {n/total*100:4.1f}%] {rate:.2f} f/s "
                      f"ETA {int(eta//60)}m{int(eta%60):02d}s errs={errs} | "
                      f"{os.path.basename(fp)[:40]}", flush=True)

    print(f"[vocab-mac] DONE: wrote up to {n}/{total} (errs={errs}) -> {a.out}", flush=True)


if __name__ == "__main__":
    main()
