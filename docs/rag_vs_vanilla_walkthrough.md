# RAG vs Vanilla Codex Coding Walkthrough

This walkthrough verifies whether the local RAG system helps more than ordinary
Codex-style source inspection for coding work.

Current status from the June 5, 2026 smoke run:

- Ollama: running on `127.0.0.1:11434`
- RAG daemon: running on `127.0.0.1:7890`
- Web dashboard: `http://127.0.0.1:7890/`
- Main collection: `code_chunks`, 56,427 chunks
- Embedding model: `qwen3-embedding:4b-q8_0`
- Generation model: `qwen3:8b`

## 1. Start Services

Terminal A:

```bash
ollama serve
```

Terminal B:

```bash
cd /Users/nikitaf/production/ragsystem
uv run rag start
```

Health checks:

```bash
curl -sS http://127.0.0.1:7890/health

TOKEN="$(tr -d '\n' < ~/.rag/token)"
curl -sS \
  -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:7890/status | uv run python -m json.tool
```

Expected:

- `/health` has `qdrant: ok`, `embedder: ollama`, `ollama: ok`
- `/status` has `status: running`
- Browser dashboard shows chunks and model names

## 2. RAG Evaluation

The existing eval harness currently misses the auth header, so running it
directly is a negative control:

```bash
uv run python tests/eval/run_eval.py tests/eval/telegram_eval.jsonl --top-k 10
```

Current expected result until fixed:

- `avg_recall=0.000`
- every task has `strategy=ERROR`

Authenticated RAG eval procedure:

```bash
TOKEN="$(tr -d '\n' < ~/.rag/token)"
uv run python - <<'PY'
from pathlib import Path
import json, httpx, time, statistics

base = "http://127.0.0.1:7890"
token = Path.home().joinpath(".rag/token").read_text().strip()
items = [
    json.loads(line)
    for line in Path("tests/eval/telegram_eval.jsonl").read_text().splitlines()
    if line.strip() and not line.startswith("#")
]

def file_hit(returned_path, expected_suffix):
    rp = returned_path.replace("\\", "/")
    sx = expected_suffix.replace("\\", "/").lstrip("/")
    return rp.endswith(sx) or f"/{sx}" in rp

rows = []
with httpx.Client(headers={"Authorization": f"Bearer {token}"}, timeout=60) as client:
    for item in items:
        started = time.perf_counter()
        resp = client.post(base + "/search", json={
            "query": item["query"],
            "top_k": 10,
            "rerank": False,
        })
        elapsed_ms = (time.perf_counter() - started) * 1000
        if resp.status_code != 200:
            rows.append((item["task_id"], "ERROR", 0.0, "", elapsed_ms, 0, len(item["expected_files"])))
            continue

        body = resp.json()
        returned = [r["file_path"] for r in body.get("results", [])]
        matched = []
        first = None
        for exp in item["expected_files"]:
            for rank, path in enumerate(returned, start=1):
                if file_hit(path, exp):
                    matched.append(exp)
                    first = rank if first is None else min(first, rank)
                    break
        recall = len(matched) / len(item["expected_files"])
        rows.append((
            item["task_id"],
            (body.get("plan") or {}).get("strategy", "unknown"),
            recall,
            first or "",
            body.get("latency_ms", elapsed_ms),
            len(matched),
            len(item["expected_files"]),
        ))

print("task_id,strategy,recall,first_hit,latency_ms,matched/expected")
for row in rows:
    print(f"{row[0]},{row[1]},{row[2]:.2f},{row[3]},{row[4]:.0f},{row[5]}/{row[6]}")
print("avg_recall", round(statistics.mean(r[2] for r in rows), 3))
PY
```

Current measured RAG result:

