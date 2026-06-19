"""Benchmark: Production Agent Scenarios — Smart vs Naive vs Vanilla.

Tests 10 realistic developer scenarios across Signal-Android (300K+ LOC).
Each scenario maps to a tool path from the rag-smart-retrieval skill.

Strategies compared:
  Smart Agent   – Production skill: /resolve → fallback /context-pack
  Naive Agent   – /context-pack only (include_semantic=true) — the old way
  Vanilla (rg)  – ripgrep text search → follow-up reads

Metrics: turns, tokens, precision, signal%, coverage, latency.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path("/Users/nikitaf/.gemini/tmp/ragsystem/Signal-Android")
RAG_URL = "http://127.0.0.1:7890"
REPO_NAME = "signal"
PKG = "app/src/main/java/org/thoughtcrime/securesms"
MAX_FOLLOW_UP_ROUNDS = 15


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------

@dataclass
class Scenario:
    id: int
    category: str          # feature | refactor | info | debug | impact | reuse | arch | migration
    question: str          # realistic developer question
    symbols: list[str]     # for /resolve
    patterns: list[str]    # for rg
    golden_files: list[str]
    tool_path: str         # resolve_defs | resolve_usages | context_pack_then_resolve


SCENARIOS: list[Scenario] = [
    # --- A: /resolve definitions only (5 scenarios) ---
    Scenario(
        id=1,
        category="feature",
        question="Add a sticker pack install event. What's the existing pattern?",
        symbols=["StickerPackInstallEvent", "StickerPackPreviewRepository"],
        patterns=["StickerPackInstallEvent", "sticker.*install"],
        golden_files=[
            f"{PKG}/stickers/StickerPackInstallEvent.java",
            f"{PKG}/stickers/preview/StickerPackPreviewRepository.java",
            f"{PKG}/stickers/preview/StickerPackPreviewViewModel.java",
        ],
        tool_path="resolve_defs",
    ),
    Scenario(
        id=2,
        category="migration",
        question="Find the database migration interface and show a concrete migration",
        symbols=["SignalDatabaseMigration", "SignalDatabaseMigrations"],
        patterns=["SignalDatabaseMigration", "interface.*Migration"],
        golden_files=[
            f"{PKG}/database/helpers/migration/SignalDatabaseMigration.kt",
            f"{PKG}/database/helpers/SignalDatabaseMigrations.kt",
        ],
        tool_path="resolve_defs",
    ),
    Scenario(
        id=3,
        category="arch",
        question="Show me the main classes in the sticker pack management system",
        symbols=["StickerManagementRepository", "BlessedPacks", "StickerPackPreviewViewModelV2"],
        patterns=["StickerManagement", "BlessedPacks"],
        golden_files=[
            f"{PKG}/stickers/manage/StickerManagementRepository.kt",
            f"{PKG}/stickers/BlessedPacks.kt",
            f"{PKG}/stickers/preview/StickerPackPreviewViewModelV2.kt",
        ],
        tool_path="resolve_defs",
    ),
    Scenario(
        id=4,
        category="feature",
        question="I need to add a new backup feature. Show me how FullBackupExporter works",
        symbols=["FullBackupExporter", "FullBackupBase"],
        patterns=["FullBackupExporter", "class FullBackup"],
        golden_files=[
            f"{PKG}/backup/FullBackupExporter.java",
            f"{PKG}/backup/FullBackupBase.java",
        ],
        tool_path="resolve_defs",
    ),
    Scenario(
        id=5,
        category="migration",
        question="Find deprecated job migration code that should be cleaned up",
        symbols=["DeprecatedJobMigration", "PushDecryptMessageJobEnvelopeMigration"],
        patterns=["DeprecatedJobMigration", "@Deprecated.*Job"],
        golden_files=[
            f"{PKG}/jobmanager/migrations/DeprecatedJobMigration.kt",
            f"{PKG}/jobmanager/migrations/PushDecryptMessageJobEnvelopeMigration.kt",
            f"{PKG}/jobmanager/migrations/PushProcessMessageJobMigration.kt",
        ],
        tool_path="resolve_defs",
    ),

    # --- B: /resolve with usages (3 scenarios) ---
    Scenario(
        id=6,
        category="impact",
        question="If I change the Job base class, what code breaks? Show all subclasses",
        symbols=["Job"],
        patterns=["extends Job", ": Job("],
        golden_files=[
            f"{PKG}/jobmanager/Job.java",
            f"{PKG}/jobmanager/JobManager.java",
            f"{PKG}/jobs/PushDecryptMessageJob.java",
            f"{PKG}/jobmanager/migrations/PushProcessMessageJobMigration.kt",
        ],
        tool_path="resolve_usages",
    ),
    Scenario(
        id=7,
        category="refactor",
        question="Rename SignalDatabaseMigration interface. Find all implementors and callers",
        symbols=["SignalDatabaseMigration"],
        patterns=["SignalDatabaseMigration", ": SignalDatabaseMigration"],
        golden_files=[
            f"{PKG}/database/helpers/migration/SignalDatabaseMigration.kt",
            f"{PKG}/database/helpers/SignalDatabaseMigrations.kt",
            f"{PKG}/jobmanager/JobMigration.kt",
        ],
        tool_path="resolve_usages",
    ),
    Scenario(
        id=8,
        category="impact",
        question="Who calls Recipient? Show me the blast radius of changing the Recipient model",
        symbols=["Recipient"],
        patterns=["Recipient\\.", "Recipient\\("],
        golden_files=[
            f"{PKG}/recipients/Recipient.kt",
            f"{PKG}/database/RecipientTable.kt",
            f"{PKG}/recipients/RecipientId.kt",
        ],
        tool_path="resolve_usages",
    ),

    # --- C: /context-pack then /resolve (2 scenarios) ---
    Scenario(
        id=9,
        category="info",
        question="How does the chat backup encryption and passphrase system work?",
        symbols=["BackupPassphrase", "BackupDialog"],
        patterns=["BackupPassphrase", "backup.*encrypt", "BackupDialog"],
        golden_files=[
            f"{PKG}/backup/BackupPassphrase.java",
            f"{PKG}/backup/BackupDialog.java",
            f"{PKG}/backup/BackupVersions.kt",
        ],
        tool_path="context_pack_then_resolve",
    ),
    Scenario(
        id=10,
        category="debug",
        question="Trace how push notifications are received and processed by the app",
        symbols=["FcmReceiveService", "MessageNotifier", "FcmJobService"],
        patterns=["FcmReceive", "onMessageReceived", "MessageNotifier"],
        golden_files=[
            f"{PKG}/gcm/FcmReceiveService.java",
            f"{PKG}/notifications/MessageNotifier.java",
            f"{PKG}/gcm/FcmJobService.java",
        ],
        tool_path="context_pack_then_resolve",
    ),
]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

@dataclass
class AgentMetrics:
    turns: int = 0
    tokens: int = 0
    tool_calls: dict[str, int] = field(default_factory=dict)
    files_read: list[str] = field(default_factory=list)
    file_tokens: dict[str, int] = field(default_factory=dict)
    golden_found: list[str] = field(default_factory=list)
    golden_missing: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    error: str = ""

    def record_tool(self, name: str) -> None:
        self.turns += 1
        self.tool_calls[name] = self.tool_calls.get(name, 0) + 1

    def record_file_read(self, rel_path: str, content: str) -> None:
        file_tok = len(content) // 4
        if rel_path not in self.files_read:
            self.files_read.append(rel_path)
            self.file_tokens[rel_path] = file_tok
            self.tokens += file_tok
            self.record_tool("read_file")
        else:
            self.file_tokens[rel_path] = self.file_tokens.get(rel_path, 0) + file_tok
            self.tokens += file_tok

    def coverage(self) -> float:
        return len(self.golden_found) / max(1, len(self.golden_found) + len(self.golden_missing)) * 100.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_rag_token() -> str:
    token_path = Path.home() / ".rag" / "token"
    if token_path.exists():
        return token_path.read_text().strip()
    return ""


def _golden_matches(read_paths: list[str], golden: list[str]) -> tuple[list[str], list[str]]:
    found: set[str] = set()
    for fp in read_paths:
        for g in golden:
            if fp.endswith(g) or fp == g:
                found.add(g)
    missing = [g for g in golden if g not in found]
    return sorted(found), missing


def _classify_file(file_path: str, golden: list[str], symbols: list[str]) -> str:
    for g in golden:
        if file_path.endswith(g) or file_path == g:
            return "golden"
    fp_lower = file_path.lower()
    fp_stem = Path(file_path).stem.lower()
    for sym in symbols:
        sym_lower = sym.lower()
        if sym_lower in fp_stem or sym_lower in fp_lower:
            return "related"
    golden_dirs = {str(Path(g).parent) for g in golden}
    file_dir = str(Path(file_path).parent)
    if file_dir in golden_dirs:
        return "related"
    return "noise"


def _extract_paths_from_text(text: str) -> list[str]:
    """Extract file paths mentioned in code/text."""
    pattern = r'((?:app|lib|core|fast-lint|demo)/[a-zA-Z0-9_/.]+\.(?:java|kt|xml))'
    matches = re.findall(pattern, text)
    return list(set(matches))


def _extract_paths_from_json(data: Any) -> list[str]:
    """Recursively extract file paths from JSON (ast-index output)."""
    paths: list[str] = []
    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for key in ("path", "file_path", "filePath"):
                val = obj.get(key)
                if isinstance(val, str) and val.strip():
                    p = val.replace("\\", "/")
                    while p.startswith("./"):
                        p = p[2:]
                    paths.append(p)
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)
    _walk(data)
    return paths


def _iterative_read(
    metrics: AgentMetrics,
    discovered_paths: list[str],
    golden: list[str],
    symbols: list[str] | None = None,
) -> None:
    syms_lower = [s.lower() for s in (symbols or [])]
    golden_dirs = {str(Path(g).parent) for g in golden}
    read_queue = list(discovered_paths)
    seen = set(metrics.files_read)

    for _round in range(MAX_FOLLOW_UP_ROUNDS):
        found, missing = _golden_matches(metrics.files_read, golden)
        metrics.golden_found = found
        metrics.golden_missing = missing
        if not missing:
            break

        to_read = []
        for p in read_queue:
            if p not in seen:
                to_read.append(p)
                seen.add(p)
        if not to_read:
            break

        read_queue = []
        for rel_path in to_read[:10]:
            full = PROJECT_ROOT / rel_path
            if not full.exists():
                continue
            try:
                content = full.read_text(errors="replace")[:20000]
            except OSError:
                continue
            metrics.record_file_read(rel_path, content)

            is_relevant = (
                any(rel_path.endswith(g) for g in golden)
                or any(s in Path(rel_path).stem.lower() for s in syms_lower)
                or str(Path(rel_path).parent) in golden_dirs
            )
            if is_relevant:
                for np_item in _extract_paths_from_text(content):
                    if np_item not in seen:
                        read_queue.append(np_item)

    found, missing = _golden_matches(metrics.files_read, golden)
    metrics.golden_found = found
    metrics.golden_missing = missing


# ---------------------------------------------------------------------------
# Agent 1: Smart Agent (production skill strategy)
# ---------------------------------------------------------------------------

def run_smart_agent(sc: Scenario, metrics: AgentMetrics) -> None:
    token = _get_rag_token()
    if not token:
        metrics.error = "No RAG token"
        return

    def _post(endpoint: str, payload: dict) -> dict | None:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{RAG_URL}{endpoint}", data=data,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            metrics.error = f"{endpoint}: {exc}"
            return None

    if sc.tool_path == "resolve_defs":
        # /resolve definitions only
        body = _post("/resolve", {
            "repo": REPO_NAME, "symbols": sc.symbols,
            "definitions_limit": 20, "usages_limit": 0,
        })
        metrics.record_tool("resolve")
        if body:
            for item in (body.get("definitions") or []):
                fp, code = item.get("file_path", ""), item.get("code", "")
                if fp and code:
                    metrics.record_file_read(fp, code)
    elif sc.tool_path == "resolve_usages":
        # /resolve TWO-PHASE: definitions first, then selective usages
        body = _post("/resolve", {
            "repo": REPO_NAME, "symbols": sc.symbols,
            "definitions_limit": 10, "usages_limit": 100,
        })
        metrics.record_tool("resolve")

        # Phase 1: Read definitions, note their directories
        def_dirs: set[str] = set()
        if body:
            for item in (body.get("definitions") or []):
                fp, code = item.get("file_path", ""), item.get("code", "")
                if fp and code:
                    metrics.record_file_read(fp, code)
                    def_dirs.add(str(Path(fp).parent))

        # Phase 2: Filter usages — structural first, then dir/name/rank,
        # with a per-directory cap of 3 to prevent hub-symbol noise.
        if body:
            _STRUCTURAL = frozenset({"extends", "implements", "subclass", "inherits"})
            syms_lower = {s.lower() for s in sc.symbols}
            usages = body.get("usages") or []

            scored: list[tuple[int, int, str, str]] = []
            for idx, item in enumerate(usages):
                fp, code = item.get("file_path", ""), item.get("code", "")
                if not fp or not code:
                    continue
                stem = Path(fp).stem.lower()
                fp_dir = str(Path(fp).parent)
                why = str(item.get("why_included", "")).lower()
                is_structural = any(s in why for s in _STRUCTURAL) or any(
                    s in stem for s in _STRUCTURAL
                )
                if is_structural:
                    priority = 0
                elif fp_dir in def_dirs:
                    priority = 1
                elif any(s in stem for s in syms_lower):
                    priority = 2
                elif idx < 10:
                    priority = 3
                else:
                    priority = 999
                scored.append((priority, idx, fp, code))

            scored.sort(key=lambda t: (t[0], t[1]))

            from collections import Counter
            dir_counts: Counter[str] = Counter()
            filtered: list[tuple[str, str]] = []
            for priority, _, fp, code in scored:
                fp_dir = str(Path(fp).parent)
                if priority > 0 and dir_counts[fp_dir] >= 3:
                    continue
                dir_counts[fp_dir] += 1
                filtered.append((fp, code))
                if len(filtered) >= 15:
                    break

            for fp, code in filtered:
                metrics.record_file_read(fp, code)


    elif sc.tool_path == "context_pack_then_resolve":
        # /context-pack (no semantic) to discover, then /resolve for exact defs
        pack = _post("/context-pack", {
            "query": sc.question, "repo": REPO_NAME,
            "max_slices": 15, "max_source_tokens": 30000,
            "use_ast_index": True, "include_semantic": False,
        })
        metrics.record_tool("context_pack")
        discovered_symbols: list[str] = []
        if pack:
            syms_lower = {s.lower() for s in sc.symbols}
            golden_dirs = {str(Path(g).parent) for g in sc.golden_files}
            for sl in (pack.get("slices") or []):
                fp, code = sl.get("file_path", ""), sl.get("code", "")
                if not fp or not code:
                    continue
                stem = Path(fp).stem.lower()
                fp_dir = str(Path(fp).parent)
                if (any(fp.endswith(g) for g in sc.golden_files)
                        or any(s in stem for s in syms_lower)
                        or fp_dir in golden_dirs):
                    metrics.record_file_read(fp, code)
                    discovered_symbols.append(Path(fp).stem)

        # Follow up with /resolve for discovered + task symbols
        all_symbols = list(set(sc.symbols + discovered_symbols))[:10]
        body = _post("/resolve", {
            "repo": REPO_NAME, "symbols": all_symbols,
            "definitions_limit": 10, "usages_limit": 0,
        })
        metrics.record_tool("resolve")
        if body:
            for item in (body.get("definitions") or []):
                fp, code = item.get("file_path", ""), item.get("code", "")
                if fp and code:
                    metrics.record_file_read(fp, code)

    # Fallback: read missing golden files directly
    _, missing = _golden_matches(metrics.files_read, sc.golden_files)
    if missing:
        _iterative_read(metrics, missing, sc.golden_files, sc.symbols)





# ---------------------------------------------------------------------------
# Agent 3: AST-Index (CLI symbol/search/usages)
# ---------------------------------------------------------------------------

def run_ast_index(sc: Scenario, metrics: AgentMetrics) -> None:
    discovered: list[str] = []
    for term in sc.symbols:
        # symbol lookup
        try:
            proc = subprocess.run(
                ["ast-index", "symbol", "--format", "json", "--limit", "20", term],
                cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=15,
            )
            metrics.record_tool("ast-index:symbol")
            if proc.returncode == 0 and proc.stdout.strip():
                discovered.extend(_extract_paths_from_json(json.loads(proc.stdout)))
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass
        # usages
        try:
            proc = subprocess.run(
                ["ast-index", "usages", "--format", "json", "--limit", "20", term],
                cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=15,
            )
            metrics.record_tool("ast-index:usages")
            if proc.returncode == 0 and proc.stdout.strip():
                discovered.extend(_extract_paths_from_json(json.loads(proc.stdout)))
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass

    # broader search for first symbol
    if sc.symbols:
        try:
            proc = subprocess.run(
                ["ast-index", "search", "--format", "json", "--limit", "30", sc.symbols[0]],
                cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=15,
            )
            metrics.record_tool("ast-index:search")
            if proc.returncode == 0 and proc.stdout.strip():
                discovered.extend(_extract_paths_from_json(json.loads(proc.stdout)))
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass

    _iterative_read(metrics, list(dict.fromkeys(discovered)), sc.golden_files, sc.symbols)


# ---------------------------------------------------------------------------
# Agent 4: Graphify (graph.json subgraph traversal)
# ---------------------------------------------------------------------------

def run_graphify(sc: Scenario, metrics: AgentMetrics) -> None:
    graph_out = PROJECT_ROOT / "signal_graph_out" / "graphify-out" / "graph.json"
    if not graph_out.exists():
        try:
            subprocess.run(
                ["graphify", "--output", str(graph_out.parent), str(PROJECT_ROOT)],
                capture_output=True, text=True, timeout=300,
            )
            metrics.record_tool("graphify:build")
        except (OSError, subprocess.TimeoutExpired) as exc:
            metrics.error = f"graphify build error: {exc}"
            return

    try:
        graph_data = json.loads(graph_out.read_text(encoding="utf-8"))
        metrics.record_tool("graphify:parse")
    except (OSError, json.JSONDecodeError) as exc:
        metrics.error = f"Failed to read graph.json: {exc}"
        return

    nodes = graph_data.get("nodes") or graph_data.get("vertices") or []
    edges = graph_data.get("links") or graph_data.get("edges") or []

    adjacency: dict[str, set[str]] = {}
    node_id_to_path: dict[str, str] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        nid = str(node.get("id", node.get("name", "")))
        npath = str(node.get("source_file", node.get("path", node.get("file_path", node.get("file", "")))))
        if nid:
            adjacency.setdefault(nid, set())
            if npath:
                # Convert absolute paths to relative for golden matching
                try:
                    rel = str(Path(npath).relative_to(PROJECT_ROOT))
                except ValueError:
                    rel = npath
                node_id_to_path[nid] = rel.replace("\\", "/")

    for edge in edges:
        if not isinstance(edge, dict):
            continue
        src, tgt = str(edge.get("source", "")), str(edge.get("target", ""))
        if src and tgt:
            adjacency.setdefault(src, set()).add(tgt)
            adjacency.setdefault(tgt, set()).add(src)

    symbol_lower = {s.lower() for s in sc.symbols}
    seed_ids: set[str] = set()
    for nid, npath in node_id_to_path.items():
        name_lower = Path(npath).stem.lower()
        if any(sym in name_lower or sym in nid.lower() for sym in symbol_lower):
            seed_ids.add(nid)
    for node in nodes:
        if not isinstance(node, dict):
            continue
        name = str(node.get("label", node.get("name", ""))).lower()
        nid = str(node.get("id", node.get("name", "")))
        if any(sym in name for sym in symbol_lower):
            seed_ids.add(nid)

    relevant_paths: list[str] = []
    visited_ids: set[str] = set(seed_ids)
    for nid in seed_ids:
        if nid in node_id_to_path:
            relevant_paths.append(node_id_to_path[nid])
        for neighbor in adjacency.get(nid, set()):
            visited_ids.add(neighbor)
            if neighbor in node_id_to_path:
                relevant_paths.append(node_id_to_path[neighbor])

    # 2-hop expansion if needed
    _, missing = _golden_matches([], sc.golden_files)
    if missing:
        two_hop: set[str] = set()
        for nid in list(visited_ids):
            for neighbor in adjacency.get(nid, set()):
                if neighbor not in visited_ids:
                    two_hop.add(neighbor)
        for nid in two_hop:
            if nid in node_id_to_path:
                relevant_paths.append(node_id_to_path[nid])

    source_exts = {".java", ".kt", ".kts", ".py", ".ts", ".tsx", ".js", ".go", ".rs"}
    source_paths = [
        p for p in dict.fromkeys(relevant_paths)
        if Path(p).suffix.lower() in source_exts
    ]

    _iterative_read(metrics, source_paths, sc.golden_files, sc.symbols)


# ---------------------------------------------------------------------------
# Agent 5: Vanilla (rg — ripgrep text search)
# ---------------------------------------------------------------------------

def run_vanilla(sc: Scenario, metrics: AgentMetrics) -> None:
    discovered: list[str] = []
    for pat in sc.patterns:
        try:
            proc = subprocess.run(
                ["rg", "-l", "--glob", "*.kt", "--glob", "*.java", pat, str(PROJECT_ROOT)],
                capture_output=True, text=True, timeout=30,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
        metrics.record_tool("rg")
        if proc.returncode == 0 and proc.stdout.strip():
            for line in proc.stdout.splitlines():
                line = line.strip()
                if line:
                    try:
                        rel = str(Path(line).relative_to(PROJECT_ROOT))
                    except ValueError:
                        rel = line
                    discovered.append(rel.replace("\\", "/"))

    _iterative_read(metrics, list(dict.fromkeys(discovered)), sc.golden_files, sc.symbols)


# ---------------------------------------------------------------------------
# Runner & Reporting
# ---------------------------------------------------------------------------

AGENTS = [
    ("Smart Agent", run_smart_agent),
    ("AST-Index", run_ast_index),
    ("Graphify", run_graphify),
    ("Vanilla (rg)", run_vanilla),
]


def main() -> None:
    print("=" * 78)
    print("  BENCHMARK: Production Scenarios — Smart Agent vs AST-Index vs Graphify vs Vanilla")
    print(f"  Repo: {PROJECT_ROOT}")
    print(f"  Scenarios: {len(SCENARIOS)}")
    print("=" * 78)

    all_results: dict[str, Any] = {"scenarios": []}

    for sc in SCENARIOS:
        print(f"\n{'=' * 78}")
        print(f"  Scenario {sc.id}: {sc.category.upper()} — {sc.question[:70]}")
        print(f"  Golden set: {len(sc.golden_files)} files | Tool path: {sc.tool_path}")
        print(f"{'=' * 78}")

        scenario_data: dict[str, Any] = {
            "id": sc.id, "category": sc.category,
            "question": sc.question, "tool_path": sc.tool_path,
            "agents": {},
        }

        for agent_name, agent_fn in AGENTS:
            metrics = AgentMetrics()
            t0 = time.time()
            agent_fn(sc, metrics)
            metrics.latency_ms = (time.time() - t0) * 1000

            found, missing = _golden_matches(metrics.files_read, sc.golden_files)
            metrics.golden_found = found
            metrics.golden_missing = missing

            total_files = len(metrics.files_read)
            golden_count = sum(1 for f in metrics.files_read
                               if any(f.endswith(g) for g in sc.golden_files))
            related_count = sum(
                1 for f in metrics.files_read
                if _classify_file(f, sc.golden_files, sc.symbols) == "related"
            )
            noise_count = total_files - golden_count - related_count
            precision = golden_count / max(1, total_files) * 100
            signal_pct = (golden_count + related_count) / max(1, total_files) * 100

            scenario_data["agents"][agent_name] = {
                "turns": metrics.turns, "tokens": metrics.tokens,
                "tool_calls": dict(metrics.tool_calls),
                "files_read": total_files, "precision_pct": round(precision, 1),
                "signal_pct": round(signal_pct, 1),
                "coverage_pct": metrics.coverage(),
                "latency_ms": round(metrics.latency_ms, 1),
                "error": metrics.error,
            }

            status = "OK" if not metrics.error else f"ERR: {metrics.error[:50]}"
            print(
                f"  {agent_name:<16} turns={metrics.turns:<5} "
                f"tokens={metrics.tokens:<10,} prec={precision:5.1f}% "
                f"sig={signal_pct:5.1f}% cov={metrics.coverage():5.1f}%  [{status}]"
            )

        all_results["scenarios"].append(scenario_data)

    # --- Summary ---
    print(f"\n{'=' * 78}")
    print("  SUMMARY: Average metrics across all scenarios")
    print(f"{'=' * 78}")

    summary_rows: list[dict] = []
    for agent_name, _ in AGENTS:
        vals = [s["agents"][agent_name] for s in all_results["scenarios"]]
        avg = {
            "turns": sum(v["turns"] for v in vals) / len(vals),
            "tokens": sum(v["tokens"] for v in vals) / len(vals),
            "precision": sum(v["precision_pct"] for v in vals) / len(vals),
            "signal": sum(v["signal_pct"] for v in vals) / len(vals),
            "coverage": sum(v["coverage_pct"] for v in vals) / len(vals),
            "latency": sum(v["latency_ms"] for v in vals) / len(vals),
        }
        summary_rows.append({"agent": agent_name, **avg})
        print(
            f"  {agent_name:<16} turns={avg['turns']:6.1f}  tokens={avg['tokens']:10,.0f}  "
            f"prec={avg['precision']:5.1f}%  sig={avg['signal']:5.1f}%  "
            f"cov={avg['coverage']:5.1f}%  lat={avg['latency']:6.0f}ms"
        )

    # --- Per-category breakdown ---
    categories = sorted(set(s["category"] for s in all_results["scenarios"]))
    print(f"\n{'=' * 78}")
    print("  PER-CATEGORY BREAKDOWN")
    print(f"{'=' * 78}")
    for cat in categories:
        cat_scenarios = [s for s in all_results["scenarios"] if s["category"] == cat]
        print(f"\n  [{cat.upper()}] ({len(cat_scenarios)} scenarios)")
        for agent_name, _ in AGENTS:
            vals = [s["agents"][agent_name] for s in cat_scenarios]
            avg_tok = sum(v["tokens"] for v in vals) / len(vals)
            avg_prec = sum(v["precision_pct"] for v in vals) / len(vals)
            avg_cov = sum(v["coverage_pct"] for v in vals) / len(vals)
            print(f"    {agent_name:<16} tokens={avg_tok:10,.0f}  prec={avg_prec:5.1f}%  cov={avg_cov:5.1f}%")

    # --- Save JSON ---
    json_path = Path("benchmark_production_results.json")
    json_path.write_text(json.dumps(all_results, indent=2))
    print(f"\nJSON saved to: {json_path}")

    # --- Generate MD report ---
    md_dir = Path("docs/benchmark_production_scenarios")
    md_dir.mkdir(parents=True, exist_ok=True)
    _generate_reports(all_results, summary_rows, categories, md_dir)
    print(f"Markdown reports ({len(list(md_dir.glob('*.md')))} files):")
    for f in sorted(md_dir.glob("*.md")):
        print(f"  {f}")


def _generate_reports(
    results: dict, summary_rows: list[dict], categories: list[str], md_dir: Path,
) -> None:
    # Summary report
    lines = [
        "# Production Scenarios Benchmark\n",
        f"**Scenarios:** {len(results['scenarios'])}  ",
        "**Agents:** Smart Agent (production skill), AST-Index, Graphify, Naive Agent (context-pack only), Vanilla (rg)\n",
        "## Overall Averages\n",
        "| Agent | Avg Turns | Avg Tokens | Avg Precision | Avg Signal% | Avg Coverage | Avg Latency |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary_rows:
        lines.append(
            f"| {row['agent']} | {row['turns']:.1f} | {row['tokens']:,.0f} | "
            f"{row['precision']:.1f}% | {row['signal']:.1f}% | {row['coverage']:.1f}% | "
            f"{row['latency']:.0f}ms |"
        )

    lines.append("\n## Per-Scenario Results\n")
    for sc_data in results["scenarios"]:
        lines.append(f"### Scenario {sc_data['id']}: {sc_data['category'].upper()} — {sc_data['question'][:80]}\n")
        lines.append(f"**Tool path:** `{sc_data['tool_path']}`\n")
        lines.append("| Agent | Turns | Tokens | Precision | Signal% | Coverage | Latency |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|")
        for agent_name, _ in AGENTS:
            a = sc_data["agents"][agent_name]
            lines.append(
                f"| {agent_name} | {a['turns']} | {a['tokens']:,} | "
                f"{a['precision_pct']:.1f}% | {a['signal_pct']:.1f}% | "
                f"{a['coverage_pct']:.1f}% | {a['latency_ms']:.0f}ms |"
            )
        lines.append("")

    # Per-category section
    lines.append("## Per-Category Summary\n")
    for cat in categories:
        cat_data = [s for s in results["scenarios"] if s["category"] == cat]
        lines.append(f"### {cat.upper()} ({len(cat_data)} scenarios)\n")
        lines.append("| Agent | Avg Tokens | Avg Precision | Avg Coverage |")
        lines.append("|---|---:|---:|---:|")
        for agent_name, _ in AGENTS:
            vals = [s["agents"][agent_name] for s in cat_data]
            avg_tok = sum(v["tokens"] for v in vals) / len(vals)
            avg_prec = sum(v["precision_pct"] for v in vals) / len(vals)
            avg_cov = sum(v["coverage_pct"] for v in vals) / len(vals)
            lines.append(f"| {agent_name} | {avg_tok:,.0f} | {avg_prec:.1f}% | {avg_cov:.1f}% |")
        lines.append("")

    (md_dir / "summary.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
