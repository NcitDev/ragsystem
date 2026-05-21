# Telegram RAG Stress-Test Tasks

Five real-world tasks on the Telegram Android codebase (`TMessagesProj/src/main/java`)
used to evaluate the RAG system in production-like conditions. Each task has
ground-truth files, an expected difficulty, and pass/fail criteria.

Corpus snapshot:
- 2913 Java files
- ~24k LOC `MessagesController.java` (god-class)
- 126 `BaseFragment` subclasses
- Packages: `messenger/`, `tgnet/`, `ui/`, `messenger/voip/`, `messenger/secretmedia/`

---

## Task 1 — Refactor: extract message-send pipeline from MessagesController

**Type:** refactor
**Difficulty:** hard
**Question:** Where is the message-send code path that flows from
`MessagesController` into `SendMessagesHelper`, and which methods would need
to move to extract the send pipeline into a dedicated class?

**Ground-truth files (must surface in top-10):**
- `messenger/MessagesController.java`
- `messenger/SendMessagesHelper.java`
- `messenger/MessageObject.java`
- `messenger/SecretChatHelper.java` (secret-chat branch)
- `tgnet/ConnectionsManager.java` (transport)

**Success criteria:**
- Recall ≥ 4/5 on ground-truth files
- Top result is `SendMessagesHelper` or `MessagesController.sendMessage*`
- Strategy plan should pick `hybrid` or `graph_walk`

---

## Task 2 — Bugfix investigation: voice-message recording → playback flow

**Type:** comprehension / bugfix
**Difficulty:** medium
**Question:** Trace the voice message lifecycle: microphone capture →
encoding → upload → server → download → playback. Identify the classes that
would need to change to fix a bug where voice messages cut off the last 100ms.

**Ground-truth files:**
- `messenger/MediaController.java` (recording)
- `messenger/voip/AudioRecordJNI.java` or `AudioTrackJNI.java`
- `messenger/SendMessagesHelper.java` (upload path)
- `messenger/MessageObject.java` (audio attribute)
- `ui/Components/RecordCircle.java` or similar UI

**Success criteria:**
- Recall ≥ 3/5
- Hits include both record and playback layers
- Latency p95 < 3s

---

## Task 3 — Refactor: introduce BaseController for all controllers

**Type:** refactor / cross-cutting
**Difficulty:** hard
**Question:** Which controller classes do NOT extend `BaseController` and
should be migrated? List candidates and the methods they share with
`BaseController`.

**Ground-truth files:**
- `messenger/BaseController.java` (parent)
- 30+ `*Controller.java` siblings (subset must appear)
- At minimum: `MessagesController`, `ContactsController`,
  `LocationController`, `DownloadController`

**Success criteria:**
- Surfaces `BaseController.java` plus ≥ 5 subclasses
- Strategy plan picks `aggregate` or `filtered`
- Demonstrates RAG can answer "which classes match pattern X"

---

## Task 4 — Cross-cutting: add a new field to TLRPC message

**Type:** cross-cutting change
**Difficulty:** hard
**Question:** If we add a new field `int reactionCount` to `TLRPC.Message`,
which files need to change to (a) parse it from the wire, (b) store it,
(c) display it in chat?

**Ground-truth files:**
- `tgnet/TLRPC.java` (definition)
- `messenger/MessagesStorage.java` (persistence)
- `messenger/MessageObject.java` (in-memory model)
- `ui/Cells/ChatMessageCell.java` (rendering)
- `messenger/MessagesController.java` (state propagation)

**Success criteria:**
- Recall ≥ 4/5
- All three layers (wire/storage/UI) represented in top-10
- This is the hardest task; partial credit accepted at 3/5

---

## Task 5 — Bugfix: race in connection state notifications

**Type:** bugfix
**Difficulty:** medium
**Question:** Where are connection state changes (`STATE_CONNECTING`,
`STATE_CONNECTED`, `STATE_WAITING_FOR_NETWORK`) propagated to the UI? List
all observers and the threading model used.

**Ground-truth files:**
- `tgnet/ConnectionsManager.java` (source)
- `messenger/NotificationCenter.java` (event bus)
- `ui/ActionBar/ActionBarLayout.java` or `LaunchActivity.java` (UI consumer)

**Success criteria:**
- Recall ≥ 2/3
- `NotificationCenter` and `ConnectionsManager` both in top-10
- Strategy plan picks `hybrid`

---

## Evaluation procedure

For each task, run:

```bash
# RAG path
rag search "<task question>" --repo telegram-core --top-k 10 > rag_taskN.json

# Baseline path
grep -rln "<keywords>" \
  /Users/nikitaf/production/Telegram/TMessagesProj/src/main/java \
  | head -10 > grep_taskN.txt
```

Record per task:

| Metric | RAG | grep |
|--------|-----|------|
| Files surfaced | | |
| Ground-truth hits | | |
| Recall@10 | | |
| Latency | | |
| Noise (irrelevant hits) | | |

Aggregate goal: **RAG recall@10 ≥ 0.80 averaged across 5 tasks**, with
median latency < 2s.
