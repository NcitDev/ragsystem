"""Compare repo-scoped RAG retrieval against plain rg + full-file reads.

This benchmark models the tool workflow we want to improve:

* RAG: ask the daemon for top-k code chunks in one repo.
* grep baseline: use task-supplied rg patterns to find candidate files, then
  read whole files for enough context to edit or reason about them.

The output is intentionally a tool-level proxy, not a claim about a whole
assistant session. It measures recall, first-hit rank, latency, and approximate
tokens returned to the model.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx


DEFAULT_BASE_URL = "http://127.0.0.1:7890"
DEFAULT_TOP_K = 10


@dataclass
class ToolResult:
    files: list[str]
    matched: list[str]
    recall: float
    first_hit_rank: int | None
    latency_ms: float
    chars: int

    @property
    def approx_tokens(self) -> int:
        return max(1, round(self.chars / 4))


@dataclass
class CompareResult:
    task_id: str
    query: str
    expected_files: list[str]
    min_recall: float
    rag: ToolResult
    grep: ToolResult

    @property
    def rag_passed(self) -> bool:
        return self.rag.recall >= self.min_recall

    @property
    def grep_passed(self) -> bool:
        return self.grep.recall >= self.min_recall

    @property
    def token_savings_ratio(self) -> float:
        if self.grep.approx_tokens <= 0:
            return 0.0
        return 1.0 - (self.rag.approx_tokens / self.grep.approx_tokens)


@dataclass
class CompareReport:
    results: list[CompareResult] = field(default_factory=list)

    def values(self, selector: str) -> list[float]:
        return [float(getattr(getattr(r, selector), "recall")) for r in self.results]

    @property
    def avg_rag_recall(self) -> float:
        return mean([r.rag.recall for r in self.results])

    @property
    def avg_grep_recall(self) -> float:
        return mean([r.grep.recall for r in self.results])

    @property
    def rag_mrr(self) -> float:
        return mrr([r.rag.first_hit_rank for r in self.results])

    @property
    def grep_mrr(self) -> float:
        return mrr([r.grep.first_hit_rank for r in self.results])

    @property
    def rag_latency_p50(self) -> float:
        return median([r.rag.latency_ms for r in self.results])

    @property
    def grep_latency_p50(self) -> float:
        return median([r.grep.latency_ms for r in self.results])

    @property
    def rag_tokens_avg(self) -> float:
        return mean([r.rag.approx_tokens for r in self.results])

    @property
    def grep_tokens_avg(self) -> float:
        return mean([r.grep.approx_tokens for r in self.results])

    @property
    def avg_token_savings(self) -> float:
        return mean([r.token_savings_ratio for r in self.results])

    @property
    def rag_pass_rate(self) -> float:
        return mean([1.0 if r.rag_passed else 0.0 for r in self.results])

    @property
    def grep_pass_rate(self) -> float:
        return mean([1.0 if r.grep_passed else 0.0 for r in self.results])


def mean(values: list[float | int]) -> float:
    return statistics.mean(values) if values else 0.0


def median(values: list[float | int]) -> float:
    return statistics.median(values) if values else 0.0


def mrr(ranks: list[int | None]) -> float:
    return mean([1.0 / rank if rank else 0.0 for rank in ranks])


def load_eval_set(path: Path) -> list[dict[str, Any]]:
    items = []
    for line_no, line in enumerate(path.read_text().splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{line_no}: invalid JSON: {exc}") from exc
    return items


def file_hit(returned_path: str, expected_suffix: str) -> bool:
    rp = returned_path.replace("\\", "/")
    sx = expected_suffix.replace("\\", "/").lstrip("/")
    return rp.endswith(sx) or f"/{sx}" in rp


def rel_path(path: str | Path, root: Path) -> str:
    p = Path(path)
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path).replace("\\", "/")


def score_files(files: list[str], expected: list[str]) -> tuple[list[str], float, int | None]:
    matched: list[str] = []
    first_hit_rank: int | None = None
    for exp in expected:
        for rank, file_path in enumerate(files, start=1):
            if file_hit(file_path, exp):
                matched.append(exp)
                if first_hit_rank is None or rank < first_hit_rank:
                    first_hit_rank = rank
                break
    recall = len(matched) / len(expected) if expected else 0.0
    return matched, recall, first_hit_rank


def read_token(token_path: Path | None) -> str | None:
    if os.environ.get("RAG_TOKEN"):
        return os.environ["RAG_TOKEN"]
    if token_path and token_path.exists():
        return token_path.read_text().strip()
    default = Path.home() / ".rag" / "token"
    if default.exists():
        return default.read_text().strip()
    return None


def rag_search(
    client: httpx.Client,
    base_url: str,
    token: str,
    repo: str,
    item: dict[str, Any],
    top_k: int,
) -> ToolResult:
    t0 = time.perf_counter()
    resp = client.post(
        f"{base_url}/search",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": item["query"], "top_k": top_k, "rerank": False, "repo": repo},
        timeout=120.0,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000
    if resp.status_code != 200:
        detail = resp.text[:500]
        raise RuntimeError(f"RAG search failed for {item['task_id']}: {resp.status_code} {detail}")

    body = resp.json()
    rows = body.get("results", [])
    files = [str(row.get("file_path", "")) for row in rows]
    chars = sum(len(str(row.get("code", ""))) for row in rows)
    matched, recall, first_hit_rank = score_files(files, item.get("expected_files", []))
    return ToolResult(files, matched, recall, first_hit_rank, elapsed_ms, chars)


def grep_read(
    source_root: Path,
    item: dict[str, Any],
    top_k: int,
    file_limit: int,
) -> ToolResult:
    patterns = item.get("grep_patterns") or [item["query"]]
    t0 = time.perf_counter()
    files: list[str] = []
    seen: set[str] = set()

    for pattern in patterns:
        cmd = ["rg", "-l", "-F", pattern, str(source_root)]
        proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
        if proc.returncode not in (0, 1):
            raise RuntimeError(f"rg failed for {item['task_id']} pattern {pattern!r}: {proc.stderr}")
        for line in proc.stdout.splitlines():
            relative = rel_path(line, source_root)
            if relative not in seen:
                seen.add(relative)
                files.append(relative)
            if len(files) >= top_k:
                break
        if len(files) >= top_k:
            break

    chars = 0
    for relative in files[:file_limit]:
        path = source_root / relative
        try:
            chars += len(path.read_text(errors="ignore"))
        except OSError:
            continue
    elapsed_ms = (time.perf_counter() - t0) * 1000

    matched, recall, first_hit_rank = score_files(files, item.get("expected_files", []))
    return ToolResult(files, matched, recall, first_hit_rank, elapsed_ms, chars)


def write_csv(report: CompareReport, csv_path: Path) -> None:
    with csv_path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "task_id",
                "rag_recall",
                "grep_recall",
                "rag_first_hit_rank",
                "grep_first_hit_rank",
                "rag_latency_ms",
                "grep_latency_ms",
                "rag_approx_tokens",
                "grep_approx_tokens",
                "token_savings_ratio",
                "rag_passed",
                "grep_passed",
            ]
        )
        for row in report.results:
            writer.writerow(
                [
                    row.task_id,
                    f"{row.rag.recall:.3f}",
                    f"{row.grep.recall:.3f}",
                    row.rag.first_hit_rank or "",
                    row.grep.first_hit_rank or "",
                    f"{row.rag.latency_ms:.1f}",
                    f"{row.grep.latency_ms:.1f}",
                    row.rag.approx_tokens,
                    row.grep.approx_tokens,
                    f"{row.token_savings_ratio:.3f}",
                    int(row.rag_passed),
                    int(row.grep_passed),
                ]
            )


def render_markdown(report: CompareReport, repo: str, source_root: Path, top_k: int) -> str:
    lines: list[str] = []
    lines.append("# Dodo RAG vs Grep Tool Eval")
    lines.append("")
    lines.append(f"- Repo: `{repo}`")
    lines.append(f"- Source root: `{source_root}`")
    lines.append(f"- Top K: **{top_k}**")
    lines.append(f"- Tasks: **{len(report.results)}**")
    lines.append(f"- RAG avg recall / MRR: **{report.avg_rag_recall:.3f} / {report.rag_mrr:.3f}**")
    lines.append(f"- Grep avg recall / MRR: **{report.avg_grep_recall:.3f} / {report.grep_mrr:.3f}**")
    lines.append(
        f"- RAG p50 latency: **{report.rag_latency_p50:.0f} ms**; "
        f"grep+read p50 latency: **{report.grep_latency_p50:.0f} ms**"
    )
    lines.append(
        f"- Avg approximate tokens returned: RAG **{report.rag_tokens_avg:.0f}**, "
        f"grep+read **{report.grep_tokens_avg:.0f}**"
    )
    lines.append(f"- Avg token reduction from RAG chunks: **{report.avg_token_savings:.0%}**")
    lines.append(f"- Pass rate: RAG **{report.rag_pass_rate:.0%}**, grep **{report.grep_pass_rate:.0%}**")
    lines.append("")
    lines.append(
        "Token counts are a proxy: `chars / 4`. The grep baseline reads full candidate "
        "files because that is the expensive tool behavior RAG is meant to avoid."
    )
    lines.append("")
    lines.append("| Task | RAG recall | Grep recall | RAG rank | Grep rank | RAG tok | Grep tok | Saved |")
    lines.append("|------|------------|-------------|----------|-----------|---------|----------|-------|")
    for row in report.results:
        rag_rank = row.rag.first_hit_rank or "-"
        grep_rank = row.grep.first_hit_rank or "-"
        lines.append(
            f"| {row.task_id} | {row.rag.recall:.2f} | {row.grep.recall:.2f} | "
            f"{rag_rank} | {grep_rank} | {row.rag.approx_tokens} | "
            f"{row.grep.approx_tokens} | {row.token_savings_ratio:.0%} |"
        )
    lines.append("")
    lines.append("## Per-task Results")
    for row in report.results:
        lines.append("")
        lines.append(f"### {row.task_id}")
        lines.append(f"- Query: `{row.query}`")
        lines.append(f"- Expected: {row.expected_files}")
        lines.append(f"- RAG matched: {row.rag.matched}")
        lines.append(f"- Grep matched: {row.grep.matched}")
        lines.append("- RAG files:")
        for i, file_path in enumerate(row.rag.files, start=1):
            lines.append(f"  {i}. `{file_path}`")
        lines.append("- Grep files:")
        for i, file_path in enumerate(row.grep.files, start=1):
            lines.append(f"  {i}. `{file_path}`")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare RAG search with rg + full-file read")
    parser.add_argument("eval_set", type=Path)
    parser.add_argument("--repo", required=True, help="Registered RAG repo name")
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--token-path", type=Path, default=None)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument(
        "--grep-read-files",
        type=int,
        default=10,
        help="How many grep candidate files to count as full-file reads",
    )
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--csv", type=Path, default=None)
    args = parser.parse_args()

    if not args.eval_set.exists():
        print(f"eval set not found: {args.eval_set}", file=sys.stderr)
        return 2
    if not args.source_root.exists():
        print(f"source root not found: {args.source_root}", file=sys.stderr)
        return 2
    token = read_token(args.token_path)
    if not token:
        print("RAG token not found; set RAG_TOKEN or provide --token-path", file=sys.stderr)
        return 2

    items = load_eval_set(args.eval_set)
    if not items:
        print("eval set is empty", file=sys.stderr)
        return 2

    md_out = args.out or args.eval_set.with_suffix(".compare.md")
    csv_out = args.csv or args.eval_set.with_suffix(".compare.csv")

    report = CompareReport()
    with httpx.Client() as client:
        try:
            health = client.get(f"{args.base_url}/health", timeout=5.0)
            health.raise_for_status()
        except httpx.HTTPError as exc:
            print(f"daemon unreachable at {args.base_url}: {exc}", file=sys.stderr)
            return 3

        for item in items:
            rag = rag_search(client, args.base_url, token, args.repo, item, args.top_k)
            grep = grep_read(args.source_root, item, args.top_k, args.grep_read_files)
            result = CompareResult(
                task_id=item.get("task_id", item["query"][:40]),
                query=item["query"],
                expected_files=item.get("expected_files", []),
                min_recall=float(item.get("min_recall", 0.5)),
                rag=rag,
                grep=grep,
            )
            report.results.append(result)
            print(
                f"[{result.task_id}] rag recall={rag.recall:.2f} "
                f"grep recall={grep.recall:.2f} tokens={rag.approx_tokens}/{grep.approx_tokens} "
                f"saved={result.token_savings_ratio:.0%}"
            )

    write_csv(report, csv_out)
    md_out.write_text(render_markdown(report, args.repo, args.source_root, args.top_k))
    print(f"\nReport written to {md_out}")
    print(f"CSV written to {csv_out}")
    print(
        f"rag_recall={report.avg_rag_recall:.3f} grep_recall={report.avg_grep_recall:.3f} "
        f"rag_mrr={report.rag_mrr:.3f} grep_mrr={report.grep_mrr:.3f} "
        f"avg_token_savings={report.avg_token_savings:.0%}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