| Task | Strategy | Recall@10 | First hit | Latency |
| --- | --- | ---: | ---: | ---: |
| task-1-send-pipeline | graph_walk | 0.00 | - | 771 ms |
| task-2-voice-flow | lod_drill | 0.00 | - | 393 ms |
| task-3-controllers | aggregate | 0.20 | 1 | 406 ms |
| task-4-tlrpc-message | lod_drill | 0.20 | 1 | 573 ms |
| task-5-connection-state | filtered | 0.00 | - | 728 ms |
| sanity-1 | lod_drill | 1.00 | 8 | 408 ms |
| sanity-2 | lod_drill | 1.00 | 3 | 389 ms |
| sanity-3 | lod_drill | 0.00 | - | 357 ms |

Summary:

- Average recall: 0.300
- MRR: 0.307
- p50 latency: 407 ms
- p95 latency: 728 ms

## 3. Vanilla Codex Baseline

This approximates vanilla Codex using targeted `rg` searches over the same
Telegram source tree.

```bash
uv run python - <<'PY'
from pathlib import Path
import subprocess, time, json, statistics

root = Path("/Users/nikitaf/production/Telegram/TMessagesProj/src/main/java")
items = [
    json.loads(line)
    for line in Path("tests/eval/telegram_eval.jsonl").read_text().splitlines()
    if line.strip() and not line.startswith("#")
]

patterns = {
    "task-1-send-pipeline": ["MessagesController", "SendMessagesHelper", "sendMessage", "SecretChatHelper", "ConnectionsManager"],
    "task-2-voice-flow": ["voice message", "AudioRecordJNI", "AudioTrackJNI", "MediaController", "SendMessagesHelper", "MessageObject", "RecordCircle"],
    "task-3-controllers": ["extends BaseController", "BaseController", "AccountInstance", "MessagesController", "ContactsController", "LocationController", "DownloadController"],
    "task-4-tlrpc-message": ["TLRPC.Message", "class Message", "serializeToStream", "MessagesStorage", "MessageObject", "ChatMessageCell"],
    "task-5-connection-state": ["STATE_CONNECTING", "STATE_CONNECTED", "STATE_WAITING_FOR_NETWORK", "NotificationCenter", "ConnectionsManager"],
    "sanity-1": ["class MessagesController", "MessagesController"],
    "sanity-2": ["class ConnectionsManager", "ConnectionsManager"],
    "sanity-3": ["class BaseFragment", "onFragmentCreate", "onFragmentDestroy"],
}

def file_hit(path, expected_suffix):
    rp = str(path).replace("\\", "/")
    sx = expected_suffix.replace("\\", "/").lstrip("/")
    return rp.endswith(sx) or f"/{sx}" in rp

rows = []
for item in items:
    started = time.perf_counter()
    ordered = []
    seen = set()
    for pattern in patterns[item["task_id"]]:
        result = subprocess.run(["rg", "-l", "-F", pattern, str(root)], text=True, capture_output=True)
        for path in result.stdout.splitlines():
            if path not in seen:
                seen.add(path)
                ordered.append(path)
    elapsed_ms = (time.perf_counter() - started) * 1000
    top = ordered[:10]
    matched = []
    first = None
    for exp in item["expected_files"]:
        for rank, path in enumerate(top, start=1):
            if file_hit(path, exp):
                matched.append(exp)
                first = rank if first is None else min(first, rank)
                break
    rows.append((item["task_id"], len(matched) / len(item["expected_files"]), first or "", elapsed_ms, len(matched), len(item["expected_files"])))

print("task_id,recall,first_hit,latency_ms,matched/expected")
for row in rows:
    print(f"{row[0]},{row[1]:.2f},{row[2]},{row[3]:.0f},{row[4]}/{row[5]}")
print("avg_recall", round(statistics.mean(r[1] for r in rows), 3))
PY
```

Current measured vanilla baseline:

| Task | Recall@10 | First hit | Latency |
| --- | ---: | ---: | ---: |
| task-1-send-pipeline | 0.00 | - | 222 ms |
| task-2-voice-flow | 0.50 | 1 | 171 ms |
| task-3-controllers | 0.20 | 10 | 168 ms |
| task-4-tlrpc-message | 0.00 | - | 144 ms |
| task-5-connection-state | 0.50 | 9 | 117 ms |
| sanity-1 | 1.00 | 1 | 48 ms |
| sanity-2 | 1.00 | 1 | 49 ms |
| sanity-3 | 1.00 | 1 | 69 ms |

