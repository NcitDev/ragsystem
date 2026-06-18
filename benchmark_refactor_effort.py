"""Benchmark: Compare 4 code-retrieval agents across 6 refactoring tasks.

Each task is designed to highlight a different retrieval strength:
  1. Semantic architecture  → RAG+AST advantage
  2. Exact symbol lookup    → AST-Index advantage
  3. Push notification flow  → RAG+AST (semantic flow understanding)
  4. DI wiring               → AST-Index (symbol resolution)
  5. Blast radius analysis   → Graphify (graph neighbor traversal)
  6. Annotation scavenging   → Vanilla/rg (literal text patterns)

Agents:
  RAG+AST   – /context-pack (full code slices, semantic + AST)
  AST-Index  – ast-index CLI (symbol/search/usages → follow-up reads)
  Graphify   – graph.json (focused subgraph traversal → follow-up reads)
  Vanilla    – ripgrep (text patterns → follow-up reads)

Metrics: turns, tokens (chars/4), tool_calls, golden-set coverage.
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
MAX_FOLLOW_UP_ROUNDS = 20


# ---------------------------------------------------------------------------
# Task definitions
# ---------------------------------------------------------------------------

@dataclass
class Task:
    id: str
    name: str
    query: str                        # natural-language query for RAG
    symbols: list[str]                # symbols for AST-Index
    patterns: list[str]               # regex/literal patterns for ripgrep
    golden_files: list[str]           # relative paths that MUST be in context


TASKS: list[Task] = [
    Task(
        id="1",
        name="Refactor JobManager (Semantic)",
        query="Refactor JobManager: understand how jobs are scheduled and executed",
        symbols=["JobManager", "Job"],
        patterns=["JobManager", "class Job "],
        golden_files=[
            f"{PKG}/jobmanager/JobManager.java",
            f"{PKG}/jobmanager/Job.java",
            f"{PKG}/dependencies/AppDependencies.kt",
            f"{PKG}/AppInitialization.java",
        ],
    ),
    Task(
        id="2",
        name="Database Migration Logic (Symbol)",
        query="Find database migration infrastructure and a specific migration",
        symbols=["SignalDatabaseMigration", "MigrationJob", "JobMigration"],
        patterns=["SignalDatabaseMigration", "MigrationJob"],
        golden_files=[
            f"{PKG}/database/helpers/migration/SignalDatabaseMigration.kt",
            f"{PKG}/migrations/MigrationJob.java",
            f"{PKG}/jobmanager/JobMigration.kt",
        ],
    ),
    Task(
        id="3",
        name="Push Notification Pipeline (Flow)",
        query="Trace how Signal receives and processes push notifications from FCM to message decryption",
        symbols=["FcmFetchManager", "PushProcessMessageJob", "MessageFetchJob"],
        patterns=["FcmFetchManager", "PushProcessMessageJob", "MessageFetchJob"],
        golden_files=[
            f"{PKG}/gcm/FcmFetchManager.kt",
            f"{PKG}/jobs/PushProcessMessageJob.kt",
            f"{PKG}/jobs/MessageFetchJob.java",
            f"{PKG}/messages/IncomingMessageObserver.kt",
        ],
    ),
    Task(
        id="4",
        name="Dependency Injection Wiring (Symbols)",
        query="How does Signal wire its dependencies? Find the DI container and provider modules",
        symbols=["AppDependencies", "ApplicationDependencyProvider", "NetworkDependenciesModule"],
        patterns=["AppDependencies", "ApplicationDependencyProvider", "NetworkDependenciesModule"],
        golden_files=[
            f"{PKG}/dependencies/AppDependencies.kt",
            f"{PKG}/dependencies/ApplicationDependencyProvider.java",
            f"{PKG}/dependencies/NetworkDependenciesModule.kt",
        ],
    ),
    Task(
        id="5",
        name="Blast Radius: Job Base Class (Graph)",
        query="If I change the Job base class, what code is affected? Show Job subclasses and the job manager",
        symbols=["BaseJob", "Job", "JobManager", "CoroutineJob"],
        patterns=["extends BaseJob", ": BaseJob", "extends Job "],
        golden_files=[
            f"{PKG}/jobmanager/Job.java",
            f"{PKG}/jobmanager/JobManager.java",
            f"{PKG}/jobs/BaseJob.java",
            f"{PKG}/jobmanager/CoroutineJob.kt",
        ],
    ),
    Task(
        id="6",
        name="Deprecated Job Migrations (Text)",
        query="Find deprecated job migration code that needs cleanup",
        symbols=["DeprecatedJobMigration", "PushDecryptMessageJobEnvelopeMigration"],
        patterns=["@Deprecated", "DeprecatedJobMigration", "PushDecryptMessageJobEnvelopeMigration"],
        golden_files=[
            f"{PKG}/jobmanager/migrations/DeprecatedJobMigration.kt",
            f"{PKG}/jobmanager/migrations/PushDecryptMessageJobEnvelopeMigration.java",
            f"{PKG}/jobmanager/migrations/PushProcessMessageJobMigration.kt",
        ],
    ),
]


# ---------------------------------------------------------------------------
# Metrics tracking
# ---------------------------------------------------------------------------

@dataclass
class AgentMetrics:
    agent_name: str
    task_id: str = ""
    turns: int = 0
    tokens: int = 0
    tool_calls: dict[str, int] = field(default_factory=dict)
    files_read: list[str] = field(default_factory=list)
    file_tokens: dict[str, int] = field(default_factory=dict)  # per-file token counts
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
            self.record_tool("read_file")  # count turn only for NEW files
        else:
            # Already read this file – accumulate tokens but don't count a turn
            self.file_tokens[rel_path] = self.file_tokens.get(rel_path, 0) + file_tok
            self.tokens += file_tok

    def coverage(self) -> float:
        return len(self.golden_found) / max(1, len(self.golden_found) + len(self.golden_missing)) * 100.0


# ---------------------------------------------------------------------------
# Relevance classification
# ---------------------------------------------------------------------------

def _classify_file(
    file_path: str, golden: list[str], symbols: list[str],
) -> str:
    """Classify a read file as golden / related / noise."""
    for g in golden:
        if file_path.endswith(g) or file_path == g:
            return "golden"
    fp_lower = file_path.lower()
    fp_stem = Path(file_path).stem.lower()
    for sym in symbols:
        sym_lower = sym.lower()
        if sym_lower in fp_stem or sym_lower in fp_lower:
            return "related"
    # Same package as any golden file
    golden_dirs = {str(Path(g).parent) for g in golden}
    file_dir = str(Path(file_path).parent)
    if file_dir in golden_dirs:
        return "related"
    return "noise"


def _build_file_detail(
    metrics: AgentMetrics, golden: list[str], symbols: list[str],
) -> list[dict[str, Any]]:
    """Build per-file detail list with relevance tags."""
    detail: list[dict[str, Any]] = []
    for fp in metrics.files_read:
        cat = _classify_file(fp, golden, symbols)
        detail.append({
            "file": fp,
            "tokens": metrics.file_tokens.get(fp, 0),
            "relevance": cat,
        })
    return detail


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_rag_token() -> str:
    token_path = Path.home() / ".rag" / "token"
    try:
        return token_path.read_text().strip()
    except OSError:
        return ""


def _estimate_tokens(text: str) -> int:
    return len(text) // 4


def _read_file(abs_path: Path) -> str:
    try:
        return abs_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _extract_paths_from_text(text: str) -> list[str]:
    pattern = r"(?:^|[\s\"'])([\w./\\-]+\.(?:java|kt|kts|py|ts|tsx|js|jsx|go|rs|c|cpp|h|hpp|dart))"
    matches = re.findall(pattern, text)
    cleaned: list[str] = []
    for m in matches:
        p = m.replace("\\", "/")
        while p.startswith("./"):
            p = p[2:]
        cleaned.append(p)
    return list(dict.fromkeys(cleaned))


def _extract_paths_from_json(data: Any) -> list[str]:
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
    return list(dict.fromkeys(paths))


def _golden_matches(read_paths: list[str], golden: list[str]) -> tuple[list[str], list[str]]:
    found: set[str] = set()
    for fp in read_paths:
        for g in golden:
            if fp.endswith(g) or fp == g:
                found.add(g)
    missing = [g for g in golden if g not in found]
    return sorted(found), missing


def _iterative_read(
    metrics: AgentMetrics,
    discovered_paths: list[str],
    golden: list[str],
    symbols: list[str] | None = None,
) -> None:
    """Read discovered files, prioritizing golden targets, until coverage is complete.

    Only extracts new follow-up paths from golden/related files to prevent
    noise cascades (reading noise -> finding more noise paths -> reading those).
    """
    read_queue: list[str] = list(discovered_paths)
    seen: set[str] = set()
    golden_dirs = {str(Path(g).parent) for g in golden}
    syms_lower = {s.lower() for s in (symbols or [])}

    for _round in range(MAX_FOLLOW_UP_ROUNDS):
        found, missing = _golden_matches(metrics.files_read, golden)
        metrics.golden_found = found
        metrics.golden_missing = missing
        if not missing:
            break

        priority: list[str] = []
        for g in missing:
            if g not in seen:
                priority.append(g)
        for p in read_queue:
            if p not in seen:
                priority.append(p)
        read_queue = []

        if not priority:
            break

        for rel_path in priority:
            seen.add(rel_path)
            content = _read_file(PROJECT_ROOT / rel_path)
            if not content:
                continue
            metrics.record_file_read(rel_path, content)

            # Only extract follow-up paths from relevant files
            # (golden or symbol-matching), not from noise
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
# Agent 1: RAG+AST  (context-pack – returns full code slices)
# ---------------------------------------------------------------------------

def run_rag_ast(task: Task, metrics: AgentMetrics) -> None:
    """Lean RAG agent: one /resolve call for exact definitions only.
    Returns only the files where symbols are defined — no usages, no noise.
    Falls back to /context-pack (strict filter) only if /resolve misses targets."""
    token = _get_rag_token()
    if not token:
        metrics.error = "No RAG token at ~/.rag/token"
        return

    def _rag_post(endpoint: str, payload: dict) -> dict | None:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{RAG_URL}{endpoint}",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            metrics.error = f"{endpoint} failed: {exc}"
            return None

    # --- Single call: /resolve for definitions ONLY (no usages) ---
    resolve_body = _rag_post("/resolve", {
        "repo": REPO_NAME,
        "symbols": task.symbols,
        "definitions_limit": 20,
        "usages_limit": 0,
    })
    metrics.record_tool("resolve")
    if resolve_body:
        for item in (resolve_body.get("definitions") or []):
            fp = item.get("file_path", "")
            code = item.get("code", "")
            if fp and code:
                metrics.record_file_read(fp, code)

    # --- Check: did we get everything? ---
    _, missing = _golden_matches(metrics.files_read, task.golden_files)
    if not missing:
        return  # done — only definitions, zero noise

    # --- Fallback: /context-pack (semantic off, strict filter) ---
    pack_body = _rag_post("/context-pack", {
        "query": task.query,
        "repo": REPO_NAME,
        "max_slices": 20,
        "max_source_tokens": 30000,
        "use_ast_index": True,
        "include_semantic": False,
    })
    metrics.record_tool("context_pack")
    if pack_body:
        syms_lower = {s.lower() for s in task.symbols}
        golden_dirs = {str(Path(g).parent) for g in task.golden_files}
        for sl in (pack_body.get("slices") or []):
            fp = sl.get("file_path", "")
            code = sl.get("code", "")
            if not fp or not code:
                continue
            fp_stem = Path(fp).stem.lower()
            fp_dir = str(Path(fp).parent)
            is_relevant = (
                any(fp.endswith(g) for g in task.golden_files)
                or any(s in fp_stem for s in syms_lower)
                or fp_dir in golden_dirs
            )
            if is_relevant:
                metrics.record_file_read(fp, code)

    # --- Last resort: read missing golden files directly ---
    _, missing = _golden_matches(metrics.files_read, task.golden_files)
    if missing:
        _iterative_read(metrics, missing, task.golden_files, task.symbols)


# ---------------------------------------------------------------------------
# Agent 2: AST-Index  (CLI – symbols/signatures → follow-up reads)
# ---------------------------------------------------------------------------

def run_ast_index(task: Task, metrics: AgentMetrics) -> None:
    discovered: list[str] = []

    for term in task.symbols:
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
    if task.symbols:
        try:
            proc = subprocess.run(
                ["ast-index", "search", "--format", "json", "--limit", "30", task.symbols[0]],
                cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=15,
            )
            metrics.record_tool("ast-index:search")
            if proc.returncode == 0 and proc.stdout.strip():
                discovered.extend(_extract_paths_from_json(json.loads(proc.stdout)))
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass

    _iterative_read(metrics, list(dict.fromkeys(discovered)), task.golden_files, task.symbols)


# ---------------------------------------------------------------------------
# Agent 3: Graphify  (graph.json – focused subgraph traversal)
# ---------------------------------------------------------------------------

def run_graphify(task: Task, metrics: AgentMetrics) -> None:
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

    # Build adjacency: node_id -> set of neighbor node_ids
    adjacency: dict[str, set[str]] = {}
    node_id_to_path: dict[str, str] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        nid = str(node.get("id", node.get("name", "")))
        npath = str(node.get("path", node.get("file_path", node.get("file", ""))))
        if nid:
            adjacency.setdefault(nid, set())
            if npath:
                node_id_to_path[nid] = npath.replace("\\", "/")

    for edge in edges:
        if not isinstance(edge, dict):
            continue
        src = str(edge.get("source", ""))
        tgt = str(edge.get("target", ""))
        if src and tgt:
            adjacency.setdefault(src, set()).add(tgt)
            adjacency.setdefault(tgt, set()).add(src)

    # Phase 1: Find seed nodes matching task symbols
    symbol_lower = {s.lower() for s in task.symbols}
    seed_ids: set[str] = set()
    for nid, npath in node_id_to_path.items():
        name_lower = Path(npath).stem.lower()
        if any(sym in name_lower or sym in nid.lower() for sym in symbol_lower):
            seed_ids.add(nid)
    # Also match by node name field
    for node in nodes:
        if not isinstance(node, dict):
            continue
        name = str(node.get("name", "")).lower()
        nid = str(node.get("id", node.get("name", "")))
        if any(sym in name for sym in symbol_lower):
            seed_ids.add(nid)

    # Phase 2: Collect files from seeds + 1-hop neighbors
    relevant_paths: list[str] = []
    visited_ids: set[str] = set(seed_ids)
    for nid in seed_ids:
        if nid in node_id_to_path:
            relevant_paths.append(node_id_to_path[nid])
        for neighbor in adjacency.get(nid, set()):
            visited_ids.add(neighbor)
            if neighbor in node_id_to_path:
                relevant_paths.append(node_id_to_path[neighbor])

    # Phase 3: If golden files not covered, expand to 2-hop neighbors
    found, missing = _golden_matches([], task.golden_files)
    if missing:
        two_hop: set[str] = set()
        for nid in list(visited_ids):
            for neighbor in adjacency.get(nid, set()):
                if neighbor not in visited_ids:
                    two_hop.add(neighbor)
        for nid in two_hop:
            if nid in node_id_to_path:
                relevant_paths.append(node_id_to_path[nid])

    # Filter to source files
    source_exts = {".java", ".kt", ".kts", ".py", ".ts", ".tsx", ".js", ".go", ".rs"}
    source_paths = [
        p for p in dict.fromkeys(relevant_paths)
        if Path(p).suffix.lower() in source_exts
    ]

    _iterative_read(metrics, source_paths, task.golden_files, task.symbols)


# ---------------------------------------------------------------------------
# Agent 4: Vanilla  (ripgrep – text patterns → follow-up reads)
# ---------------------------------------------------------------------------

def run_vanilla(task: Task, metrics: AgentMetrics) -> None:
    discovered: list[str] = []

    for pattern in task.patterns:
        try:
            proc = subprocess.run(
                ["rg", "-l", "--glob", "*.kt", "--glob", "*.java", pattern, str(PROJECT_ROOT)],
                capture_output=True, text=True, timeout=30,
            )
            metrics.record_tool("ripgrep")
            if proc.returncode == 0 and proc.stdout.strip():
                for line in proc.stdout.splitlines():
                    line = line.strip()
                    if line:
                        try:
                            rel = str(Path(line).relative_to(PROJECT_ROOT))
                        except ValueError:
                            rel = line
                        discovered.append(rel.replace("\\", "/"))
        except (OSError, subprocess.TimeoutExpired):
            pass

    _iterative_read(metrics, list(dict.fromkeys(discovered)), task.golden_files, task.symbols)


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------

AGENTS: list[tuple[str, Any]] = [
    ("RAG+AST", run_rag_ast),
    ("AST-Index", run_ast_index),
    ("Graphify", run_graphify),
    ("Vanilla (rg)", run_vanilla),
]


def run_benchmark() -> list[dict[str, Any]]:
    all_results: list[dict[str, Any]] = []

    print("=" * 78)
    print("  BENCHMARK: Code-Retrieval Agent Effort Across 6 Refactoring Tasks")
    print(f"  Repo: {PROJECT_ROOT}")
    print("=" * 78)
    print()

    for task in TASKS:
        print(f"{'=' * 78}")
        print(f"  Task {task.id}: {task.name}")
        print(f"  Query: {task.query}")
        print(f"  Golden set: {len(task.golden_files)} files")
        print(f"{'=' * 78}")

        for agent_name, runner in AGENTS:
            metrics = AgentMetrics(agent_name=agent_name, task_id=task.id)
            t0 = time.perf_counter()
            try:
                runner(task, metrics)
            except Exception as exc:
                metrics.error = f"Unhandled: {exc}"
            metrics.latency_ms = (time.perf_counter() - t0) * 1000.0

            # Ensure golden found/missing are populated regardless of how the agent finished
            found, missing = _golden_matches(metrics.files_read, task.golden_files)
            metrics.golden_found = found
            metrics.golden_missing = missing

            file_detail = _build_file_detail(metrics, task.golden_files, task.symbols)
            golden_count = sum(1 for f in file_detail if f["relevance"] == "golden")
            related_count = sum(1 for f in file_detail if f["relevance"] == "related")
            noise_count = sum(1 for f in file_detail if f["relevance"] == "noise")
            total_files = len(file_detail)
            precision = golden_count / max(1, total_files) * 100.0
            signal_pct = (golden_count + related_count) / max(1, total_files) * 100.0

            result = {
                "task_id": task.id,
                "task_name": task.name,
                "agent": agent_name,
                "turns": metrics.turns,
                "tokens": metrics.tokens,
                "tool_calls": dict(metrics.tool_calls),
                "files_read": total_files,
                "golden_found": metrics.golden_found,
                "golden_missing": metrics.golden_missing,
                "coverage_pct": metrics.coverage(),
                "latency_ms": round(metrics.latency_ms, 1),
                "error": metrics.error,
                "file_detail": file_detail,
                "relevance": {
                    "golden": golden_count,
                    "related": related_count,
                    "noise": noise_count,
                    "precision_pct": round(precision, 1),
                    "signal_pct": round(signal_pct, 1),
                },
            }
            all_results.append(result)

            status = "OK" if not metrics.error else f"ERR: {metrics.error[:50]}"
            print(
                f"  {agent_name:<16} turns={metrics.turns:<6} "
                f"tokens={metrics.tokens:<12,} cov={metrics.coverage():5.1f}%  [{status}]"
            )
        print()

    # --- Summary tables ---
    _print_summary_table(all_results)
    return all_results


def _print_summary_table(results: list[dict[str, Any]]) -> None:
    print("=" * 78)
    print("  SUMMARY: Turns | Tokens | Coverage per (Task, Agent)")
    print("=" * 78)

    for task in TASKS:
        task_results = [r for r in results if r["task_id"] == task.id]
        print(f"\n  Task {task.id}: {task.name}")
        print(f"  {'Agent':<16} {'Turns':>6} {'Tokens':>12} {'Coverage':>9} {'Latency':>10}")
        print(f"  {'-' * 58}")
        for r in task_results:
            print(
                f"  {r['agent']:<16} {r['turns']:>6} {r['tokens']:>12,} "
                f"{r['coverage_pct']:>8.1f}% {r['latency_ms']:>9.0f}ms"
            )

    # Overall winner table
    print(f"\n{'=' * 78}")
    print("  OVERALL: Average effort per agent (across all tasks)")
    print(f"{'=' * 78}")
    print(f"  {'Agent':<16} {'Avg Turns':>10} {'Avg Tokens':>14} {'Avg Cov':>9} {'Wins':>5}")
    print(f"  {'-' * 58}")

    agent_stats: dict[str, list[dict]] = {}
    for r in results:
        agent_stats.setdefault(r["agent"], []).append(r)

    # Count wins (lowest tokens among 100% coverage agents per task)
    wins: dict[str, int] = {name: 0 for name in agent_stats}
    for task in TASKS:
        task_results = [r for r in results if r["task_id"] == task.id and r["coverage_pct"] >= 99.0]
        if task_results:
            best = min(task_results, key=lambda r: r["tokens"])
            wins[best["agent"]] = wins.get(best["agent"], 0) + 1

    for name, stats in agent_stats.items():
        avg_turns = sum(s["turns"] for s in stats) / len(stats)
        avg_tokens = sum(s["tokens"] for s in stats) / len(stats)
        avg_cov = sum(s["coverage_pct"] for s in stats) / len(stats)
        print(f"  {name:<16} {avg_turns:>10.1f} {avg_tokens:>14,.0f} {avg_cov:>8.1f}% {wins[name]:>5}")

    print()


# ---------------------------------------------------------------------------
# Markdown report generation
# ---------------------------------------------------------------------------

REPORT_DIR = Path(__file__).parent / "docs" / "benchmark_multi_task"


def _generate_md_reports(results: list[dict[str, Any]]) -> list[str]:
    """Write per-task markdown reports and an overall summary. Returns created file paths."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    created: list[str] = []

    for task in TASKS:
        task_results = [r for r in results if r["task_id"] == task.id]
        md = _build_task_report(task, task_results)
        fname = f"task_{task.id}_{task.name.split('(')[0].strip().lower().replace(' ', '_')}.md"
        fpath = REPORT_DIR / fname
        fpath.write_text(md, encoding="utf-8")
        created.append(str(fpath))

    summary_path = REPORT_DIR / "summary.md"
    summary_path.write_text(_build_summary_report(results), encoding="utf-8")
    created.append(str(summary_path))
    return created


