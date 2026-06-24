"""Benchmark: ALL retrieval tools, head-to-head, honestly.

Compares the code-retrieval tools a developer might reach for, on the same 10
Signal-Android scenarios:

  * rag-search  – the RAG Smart Agent: POST /search with the LLM planner
  * rag-resolve – the RAG symbol tool: POST /resolve (defs + usages)
  * vanilla-rg  – ripgrep text search
  * ast-index   – the ast-index CLI (symbol / usages / search)
  * graphify    – call-graph traversal over graphify's graph.json
  * serena      – Serena LSP agent (find_symbol / find_referencing_symbols)

FAIRNESS (vs the old benchmark_production_scenarios.py, which cheated):
  * Every tool receives ONLY the natural-language question. Query terms are
    derived by a SINGLE shared extractor (`extract_terms`) — NOT the golden
    symbols. No tool is handed the answer.
  * Each tool returns a ranked list of candidate files; we score that list
    (top_k) against the golden set. There is NO oracle backfill — nothing reads
    golden files off disk on a miss.
  * Metrics (coverage / precision) are computed identically for every tool.

Usage:
    rag start                                  # daemon up, signal repo indexed
    python benchmark_all_tools.py --tools rag-search,rag-resolve,vanilla-rg,ast-index
    python benchmark_all_tools.py --tools all  # includes slow serena + graphify
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path("/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android")
RAG_URL = "http://127.0.0.1:7890"
REPO_NAME = "signal"
PKG = "app/src/main/java/org/thoughtcrime/securesms"
TOP_K = 15

ALL_TOOLS = ["rag-agentic", "rag-smart", "rag-search", "rag-resolve",
             "vanilla-rg", "ast-index", "graphify", "serena"]

# Question phrasings that mean "blast radius" → use two-phase /resolve usages.
_BLAST_SIGNALS = (
    "what breaks", "who calls", "blast radius", "all usages", "usages",
    "implementors", "callers", "subclass", "impact", "depends", "references",
    "affected", "what code breaks",
)


@dataclass
class Scenario:
    id: int
    category: str
    question: str
    golden_files: list[str]


SCENARIOS: list[Scenario] = [
    Scenario(1, "feature", "Add a sticker pack install event. What's the existing pattern?", [
        f"{PKG}/stickers/StickerPackInstallEvent.java",
        f"{PKG}/stickers/preview/StickerPackPreviewRepository.java",
        f"{PKG}/stickers/preview/StickerPackPreviewViewModel.java",
    ]),
    Scenario(2, "migration", "Find the database migration interface and show a concrete migration", [
        f"{PKG}/database/helpers/migration/SignalDatabaseMigration.kt",
        f"{PKG}/database/helpers/SignalDatabaseMigrations.kt",
    ]),
    Scenario(3, "arch", "Show me the main classes in the sticker pack management system", [
        f"{PKG}/stickers/manage/StickerManagementRepository.kt",
        f"{PKG}/stickers/BlessedPacks.kt",
        f"{PKG}/stickers/preview/StickerPackPreviewViewModelV2.kt",
    ]),
    Scenario(4, "feature", "I need to add a new backup feature. Show me how FullBackupExporter works", [
        f"{PKG}/backup/FullBackupExporter.java",
        f"{PKG}/backup/FullBackupBase.java",
    ]),
    Scenario(5, "migration", "Find deprecated job migration code that should be cleaned up", [
        f"{PKG}/jobmanager/migrations/DeprecatedJobMigration.kt",
        # NOTE: this migration is a .java file, not .kt (golden audit fix).
        f"{PKG}/jobmanager/migrations/PushDecryptMessageJobEnvelopeMigration.java",
        f"{PKG}/jobmanager/migrations/PushProcessMessageJobMigration.kt",
    ]),
    Scenario(6, "impact", "If I change the Job base class, what code breaks? Show all subclasses", [
        f"{PKG}/jobmanager/Job.java",
        f"{PKG}/jobmanager/JobManager.java",
        # NOTE: PushDecryptMessageJob.java was removed from Signal — phantom golden
        # dropped in the audit (don't fabricate a replacement).
        f"{PKG}/jobmanager/migrations/PushProcessMessageJobMigration.kt",
    ]),
    Scenario(7, "refactor", "Rename SignalDatabaseMigration interface. Find all implementors and callers", [
        f"{PKG}/database/helpers/migration/SignalDatabaseMigration.kt",
        f"{PKG}/database/helpers/SignalDatabaseMigrations.kt",
        # NOTE: JobMigration.kt removed — it's the job-manager's migration base
        # ("migration on persisted Jobs"), unrelated to SignalDatabaseMigration.
    ]),
    Scenario(8, "impact", "Who calls Recipient? Show me the blast radius of changing the Recipient model", [
        f"{PKG}/recipients/Recipient.kt",
        f"{PKG}/database/RecipientTable.kt",
        f"{PKG}/recipients/RecipientId.kt",
    ]),
    Scenario(9, "info", "How does the chat backup encryption and passphrase system work?", [
        f"{PKG}/backup/BackupPassphrase.java",
        f"{PKG}/backup/BackupDialog.java",
        # NOTE: BackupVersions.kt removed — backup format version constants,
        # not part of the encryption/passphrase system.
    ]),
    Scenario(10, "debug", "Trace how push notifications are received and processed by the app", [
        f"{PKG}/gcm/FcmReceiveService.java",
        f"{PKG}/notifications/MessageNotifier.java",
        f"{PKG}/gcm/FcmJobService.java",
    ]),
]


# ---------------------------------------------------------------------------
# Shared query-term extraction (identical input for every symbol tool)
# ---------------------------------------------------------------------------

_STOP = {
    "show", "find", "add", "trace", "list", "give", "tell", "rename", "need",
    "what", "which", "where", "when", "who", "whom", "whose", "how", "why",
    "this", "that", "these", "those", "there", "here", "with", "from", "into",
    "your", "their", "have", "does", "code", "class", "base", "main", "should",
    "would", "could", "about", "system", "work", "works", "concrete", "show",
    "existing", "pattern", "interface", "model", "feature", "breaks", "change",
    "cleaned", "deprecated", "received", "processed", "implementors", "callers",
    "subclasses", "blast", "radius", "changing", "install", "event", "manage",
    "management", "the", "and", "all", "new", "for",
}


def extract_terms(question: str) -> tuple[list[str], list[str]]:
    """Return (symbol_terms, keyword_terms) — the SAME for every tool.

    symbol_terms : CamelCase / identifier-looking tokens (>=3 chars, e.g. Job,
                   Recipient, FullBackupExporter) that a dev would search for.
    keyword_terms: salient lowercase words, used when no symbols are present
                   (e.g. "sticker pack install" style questions).
    """
    symbols: list[str] = []
    for w in re.findall(r"\b([A-Z][a-zA-Z0-9_]{2,})\b", question):
        if w.lower() not in _STOP and w not in symbols:
            symbols.append(w)
    keywords: list[str] = []
    for w in re.findall(r"\b([a-z][a-z]{3,})\b", question.lower()):
        if w not in _STOP and w not in keywords:
            keywords.append(w)
    return symbols, keywords


def search_terms(question: str) -> list[str]:
    """The query terms a symbol/text tool gets: symbols if any, else keywords."""
    symbols, keywords = extract_terms(question)
    return symbols if symbols else keywords[:4]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

@dataclass
class ToolResult:
    files: list[str] = field(default_factory=list)   # ranked, distinct, capped
    golden_hits: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    detail: str = ""
    error: str = ""

    def score(self, golden: list[str]) -> None:
        hits = []
        for g in golden:
            if any(f == g or f.endswith(g) or g.endswith(f) for f in self.files):
                hits.append(g)
        self.golden_hits = hits

    def coverage(self, golden: list[str]) -> float:
        return len(self.golden_hits) / max(1, len(golden)) * 100.0

    def precision(self) -> float:
        return len(self.golden_hits) / max(1, len(self.files)) * 100.0


def _rel(path: str) -> str:
    p = path.replace("\\", "/")
    try:
        return str(Path(p).relative_to(PROJECT_ROOT))
    except ValueError:
        while p.startswith("./"):
            p = p[2:]
        return p


def _cap(files: list[str]) -> list[str]:
    out: list[str] = []
    for f in files:
        r = _rel(f)
        if r and r not in out:
            out.append(r)
        if len(out) >= TOP_K:
            break
    return out


def _extract_paths_from_json(data: Any) -> list[str]:
    paths: list[str] = []

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for key in ("path", "file_path", "filePath", "relative_path", "source_file", "file"):
                val = obj.get(key)
                if isinstance(val, str) and val.strip():
                    paths.append(val)
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(data)
    return paths


# ---------------------------------------------------------------------------
# Tool drivers — each returns a ToolResult (ranked file list, no oracle)
# ---------------------------------------------------------------------------

def _get_token() -> str:
    p = Path.home() / ".rag" / "token"
    return p.read_text().strip() if p.exists() else ""


def _post(endpoint: str, payload: dict, token: str) -> dict | None:
    req = urllib.request.Request(
        f"{RAG_URL}{endpoint}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=150) as resp:
        return json.loads(resp.read().decode())


def run_rag_agentic(sc: Scenario, token: str) -> ToolResult:
    """The agentic retrieval loop = your design, via the real /smart-search
    endpoint: LLM infers symbols → exact /resolve (defs + trimmed usages) →
    semantic complement → golden data. Files are collected definitions-first,
    then usages, then semantic (precision-first ordering), capped to top_k.
    """
    t0 = time.time()
    try:
        data = _post("/smart-search", {
            "question": sc.question, "repo": REPO_NAME, "top_k": TOP_K,
        }, token)
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        return ToolResult(error=str(e), latency_ms=(time.time() - t0) * 1000)
    files: list[str] = []
    for bucket in ("definitions", "usages", "related", "semantic"):
        for item in (data or {}).get(bucket, []):
            fp = item.get("file_path", "")
            if fp:
                files.append(fp)
    syms = (data or {}).get("inferred_symbols", [])
    return ToolResult(files=_cap(files), latency_ms=(time.time() - t0) * 1000,
                      detail=f"agy_symbols={syms[:3]}")


def run_rag_smart(sc: Scenario, token: str) -> ToolResult:
    """The rag-smart-retrieval SKILL, encoded: orchestrate the rag tools.

    Decision tree (from skills/rag-smart-retrieval/SKILL.md), driven from the
    NL question only — symbols are extracted by the shared extractor, NEVER
    handed in from golden:

      1. symbols in question → /resolve definitions (the skill's primary tool).
         If the question is a blast-radius question → two-phase usages:
         pull usages_limit=100, then keep only same-dir / symbol-in-filename /
         first-10 usages (max 15).
      2. no symbols, or too few defs → /context-pack (include_semantic=false),
         extract symbols from the returned slices, loop back to /resolve once.

    Files are collected definitions-first (most precise), then filtered usages,
    then context-pack slices; capped to top_k. No oracle backfill.
    """
    t0 = time.time()
    symbols, keywords = extract_terms(sc.question)
    q = sc.question.lower()
    want_usages = any(sig in q for sig in _BLAST_SIGNALS)
    files: list[str] = []
    notes: list[str] = []
    try:
        if symbols:
            data = _post("/resolve", {
                "repo": REPO_NAME, "symbols": symbols[:6],
                "definitions_limit": 20, "usages_limit": 100 if want_usages else 0,
            }, token)
            def_dirs: set[str] = set()
            for item in (data or {}).get("definitions", []):
                fp = item.get("file_path", "")
                if fp:
                    files.append(fp)
                    def_dirs.add(str(Path(fp).parent))
            if want_usages:
                syms_lower = {s.lower() for s in symbols}
                picked: list[str] = []
                for idx, item in enumerate((data or {}).get("usages", [])):
                    fp = item.get("file_path", "")
                    if not fp:
                        continue
                    stem = Path(fp).stem.lower()
                    if (str(Path(fp).parent) in def_dirs
                            or any(s in stem for s in syms_lower) or idx < 10):
                        picked.append(fp)
                    if len(picked) >= 15:
                        break
                files.extend(picked)
            notes.append(f"resolve(syms={symbols[:4]}, usages={'Y' if want_usages else 'N'})")

        distinct = len({_rel(f) for f in files})
        if not symbols or distinct < 2:
            pack = _post("/context-pack", {
                "query": sc.question, "repo": REPO_NAME, "max_slices": 15,
                "max_source_tokens": 30000, "use_ast_index": True, "include_semantic": False,
            }, token)
            discovered = []
            for sl in (pack or {}).get("slices", []):
                fp = sl.get("file_path", "")
                if fp:
                    files.append(fp)
                    discovered.append(Path(fp).stem)
            if discovered:
                data2 = _post("/resolve", {
                    "repo": REPO_NAME, "symbols": list(dict.fromkeys(discovered))[:8],
                    "definitions_limit": 10, "usages_limit": 0,
                }, token)
                for item in (data2 or {}).get("definitions", []):
                    fp = item.get("file_path", "")
                    if fp:
                        files.append(fp)
            notes.append("context_pack_fallback")
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        return ToolResult(error=str(e), latency_ms=(time.time() - t0) * 1000)
    return ToolResult(files=_cap(files), latency_ms=(time.time() - t0) * 1000,
                      detail="; ".join(notes))


def run_rag_search(sc: Scenario, token: str) -> ToolResult:
    t0 = time.time()
    try:
        data = _post("/search", {
            "query": sc.question, "repo": REPO_NAME, "top_k": TOP_K, "planner": "llm",
        }, token)
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        return ToolResult(error=str(e), latency_ms=(time.time() - t0) * 1000)
    files = [r.get("file_path", "") for r in (data or {}).get("results", [])]
    plan = (data or {}).get("plan") or {}
    return ToolResult(
        files=_cap(files), latency_ms=(time.time() - t0) * 1000,
        detail=f"strategy={plan.get('strategy')} nq={len(plan.get('queries', []))}",
    )


def run_rag_resolve(sc: Scenario, token: str) -> ToolResult:
    t0 = time.time()
    terms = search_terms(sc.question)
    try:
        data = _post("/resolve", {
            "repo": REPO_NAME, "symbols": terms,
            "definitions_limit": 15, "usages_limit": 30,
        }, token)
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        return ToolResult(error=str(e), latency_ms=(time.time() - t0) * 1000)
    files = []
    for bucket in ("definitions", "usages"):
        for item in (data or {}).get(bucket, []):
            fp = item.get("file_path", "")
            if fp:
                files.append(fp)
    return ToolResult(files=_cap(files), latency_ms=(time.time() - t0) * 1000,
                      detail=f"terms={terms}")


def run_vanilla_rg(sc: Scenario, token: str) -> ToolResult:
    t0 = time.time()
    terms = search_terms(sc.question)
    discovered: list[str] = []
    for term in terms:
        try:
            proc = subprocess.run(
                ["rg", "-l", "--glob", "*.kt", "--glob", "*.java", term, str(PROJECT_ROOT)],
                capture_output=True, text=True, timeout=30,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
        if proc.returncode == 0:
            discovered.extend(line.strip() for line in proc.stdout.splitlines() if line.strip())
    return ToolResult(files=_cap(discovered), latency_ms=(time.time() - t0) * 1000,
                      detail=f"terms={terms}")


def run_ast_index(sc: Scenario, token: str) -> ToolResult:
    t0 = time.time()
    terms = search_terms(sc.question)
    discovered: list[str] = []
    for term in terms[:4]:
        for sub in ("symbol", "usages"):
            try:
                proc = subprocess.run(
                    ["ast-index", sub, "--format", "json", "--limit", "20", term],
                    cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=20,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    discovered.extend(_extract_paths_from_json(json.loads(proc.stdout)))
            except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
                pass
    if terms:
        try:
            proc = subprocess.run(
                ["ast-index", "search", "--format", "json", "--limit", "30", terms[0]],
                cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=20,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                discovered.extend(_extract_paths_from_json(json.loads(proc.stdout)))
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass
    return ToolResult(files=_cap(discovered), latency_ms=(time.time() - t0) * 1000,
                      detail=f"terms={terms}")


_GRAPH_CACHE: dict[str, Any] = {}


def run_graphify(sc: Scenario, token: str) -> ToolResult:
    t0 = time.time()
    graph_path = PROJECT_ROOT / "signal_graph_out" / "graphify-out" / "graph.json"
    if not graph_path.exists():
        return ToolResult(error="graph.json not found", latency_ms=(time.time() - t0) * 1000)
    if "graph" not in _GRAPH_CACHE:
        try:
            _GRAPH_CACHE["graph"] = json.loads(graph_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, MemoryError) as e:
            return ToolResult(error=f"graph load: {e}", latency_ms=(time.time() - t0) * 1000)
    g = _GRAPH_CACHE["graph"]
    nodes = g.get("nodes") or g.get("vertices") or []
    edges = g.get("links") or g.get("edges") or []

    node_path: dict[str, str] = {}
    for n in nodes:
        if not isinstance(n, dict):
            continue
        nid = str(n.get("id", n.get("name", "")))
        npath = str(n.get("source_file", n.get("path", n.get("file_path", n.get("file", "")))))
        if nid and npath:
            node_path[nid] = _rel(npath)

    adj: dict[str, set[str]] = {}
    for e in edges:
        if not isinstance(e, dict):
            continue
        s, t = str(e.get("source", "")), str(e.get("target", ""))
        if s and t:
            adj.setdefault(s, set()).add(t)
            adj.setdefault(t, set()).add(s)

    terms_lower = {t.lower() for t in search_terms(sc.question)}
    seeds = {nid for nid, p in node_path.items()
             if any(t in Path(p).stem.lower() or t in nid.lower() for t in terms_lower)}
    discovered: list[str] = []
    visited = set(seeds)
    for nid in seeds:
        if nid in node_path:
            discovered.append(node_path[nid])
        for nb in adj.get(nid, set()):
            visited.add(nb)
            if nb in node_path:
                discovered.append(node_path[nb])
    exts = {".java", ".kt", ".kts"}
    discovered = [p for p in discovered if Path(p).suffix.lower() in exts]
    return ToolResult(files=_cap(discovered), latency_ms=(time.time() - t0) * 1000,
                      detail=f"seeds={len(seeds)}")


_SERENA: dict[str, Any] = {}
SERENA_SERVER = "http://127.0.0.1:7899"


def _serena_warm_lookup(sym: str) -> str | None:
    """Query the warm serena server (tools/serena_server.py). None if unusable."""
    try:
        req = urllib.request.Request(
            f"{SERENA_SERVER}/find_symbol",
            data=json.dumps({"name": sym}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            return (json.loads(resp.read().decode()) or {}).get("result")
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None


def _serena_warm_ready() -> bool:
    try:
        with urllib.request.urlopen(f"{SERENA_SERVER}/health", timeout=3) as resp:
            return bool((json.loads(resp.read().decode()) or {}).get("ready"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return False


def run_serena(sc: Scenario, token: str) -> ToolResult:
    t0 = time.time()
    use_warm = _serena_warm_ready()
    if not use_warm and "agent" not in _SERENA:
        # No warm server — boot in-process (the slow ~4min path).
        try:
            from serena.agent import SerenaAgent
            agent = SerenaAgent(project=str(PROJECT_ROOT))
            agent.execute_task(lambda: None, name="WaitForLspInit")
            _SERENA["agent"] = agent
        except Exception as e:
            return ToolResult(error=f"serena init: {e}", latency_ms=(time.time() - t0) * 1000)
    find_symbol = None if use_warm else _SERENA["agent"].get_tool_by_name("find_symbol")

    discovered: list[str] = []
    for sym in search_terms(sc.question):
        try:
            res = (_serena_warm_lookup(sym) if use_warm
                   else find_symbol.apply(name_path_pattern=sym, include_body=False))
            if res and res.strip():
                discovered.extend(_extract_paths_from_json(json.loads(res)))
        except Exception:
            pass
    return ToolResult(files=_cap(discovered), latency_ms=(time.time() - t0) * 1000,
                      detail="warm" if use_warm else "in-process")


DRIVERS: dict[str, Callable[[Scenario, str], ToolResult]] = {
    "rag-agentic": run_rag_agentic,
    "rag-smart": run_rag_smart,
    "rag-search": run_rag_search,
    "rag-resolve": run_rag_resolve,
    "vanilla-rg": run_vanilla_rg,
    "ast-index": run_ast_index,
    "graphify": run_graphify,
    "serena": run_serena,
}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tools", default="rag-smart,rag-search,rag-resolve,vanilla-rg,ast-index",
                    help="Comma list or 'all'. Slow: graphify (1GB graph), serena (~4min boot).")
    args = ap.parse_args()
    tools = ALL_TOOLS if args.tools == "all" else [t.strip() for t in args.tools.split(",")]
    tools = [t for t in tools if t in DRIVERS]

    token = _get_token()
    if not token:
        raise SystemExit("No RAG token at ~/.rag/token.")
    try:
        urllib.request.urlopen(f"{RAG_URL}/health", timeout=5).read()
    except Exception as e:
        raise SystemExit(f"Daemon not reachable ({e}). Run `rag start`.")

    print("=" * 92)
    print(f"  BENCHMARK: all tools — {', '.join(tools)}")
    print(f"  Input: NL question only, shared term extractor, top_k={TOP_K}, no oracle.")
    print("=" * 92)

    results: dict = {"top_k": TOP_K, "tools": tools, "scenarios": []}
    for sc in SCENARIOS:
        print(f"\nS{sc.id} [{sc.category}] {sc.question[:60]}  (golden={len(sc.golden_files)})")
        entry: dict = {"id": sc.id, "category": sc.category, "question": sc.question,
                       "golden_count": len(sc.golden_files), "tools": {}}
        for tool in tools:
            r = DRIVERS[tool](sc, token)
            r.score(sc.golden_files)
            entry["tools"][tool] = {
                "files": r.files, "n_files": len(r.files),
                "golden_hits": len(r.golden_hits), "golden_found": r.golden_hits,
                "coverage_pct": round(r.coverage(sc.golden_files), 1),
                "precision_pct": round(r.precision(), 1),
                "latency_ms": round(r.latency_ms, 1), "detail": r.detail, "error": r.error,
            }
            tag = ("ERR " + r.error[:32]) if r.error else "OK"
            print(f"    {tool:<12} hit={len(r.golden_hits)}/{len(sc.golden_files)} "
                  f"files={len(r.files):<3} cov={r.coverage(sc.golden_files):5.1f}% "
                  f"prec={r.precision():5.1f}% lat={r.latency_ms:7.0f}ms [{tag}]")
        results["scenarios"].append(entry)

    # Cleanup serena LSP servers if booted.
    if "agent" in _SERENA:
        try:
            _SERENA["agent"].on_shutdown()
        except Exception:
            pass

    print(f"\n{'=' * 92}\n  AVERAGES\n{'=' * 92}")
    summary: dict = {}
    for tool in tools:
        vals = [s["tools"][tool] for s in results["scenarios"]]
        ok = [v for v in vals if not v["error"]]
        n = max(1, len(ok))
        golden_total = sum(s["golden_count"] for s in results["scenarios"])
        golden_hits = sum(v["golden_hits"] for v in vals)
        total_files = sum(v["n_files"] for v in vals)
        summary[tool] = {
            "golden_hits": golden_hits,
            "golden_total": golden_total,
            "total_files": total_files,
            # Overall precision/coverage over the whole pool (not avg-of-ratios).
            "precision_overall": (golden_hits / total_files * 100) if total_files else 0.0,
            "coverage_overall": (golden_hits / golden_total * 100) if golden_total else 0.0,
            "coverage": sum(v["coverage_pct"] for v in ok) / n if ok else 0.0,
            "precision": sum(v["precision_pct"] for v in ok) / n if ok else 0.0,
            "files": sum(v["n_files"] for v in ok) / n if ok else 0.0,
            "latency": sum(v["latency_ms"] for v in ok) / n if ok else 0.0,
            "errors": len(vals) - len(ok),
        }
        s = summary[tool]
        print(f"  {tool:<12} found={s['golden_hits']:2d}/{s['golden_total']} golden  "
              f"of {s['total_files']:3d} files returned  "
              f"(coverage={s['coverage_overall']:4.1f}%  precision={s['precision_overall']:4.1f}%)  "
              f"lat={s['latency']:6.0f}ms")
    results["summary"] = summary

    Path("benchmark_all_tools_results.json").write_text(json.dumps(results, indent=2))
    print("\nJSON saved to: benchmark_all_tools_results.json")
    _write_report(results)


def _write_report(results: dict) -> None:
    md_dir = Path("docs/benchmark_all_tools")
    md_dir.mkdir(parents=True, exist_ok=True)
    L = [
        "# All-Tools Retrieval Benchmark\n",
        "Every tool gets only the natural-language question; query terms come "
        "from a single shared extractor (not golden symbols). Each tool's "
        "top-K candidate files are scored against the golden set. No oracle "
        "backfill.\n",
        f"**top_k:** {results['top_k']}  |  **tools:** {', '.join(results['tools'])}\n",
        "## Averages\n",
        "Golden found = golden files retrieved out of the whole pool. "
        "Coverage = golden found / golden pool. Precision = golden found / files returned.\n",
        "| Tool | Golden Found | Files Returned | Coverage | Precision | Avg Latency |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for tool, s in results["summary"].items():
        L.append(
            f"| {tool} | {s['golden_hits']}/{s['golden_total']} | {s['total_files']} | "
            f"{s['coverage_overall']:.1f}% | {s['precision_overall']:.1f}% | {s['latency']:.0f}ms |"
        )
    L.append("\n## Per-scenario\n")
    for sc in results["scenarios"]:
        L.append(f"### S{sc['id']} [{sc['category']}] — {sc['question']}\n")
        L.append(f"Golden: {sc['golden_count']} files\n")
        L.append("| Tool | Files | Golden Hit | Coverage | Precision | Latency |")
        L.append("|---|---:|---:|---:|---:|---:|")
        for tool, t in sc["tools"].items():
            L.append(f"| {tool} | {t['n_files']} | {t['golden_hits']}/{sc['golden_count']} | "
                     f"{t['coverage_pct']:.1f}% | {t['precision_pct']:.1f}% | {t['latency_ms']:.0f}ms |")
        L.append("")
    (md_dir / "summary.md").write_text("\n".join(L))
    print(f"Markdown report: {md_dir / 'summary.md'}")


if __name__ == "__main__":
    main()
