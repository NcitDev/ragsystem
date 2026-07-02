#!/usr/bin/env python3
"""Mac vocabulary summarizer via the `qodercli` CLI, model Qwen3.7-Max.

Serial by default (1 agent), resumable, rel-path keyed so it merges with the
agy/gemma4 outputs. Supports a [--start,--end] slice over the SORTED full file
list so it runs on a DISJOINT partition from gemma4. Aborts when qodercli starts
"dying" (--die-after consecutive errors) so we can see exactly when/if it fails.

Usage:
  python3 vocab_summarize_qoder.py --start 1300 [--end N] [--parallel 1]
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
MODEL = "Qwen3.7-Max"
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
    lines = [ANSI.sub("", l).strip() for l in stdout.splitlines()]
    lines = [l for l in lines if l]
    text = lines[-1] if lines else ""
    return MD_LINK.sub(r"\1", text).strip()


def summarize(fp, timeout, retries):
    code = open(fp, errors="replace").read()[:2800]
    prompt = PROMPT_HEAD + code
    last = ""
    for attempt in range(retries + 1):
        try:
            r = subprocess.run(
                ["qodercli", "-p", "-m", MODEL, prompt],
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
    ap.add_argument("--parallel", type=int, default=1)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--die-after", type=int, default=10,
                    help="abort after this many consecutive ERRORs (qodercli is dying)")
    ap.add_argument("--files-from", default="",
                    help="explicit newline-separated rel-paths to process (overrides slice)")
    ap.add_argument("--out", default="/Users/nikitaf/production/ragsystem/vocab_summaries_qoder.jsonl")
    a = ap.parse_args()

    files = sorted(
        glob.glob(f"{SRC}/{SUBDIR}/**/*.kt", recursive=True)
        + glob.glob(f"{SRC}/{SUBDIR}/**/*.java", recursive=True)
    )
    end = a.end or len(files)
    if a.files_from:
        wanted = {l.strip() for l in open(a.files_from) if l.strip()}
        sliced = [p for p in files if relpath(p) in wanted]
        slice_label = f"files-from={a.files_from}"
    else:
        sliced = files[a.start:end]
        slice_label = f"[{a.start}:{end}]"

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
    print(f"[vocab-qoder] model={MODEL!r} parallel={a.parallel} {slice_label} "
          f"die_after={a.die_after} | slice_files={total} done={n} todo={len(todo)}", flush=True)

    out = open(a.out, "a")
    lock = threading.Lock()
    errs = 0
    consec = 0
    aborted = False

    def work(fp):
        return fp, summarize(fp, a.timeout, a.retries)

    with ThreadPoolExecutor(max_workers=a.parallel) as ex:
        futs = [ex.submit(work, fp) for fp in todo]
        for fut in as_completed(futs):
            fp, s = fut.result()
            with lock:
                out.write(json.dumps({"file": relpath(fp), "summary": s}) + "\n")
                out.flush()
                n += 1
                if s.startswith("ERROR"):
                    errs += 1
                    consec += 1
                else:
                    consec = 0
                el = time.time() - start_t
                rate = (n - (total - len(todo))) / el if el > 0 else 0
                eta = (total - n) / rate if rate > 0 else 0
                print(f"[{n}/{total} {n/total*100:4.1f}%] {rate:.2f} f/s "
                      f"ETA {int(eta//60)}m{int(eta%60):02d}s errs={errs} consec={consec} | "
                      f"{os.path.basename(fp)[:40]}", flush=True)
                if consec >= a.die_after:
                    print(f"[vocab-qoder] DIED: {consec} consecutive errors — qodercli is failing. "
                          f"Stopping at {n}/{total}.", flush=True)
                    aborted = True
                    break
        if aborted:
            for f in futs:
                f.cancel()

    tag = "DIED" if aborted else "DONE"
    print(f"[vocab-qoder] {tag}: {n}/{total} (errs={errs}) -> {a.out}", flush=True)


if __name__ == "__main__":
    main()
