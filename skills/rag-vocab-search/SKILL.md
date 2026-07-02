---
name: rag-vocab-search
description: Use when answering a question about an indexed repo needs the RIGHT files with minimal tokens — especially vague concept questions ("where are push notifications handled?") where you don't know the exact symbol. Drives /smart-search's lazy, paginated retrieval: scan links first, read full bodies only for what you pick.
metadata:
  short-description: Lazy, paginated code retrieval — scan links, read only what you need
---

# Vocab-anchored lazy retrieval

Fetch code context from a RAG-indexed repo while reading **as few full files as possible**.
One `/smart-search` call returns the trustworthy baseline PLUS a project-vocabulary
anchor layer PLUS a paginated link list. You scan the cheap parts first and read full
bodies only for the files you actually decide you need.

Benchmarked on Signal-Android (10 scenarios): vocab + pagination lifts reachable
coverage from 60% → 73% with **no regressions**, and cracks vague concept questions
(e.g. "deprecated job migration code" went 0% → 100% reachable).

## The one call

```bash
rag smart-search "<natural language question>" --repo <repo> --links-only
# cross-repo: --repos repoA,repoB   or   --all-repos   (items carry a repo tag)
# paging:     --offset 25 --limit 25
# raw JSON:   --json
```

(The CLI is a thin client for `POST /smart-search`; prefer it over hand-built
HTTP calls — fewer tokens, and `--links-only` strips code bodies so the first
pass is links + summaries only.)

Response fields, cheapest-to-richest:

| field | cost | what it is |
|---|---|---|
| `vocab_anchors` | tiny | symbol stems the summary layer matched to your question |
| `vocab_files` | small | concept→symbol anchors: `{file_path, name, summary, score}` — **read the summary, not the file** |
| `candidates` | small | the paginated "show more" pool — LINKS only `{file_path, name, lines, source}`, no code |
| `candidates_total` | — | full pool size; page with `candidate_offset` |
| `definitions` / `usages` | large | exact bodies (full code) — only when an exact symbol resolved |
| `related` / `semantic` | medium | structural + vector neighbors |

## The loop (minimize full-file reads)

1. **Search** with the NL question (offset 0).
2. **Scan the cheap signals first** — `vocab_anchors`, `vocab_files[].summary`, and the
   `candidates` links. Do NOT read file bodies yet. The summaries usually tell you which
   files matter.
3. **Decide** which files are actually relevant to the task.
4. **Read full text only for those** — use `Read` on the `file_path`, or `/resolve` for
   the exact symbol's definition/usages. This is the only step that spends real tokens.
5. **Need more?** If the picked files left a gap, page the candidate list:
   re-run with `--offset <offset + limit>` (the golden file is often beyond
   the first 15 — `candidates_total` tells you how many remain). Repeat from step 2.
6. **Stop** as soon as the read files answer the question.

## When to trust what

- **Vague concept question, unknown symbol** ("how does X work / where is Y handled") →
  lean on `vocab_files`: its summaries bridge concept→symbol where vector search buries
  the canonical file.
- **Question already names an exact symbol** ("rename SignalDatabaseMigration", "who calls
  Recipient") → trust `definitions`/`related` first; `vocab_files` is a bonus, not the lead.
- **Blast-radius question** ("what breaks if I change X") → `usages` + `related` carry it;
  the endpoint auto-pulls usages for these phrasings.

## Rules

- Never read a file body to *decide relevance* — that's what `lines`, `name`, and the vocab
  `summary` are for. Read bodies only to *use* the content.
- Page before you re-search. A second `/smart-search` re-runs inference + embedding (~10–25s);
  paging `--offset` is free and deterministic.
- Start with `--links-only`; drop it only when you already know you want bodies inline.
- Cross-repo questions ("which of my repos handles X?") → one call with `--all-repos`
  instead of N sequential searches.
- `vocab_files` is additive and never reshapes the baseline — treat it as an extra lead list,
  not a replacement for `definitions`/`related`.