Summary:

- Average recall: 0.525
- MRR: 0.526
- p50 latency: 130 ms
- p95 latency: 171 ms

## 4. Interpretation

Current result: RAG is not yet better than vanilla Codex-style source search for
these coding tasks.

RAG is useful for the browser experience and semantic discovery, but it loses
important exact-symbol and repo-scoped tasks. The main failure modes are:

- exact class/file names are not strong enough ranking signals
- unrelated repos share the `code_chunks` collection and add noise
- named repo registry exists, but named repo collections are not populated
- the eval harness is broken after auth was added
- LOD search often degrades because summary collections are missing

## 5. Issues Found

1. Eval harness does not authenticate.
   `tests/eval/run_eval.py` calls `/search` without the bearer token, so all
   protected-route evals report fake 0% recall.

2. Registered repos can point to missing Qdrant collections.
   `telegram-core` is registered as `repo_telegram-core`, but `/collections`
   only shows `code_chunks` and `doc_chunks`. Searching `repo:"telegram-core"`
   returns HTTP 500: `Collection repo_telegram-core not found`.

3. Shared collection causes cross-repo noise.
   Queries for Telegram return Dodo/Kotlin/Dart and WebRTC hits. Without repo
   isolation, semantic search has to rank across unrelated projects.

4. Path filtering is exact-match only.
   `filters: {"file_path": "org/telegram/messenger/MediaController.java"}`
   works, but there is no prefix/root filter for `org/telegram`.

5. LOD collections are missing or stale.
   Logs show `lod_drill_degraded reason=no_lod_data`, so a strategy selected
   by the planner is not actually available.

6. Dense-only search underweights exact symbols.
   Sanity queries such as `MessagesController class definition` only find
   `MessagesController.java` at rank 8, and `BaseFragment lifecycle methods`
   misses `ActionBar/BaseFragment.java` entirely.

7. Web dashboard status can mislead.
   It shows `indexed` and 56,427 chunks, but `files_indexed` is 0 and named
   repo collections are invisible.

8. Embedded Qdrant warns above 20k points.
   The current 56k-point local collection triggers Qdrant's local-mode warning,
   so performance and reliability should be watched as corpus size grows.

## 6. Fix Plan

P0 - Make evaluation truthful:

- Add auth support to `tests/eval/run_eval.py`.
- Fail eval tasks on non-200 status with the response body in the report.
- Add a `--baseline rg` mode or separate script so RAG and vanilla results are
  generated from one command.

P0 - Fix repo scoping:

- On `/search repo=...`, check that the repo collection exists before querying.
- Return 404 or 409 with `repo registered but not indexed` instead of 500.
- Re-index Telegram into `repo_telegram-core`, or migrate existing chunks with
  a `repo_name` payload.

P1 - Improve retrieval quality:

- Add lexical/symbol retrieval alongside dense search: BM25, trigram, or exact
  identifier matching.
- Boost exact file/class/method names in `score_results`.
- Add path/package boosts for query tokens like `MessagesController`,
  `BaseFragment`, `TLRPC`, `ChatMessageCell`.
- Rebuild or disable LOD strategies until L0/L1 collections exist.

P1 - Add prefix filters:

- Store normalized `repo_name`, `source_root`, `package_path`, and path tokens
  during indexing.
- Support path-prefix filtering through payload fields rather than exact
  `file_path` equality.

P2 - Make the dashboard operationally honest:

- Show named repos and whether their backing collection exists.
- Show `registered`, `indexed`, `missing collection`, and chunk counts
  separately.
- Add search repo/filter controls.
- Fix the `files_indexed=0` display when chunks exist.

P2 - Production hardening:

- Move 50k+ point corpora to Qdrant server/Docker instead of embedded local
  mode.
- Add startup diagnostics for missing Ollama, missing model, missing repo
  collection, and stale LOD indexes.

