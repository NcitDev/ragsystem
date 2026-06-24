#!/usr/bin/env python3
"""Vocab-layer A/B benchmark against the live /smart-search endpoint.

For each golden scenario, one /smart-search call yields several buckets. We score
coverage three ways to isolate the vocab layer's contribution:
  BASELINE  = definitions + usages + related + semantic  (old smart-search)
  VOCAB     = vocab_files only                           (the new layer)
  COMBINED  = union of both

Run ON the remote box (hits localhost:7890 with the repo_signal_vocab collection):
  python3 benchmark_vocab.py
"""
import json
import time
import urllib.request

RAG_URL = "http://127.0.0.1:7890"
REPO = "signal"
TOP_K = 15
PKG = "app/src/main/java/org/thoughtcrime/securesms"

SCENARIOS = [
    (1, "Add a sticker pack install event. What's the existing pattern?",
     [f"{PKG}/stickers/StickerPackInstallEvent.java",
      f"{PKG}/stickers/preview/StickerPackPreviewRepository.java",
      f"{PKG}/stickers/preview/StickerPackPreviewViewModel.java"]),
    (2, "Find the database migration interface and show a concrete migration",
     [f"{PKG}/database/helpers/migration/SignalDatabaseMigration.kt",
      f"{PKG}/database/helpers/SignalDatabaseMigrations.kt"]),
    (3, "Show me the main classes in the sticker pack management system",
     [f"{PKG}/stickers/manage/StickerManagementRepository.kt",
      f"{PKG}/stickers/BlessedPacks.kt",
      f"{PKG}/stickers/preview/StickerPackPreviewViewModelV2.kt"]),
    (4, "I need to add a new backup feature. Show me how FullBackupExporter works",
     [f"{PKG}/backup/FullBackupExporter.java",
      f"{PKG}/backup/FullBackupBase.java"]),
    (5, "Find deprecated job migration code that should be cleaned up",
     [f"{PKG}/jobmanager/migrations/DeprecatedJobMigration.kt",
      f"{PKG}/jobmanager/migrations/PushDecryptMessageJobEnvelopeMigration.java",
      f"{PKG}/jobmanager/migrations/PushProcessMessageJobMigration.kt"]),
    (6, "If I change the Job base class, what code breaks? Show all subclasses",
     [f"{PKG}/jobmanager/Job.java",
      f"{PKG}/jobmanager/JobManager.java",
      f"{PKG}/jobmanager/migrations/PushProcessMessageJobMigration.kt"]),
    (7, "Rename SignalDatabaseMigration interface. Find all implementors and callers",
     [f"{PKG}/database/helpers/migration/SignalDatabaseMigration.kt",
      f"{PKG}/database/helpers/SignalDatabaseMigrations.kt"]),
    (8, "Who calls Recipient? Show me the blast radius of changing the Recipient model",
     [f"{PKG}/recipients/Recipient.kt",
      f"{PKG}/database/RecipientTable.kt",
      f"{PKG}/recipients/RecipientId.kt"]),
    (9, "How does the chat backup encryption and passphrase system work?",
     [f"{PKG}/backup/BackupPassphrase.java",
      f"{PKG}/backup/BackupDialog.java"]),
    (10, "Trace how push notifications are received and processed by the app",
     [f"{PKG}/gcm/FcmReceiveService.java",
      f"{PKG}/notifications/MessageNotifier.java",
      f"{PKG}/gcm/FcmJobService.java"]),
]


def post(path, body, token):
    req = urllib.request.Request(
        RAG_URL + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())


def hits(files, golden):
    return [g for g in golden if any(f == g or f.endswith(g) or g.endswith(f) for f in files)]


def run(q, golden, token, use_vocab):
    """One /smart-search call. Pull the whole candidate pool (one big page) and
    measure coverage in the top-15 (what's shown first) vs the full pool (the
    recall ceiling the LLM can reach by paging)."""
    d = post("/smart-search", {"question": q, "repo": REPO, "top_k": TOP_K,
                               "include_vocab": use_vocab,
                               "candidate_offset": 0, "candidate_limit": 200}, token)
    cand = [c.get("file_path", "") for c in d.get("candidates", []) if c.get("file_path")]
    top = cand[:TOP_K]
    top_cov = len(hits(top, golden)) / len(golden) * 100
    pool_cov = len(hits(cand, golden)) / len(golden) * 100
    return top_cov, pool_cov, len(cand)


def main():
    token = open("/home/nikita/.rag/token").read().strip()
    n = len(SCENARIOS)
    s = {"off_t": 0.0, "off_p": 0.0, "on_t": 0.0, "on_p": 0.0, "pool": 0}
    print(f"{'#':>2}  {'OFF top15/pool':>15}   {'ON top15/pool':>15}   {'poolsz':>6}")
    print("-" * 78)
    for sid, q, golden in SCENARIOS:
        try:
            ot, op, _ = run(q, golden, token, False)
            nt, npool, psz = run(q, golden, token, True)
        except Exception as e:  # noqa: BLE001
            print(f"{sid:>2}  ERROR {e}"); continue
        s["off_t"] += ot; s["off_p"] += op; s["on_t"] += nt; s["on_p"] += npool; s["pool"] += psz
        print(f"{sid:>2}    {ot:5.0f}/{op:5.0f}        {nt:5.0f}/{npool:5.0f}        {psz:>4}")
    print("-" * 78)
    print(f"AVG   {s['off_t']/n:5.1f}/{s['off_p']/n:5.1f}        "
          f"{s['on_t']/n:5.1f}/{s['on_p']/n:5.1f}        {s['pool']/n:4.0f}")
    print(f"\n(coverage %: top15 = first page, pool = full candidate list reachable by paging; "
          f"n={n}, avg pool size shown)")


if __name__ == "__main__":
    main()