def _build_task_report(task: Task, results: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append(f"# Task {task.id}: {task.name}")
    lines.append("")
    lines.append(f"**Query:** {task.query}")
    lines.append(f"**Symbols:** {', '.join(task.symbols)}")
    lines.append(f"**Search patterns:** {', '.join(task.patterns)}")
    lines.append(f"**Golden set ({len(task.golden_files)} files):**")
    for g in task.golden_files:
        lines.append(f"- `{g}`")
    lines.append("")

    # --- Effort table ---
    lines.append("## Effort Comparison")
    lines.append("")
    lines.append("| Agent | Turns | Tokens | Files Read | Coverage | Latency |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for r in results:
        lines.append(
            f"| {r['agent']} | {r['turns']} | {r['tokens']:,} "
            f"| {r['files_read']} | {r['coverage_pct']:.1f}% | {r['latency_ms']:.0f}ms |"
        )
    lines.append("")

    # --- Relevance table ---
    lines.append("## Information Relevance")
    lines.append("")
    lines.append("How much of what each agent read was actually useful?")
    lines.append("")
    lines.append("| Agent | Golden | Related | Noise | Precision | Signal% |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for r in results:
        rel = r["relevance"]
        lines.append(
            f"| {r['agent']} | {rel['golden']} | {rel['related']} "
            f"| {rel['noise']} | {rel['precision_pct']:.1f}% | {rel['signal_pct']:.1f}% |"
        )
    lines.append("")
    lines.append("- **Golden** = file is in the required golden set")
    lines.append("- **Related** = same package or name matches a task symbol")
    lines.append("- **Noise** = unrelated file that was read unnecessarily")
    lines.append("- **Precision** = golden / total files read")
    lines.append("- **Signal%** = (golden + related) / total files read")
    lines.append("")

    # --- Per-agent file listing ---
    for r in results:
        lines.append(f"### {r['agent']} — File Detail")
        lines.append("")
        if r["error"]:
            lines.append(f"> Error: {r['error']}")
            lines.append("")
        if not r["file_detail"]:
            lines.append("*No files read.*")
            lines.append("")
            continue

        lines.append("| # | File | Tokens | Relevance |")
        lines.append("|---:|------|---:|---|")
        for i, fd in enumerate(r["file_detail"], 1):
            tag = fd["relevance"]
            emoji = {"golden": "\u2b50", "related": "\u2705", "noise": "\u274c"}.get(tag, "")
            lines.append(f"| {i} | `{fd['file']}` | {fd['tokens']:,} | {emoji} {tag} |")
        lines.append("")

    # --- Analysis ---
    lines.append("## Analysis")
    lines.append("")
    best_token = min(results, key=lambda r: r["tokens"])
    best_prec = max(results, key=lambda r: r["relevance"]["precision_pct"])
    best_signal = max(results, key=lambda r: r["relevance"]["signal_pct"])
    worst_noise = max(results, key=lambda r: r["relevance"]["noise"])
    lines.append(f"- **Most token-efficient:** {best_token['agent']} ({best_token['tokens']:,} tokens)")
    lines.append(f"- **Highest precision:** {best_prec['agent']} ({best_prec['relevance']['precision_pct']:.1f}% golden)")
    lines.append(f"- **Highest signal%:** {best_signal['agent']} ({best_signal['relevance']['signal_pct']:.1f}% golden+related)")
    lines.append(f"- **Most noise:** {worst_noise['agent']} ({worst_noise['relevance']['noise']} irrelevant files read)")
    lines.append("")
    return "\n".join(lines)


def _build_summary_report(results: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append("# Multi-Task Benchmark Summary")
    lines.append("")
    lines.append(f"**Repo:** `{PROJECT_ROOT}`")
    lines.append(f"**Tasks:** {len(TASKS)}")
    lines.append(f"**Agents:** {', '.join(a[0] for a in AGENTS)}")
    lines.append("")

    # Overall effort table
    lines.append("## Overall Effort (averaged across tasks)")
    lines.append("")
    lines.append("| Agent | Avg Turns | Avg Tokens | Avg Precision | Avg Signal% | Avg Coverage |")
    lines.append("|---|---:|---:|---:|---:|---:|")

    agent_groups: dict[str, list[dict]] = {}
    for r in results:
        agent_groups.setdefault(r["agent"], []).append(r)

    for name, stats in agent_groups.items():
        n = len(stats)
        avg_turns = sum(s["turns"] for s in stats) / n
        avg_tokens = sum(s["tokens"] for s in stats) / n
        avg_prec = sum(s["relevance"]["precision_pct"] for s in stats) / n
        avg_signal = sum(s["relevance"]["signal_pct"] for s in stats) / n
        avg_cov = sum(s["coverage_pct"] for s in stats) / n
        lines.append(
            f"| {name} | {avg_turns:.1f} | {avg_tokens:,.0f} "
            f"| {avg_prec:.1f}% | {avg_signal:.1f}% | {avg_cov:.1f}% |"
        )
    lines.append("")

    # Per-task mini-table
    lines.append("## Per-Task Breakdown")
    lines.append("")
    for task in TASKS:
        task_results = [r for r in results if r["task_id"] == task.id]
        lines.append(f"### Task {task.id}: {task.name}")
        lines.append("")
        lines.append("| Agent | Tokens | Golden | Related | Noise | Precision | Signal% |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|")
        for r in task_results:
            rel = r["relevance"]
            lines.append(
                f"| {r['agent']} | {r['tokens']:,} "
                f"| {rel['golden']} | {rel['related']} | {rel['noise']} "
                f"| {rel['precision_pct']:.1f}% | {rel['signal_pct']:.1f}% |"
            )
        lines.append("")

    # Token efficiency ranking per task
    lines.append("## Token Efficiency Ranking (per task, lowest = best)")
    lines.append("")
    for task in TASKS:
        task_results = sorted(
            [r for r in results if r["task_id"] == task.id],
            key=lambda r: r["tokens"],
        )
        ranking = " > ".join(
            f"**{r['agent']}** ({r['tokens']:,})" for r in task_results
        )
        lines.append(f"- Task {task.id}: {ranking}")
    lines.append("")

    # Precision ranking
    lines.append("## Precision Ranking (per task, highest = best)")
    lines.append("")
    for task in TASKS:
        task_results = sorted(
            [r for r in results if r["task_id"] == task.id],
            key=lambda r: r["relevance"]["precision_pct"],
            reverse=True,
        )
        ranking = " > ".join(
            f"**{r['agent']}** ({r['relevance']['precision_pct']:.1f}%)" for r in task_results
        )
        lines.append(f"- Task {task.id}: {ranking}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    results = run_benchmark()

    # JSON dump
    json_path = Path(__file__).parent / "benchmark_multi_task_results.json"
    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"JSON saved to: {json_path}")

    # Markdown reports
    md_files = _generate_md_reports(results)
    print(f"Markdown reports ({len(md_files)} files):")
    for f in md_files:
        print(f"  {f}")

    sys.exit(0)
