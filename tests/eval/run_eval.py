"""RAG evaluation harness.

Reads a JSONL eval set, hits the running daemon's /search endpoint, and
computes recall@k, MRR, and latency percentiles. Outputs both a CSV row
and a markdown summary.

Usage:
    python tests/eval/run_eval.py tests/eval/telegram_eval.jsonl
    python tests/eval/run_eval.py tests/eval/telegram_eval.jsonl --top-k 10 --out results.md

Eval-set format (one JSON object per line):
    {
      "task_id": "task-1",
      "query": "where is voice message recording",
      "expected_files": ["messenger/MediaController.java", ...],
      "min_recall": 0.6,           # optional, default 0.5
      "strategy_hint": "hybrid"    # optional, informational
    }

A file is counted as a hit if any expected suffix appears anywhere in a
returned chunk's ``file_path``. This handles absolute paths in the corpus
without forcing the eval set to use absolute paths.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx


DEFAULT_BASE_URL = "http://127.0.0.1:7890"
DEFAULT_TOP_K = 10


@dataclass
class TaskResult:
    task_id: str
    query: str
    strategy: str
    expected_files: list[str]
    matched_files: list[str]
    returned_files: list[str]
    recall: float
    first_hit_rank: int | None
    latency_ms: float
    min_recall: float
    passed: bool


@dataclass
class EvalReport:
    results: list[TaskResult] = field(default_factory=list)

    @property
    def avg_recall(self) -> float:
        return statistics.mean(r.recall for r in self.results) if self.results else 0.0

    @property
    def mrr(self) -> float:
        if not self.results:
            return 0.0
        rr = [1.0 / r.first_hit_rank if r.first_hit_rank else 0.0 for r in self.results]
        return statistics.mean(rr)

    @property
    def latency_p50(self) -> float:
        return statistics.median(r.latency_ms for r in self.results) if self.results else 0.0

    @property
    def latency_p95(self) -> float:
        if not self.results:
            return 0.0
        sorted_lats = sorted(r.latency_ms for r in self.results)
        idx = max(0, int(len(sorted_lats) * 0.95) - 1)
        return sorted_lats[idx]

    @property
    def pass_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.passed) / len(self.results)


def load_eval_set(path: Path) -> list[dict]:
    items = []
    for line_no, line in enumerate(path.read_text().splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{line_no}: invalid JSON: {exc}")
    return items


def file_hit(returned_path: str, expected_suffix: str) -> bool:
    """A returned chunk's file_path matches an expected file if it ends with
    the expected suffix (after normalizing slashes)."""
    rp = returned_path.replace("\\", "/")
    sx = expected_suffix.replace("\\", "/").lstrip("/")
    return rp.endswith(sx) or f"/{sx}" in rp


def evaluate_task(client: httpx.Client, base_url: str, item: dict, top_k: int) -> TaskResult:
    query = item["query"]
    expected = item.get("expected_files", [])
    min_recall = float(item.get("min_recall", 0.5))

    t0 = time.perf_counter()
    resp = client.post(
        f"{base_url}/search",
        json={"query": query, "top_k": top_k, "rerank": False},
        timeout=60.0,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000

    if resp.status_code != 200:
        return TaskResult(
            task_id=item.get("task_id", query[:40]),
            query=query,
            strategy="ERROR",
            expected_files=expected,
            matched_files=[],
            returned_files=[],
            recall=0.0,
            first_hit_rank=None,
            latency_ms=elapsed_ms,
            min_recall=min_recall,
            passed=False,
        )

    body = resp.json()
    returned = [r["file_path"] for r in body.get("results", [])]
    plan = body.get("plan") or {}
    strategy = plan.get("strategy", "unknown")

    matched: list[str] = []
    first_hit_rank: int | None = None
    for exp in expected:
        for rank, rp in enumerate(returned, start=1):
            if file_hit(rp, exp):
                matched.append(exp)
                if first_hit_rank is None or rank < first_hit_rank:
                    first_hit_rank = rank
                break

    recall = len(matched) / len(expected) if expected else 0.0
    return TaskResult(
        task_id=item.get("task_id", query[:40]),
        query=query,
        strategy=strategy,
        expected_files=expected,
        matched_files=matched,
        returned_files=returned,
        recall=recall,
        first_hit_rank=first_hit_rank,
        latency_ms=elapsed_ms,
        min_recall=min_recall,
        passed=recall >= min_recall,
    )


def write_csv(report: EvalReport, csv_path: Path) -> None:
    with csv_path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "task_id",
                "query",
                "strategy",
                "recall",
                "first_hit_rank",
                "latency_ms",
                "passed",
                "expected_count",
                "matched_count",
            ]
        )
        for r in report.results:
            writer.writerow(
                [
                    r.task_id,
                    r.query,
                    r.strategy,
                    f"{r.recall:.3f}",
                    r.first_hit_rank if r.first_hit_rank is not None else "",
                    f"{r.latency_ms:.1f}",
                    int(r.passed),
                    len(r.expected_files),
                    len(r.matched_files),
                ]
            )


def render_markdown(report: EvalReport) -> str:
    lines: list[str] = []
    lines.append("# RAG Eval Report")
    lines.append("")
    lines.append(f"- Tasks: **{len(report.results)}**")
    lines.append(f"- Average recall: **{report.avg_recall:.3f}**")
    lines.append(f"- MRR: **{report.mrr:.3f}**")
    lines.append(f"- Latency p50: **{report.latency_p50:.0f} ms**")
    lines.append(f"- Latency p95: **{report.latency_p95:.0f} ms**")
    lines.append(f"- Pass rate (recall ≥ task threshold): **{report.pass_rate:.0%}**")
    lines.append("")
    lines.append("| Task | Strategy | Recall | First hit | Latency | Pass |")
    lines.append("|------|----------|--------|-----------|---------|------|")
    for r in report.results:
        rank = r.first_hit_rank if r.first_hit_rank is not None else "-"
        ok = "✅" if r.passed else "❌"
        lines.append(
            f"| {r.task_id} | {r.strategy} | {r.recall:.2f} ({len(r.matched_files)}/{len(r.expected_files)}) "
            f"| {rank} | {r.latency_ms:.0f} ms | {ok} |"
        )
    lines.append("")
    lines.append("## Per-task detail")
    for r in report.results:
        lines.append("")
        lines.append(f"### {r.task_id}")
        lines.append(f"- Query: `{r.query}`")
        lines.append(f"- Strategy: `{r.strategy}`")
        lines.append(f"- Expected ({len(r.expected_files)}): {r.expected_files}")
        lines.append(f"- Matched ({len(r.matched_files)}): {r.matched_files}")
        lines.append(f"- Returned files (top {len(r.returned_files)}):")
        for i, f in enumerate(r.returned_files, start=1):
            lines.append(f"  {i}. `{f}`")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="RAG eval harness")
    parser.add_argument("eval_set", type=Path, help="Path to JSONL eval set")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Markdown output path (default: alongside eval set)",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="CSV output path (default: alongside eval set)",
    )
    args = parser.parse_args()

    if not args.eval_set.exists():
        print(f"eval set not found: {args.eval_set}", file=sys.stderr)
        return 2

    items = load_eval_set(args.eval_set)
    if not items:
        print("eval set is empty", file=sys.stderr)
        return 2

    md_out = args.out or args.eval_set.with_suffix(".report.md")
    csv_out = args.csv or args.eval_set.with_suffix(".report.csv")

    report = EvalReport()
    with httpx.Client() as client:
        # Health check first — fail fast with a clear error
        try:
            h = client.get(f"{args.base_url}/health", timeout=5.0)
            h.raise_for_status()
        except httpx.HTTPError as exc:
            print(f"daemon unreachable at {args.base_url}: {exc}", file=sys.stderr)
            return 3

        for item in items:
            r = evaluate_task(client, args.base_url, item, args.top_k)
            report.results.append(r)
            tag = "✓" if r.passed else "✗"
            print(
                f"[{tag}] {r.task_id}: recall={r.recall:.2f} "
                f"strategy={r.strategy} latency={r.latency_ms:.0f}ms"
            )

    write_csv(report, csv_out)
    md_out.write_text(render_markdown(report))
    print(f"\nReport written to {md_out}")
    print(f"CSV written to {csv_out}")
    print(
        f"avg_recall={report.avg_recall:.3f} mrr={report.mrr:.3f} "
        f"p95={report.latency_p95:.0f}ms pass_rate={report.pass_rate:.0%}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
