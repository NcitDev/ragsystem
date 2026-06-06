#!/usr/bin/env python3
"""Compare vanilla grep, ast-index, and RAG navigation on Dodo tasks.

This is intentionally a lightweight navigation benchmark, not an answer-quality
grader. It measures whether each tool gets Codex to an expected file quickly and
how much source context the RAG packer proposes to put into the model context.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_PROJECT = Path("/Users/nikitaf/development/projects/dodo-mobile-android/project")
DEFAULT_RAG_ROOT = Path("/Users/nikitaf/production/ragsystem")
DEFAULT_RAG_URL = "http://127.0.0.1:7890"

PATH_RE = re.compile(
    r"(?:(?:/Users/[^\s:]+/development/projects/dodo-mobile-android/project/)?"
    r"(?:app|context|domain|core|feature|network|shared)[^\s:]*\.(?:kt|java))"
)
TOKENS_RE = re.compile(r"~(?P<tokens>\d+)\s+source tokens")


@dataclass(frozen=True)
class TaskCase:
    task_id: str
    prompt: str
    expected_files: tuple[str, ...]
    vanilla_pattern: str
    ast_symbols: tuple[str, ...]
    rag_query: str


TASKS: tuple[TaskCase, ...] = (
    TaskCase(
        "01-refactor-paid-order-reset",
        "Find suspend/async checkout functions related to waiting for paid orders.",
        (
            "context/order/src/main/java/ru/dodopizza/app/presentation/checkout/state/orderprocessing/CheckoutOrderProcessingService.kt",
            "context/order/src/test/java/com/dodopizza/order/feature/checkout/state/presentation/orderprocessing/WhenWaitForPaidOrder.kt",
        ),
        "waitForPayedOrder|setupAppStateForNewOrder|getPaidOrderForState",
        ("waitForPayedOrder", "setupAppStateForNewOrder", "getPaidOrderForState"),
        "waitForPayedOrder setupAppStateForNewOrder getPaidOrderForState trackPaymentFinished",
    ),
    TaskCase(
        "02-trace-failing-paid-order-test",
        "Trace ifSuccess_andOrderStateIsAlmostOk_shouldSetupAppStateForNewOrder.",
        (
            "context/order/src/test/java/com/dodopizza/order/feature/checkout/state/presentation/orderprocessing/WhenWaitForPaidOrder.kt",
            "context/order/src/main/java/ru/dodopizza/app/presentation/checkout/state/orderprocessing/CheckoutOrderProcessingService.kt",
        ),
        "ifSuccess_andOrderStateIsAlmostOk_shouldSetupAppStateForNewOrder|waitForPayedOrder",
        ("ifSuccess_andOrderStateIsAlmostOk_shouldSetupAppStateForNewOrder", "waitForPayedOrder"),
        "ifSuccess_andOrderStateIsAlmostOk_shouldSetupAppStateForNewOrder waitForPayedOrder",
    ),
    TaskCase(
        "03-deprecated-state-reset-api",
        "Find deprecated code pointing to CheckoutService::setupAppStateForNewOrder.",
        (
            "context/core/src/main/java/com/dodopizza/core/domain/state/StateAnalyzer.kt",
            "context/order/src/main/java/com/dodopizza/order/domain/workflow/checkout/CheckoutService.kt",
        ),
        "CheckoutService::setupAppStateForNewOrder|setupAppStateForNewOrder",
        ("setupAppStateForNewOrder", "StateAnalyzer"),
        "Deprecated CheckoutService::setupAppStateForNewOrder StateAnalyzer setupAppStateForNewOrder",
    ),
    TaskCase(
        "04-payment-completion-analytics",
        "Verify analytics tracking for successful payment completion.",
        (
            "context/order/src/main/java/ru/dodopizza/app/presentation/checkout/state/AnalyticsHelper.kt",
            "context/order/src/main/java/ru/dodopizza/app/presentation/checkout/state/orderprocessing/CheckoutOrderProcessingService.kt",
        ),
        "trackPaymentFinished|paymentFinished|waitForPayedOrder",
        ("trackPaymentFinished", "waitForPayedOrder"),
        "trackPaymentFinished paymentFinished waitForPayedOrder OrderCreated OrderIsBeingCreated",
    ),
    TaskCase(
        "05-profile-locale-di-boundary",
        "Find profile locale list dependency interface and owning module.",
        (
            "context/profile/src/main/java/com/dodopizza/profile/feature/profilelocalelist/ProfileLocaleListFeatureDependencies.kt",
            "context/profile/src/main/java/com/dodopizza/profile/feature/profilelocalelist/di/ProfileLocaleListComponent.kt",
            "app/src/main/java/ru/dodopizza/app/di/AppComponent.kt",
        ),
        "ProfileLocaleListFeatureDependencies|ProfileLocaleListComponent|LocaleListServiceModule",
        ("ProfileLocaleListFeatureDependencies", "ProfileLocaleListComponent", "LocaleListServiceModule"),
        "ProfileLocaleListFeatureDependencies ProfileLocaleListComponent LocaleListServiceModule AppComponent",
    ),
    TaskCase(
        "06-deferred-time-code-rename",
        "Find code-only deferred-time symbols to review for rename.",
        (
            "context/order/src/main/java/com/dodopizza/order/feature/checkout/deferredtime/presentation/DeferredTimeFragment.kt",
            "context/order/src/main/java/com/dodopizza/order/feature/checkout/deferredtime/presentation/DeferredTimePresenter.kt",
            "context/order/src/main/java/ru/dodopizza/app/presentation/checkout/state/CheckoutStateService.kt",
        ),
        "DeferredTimeFragment|DeferredTimePresenter|DeferredTimeState|setDeferredTime|setNewDeferredTime",
        ("DeferredTimeFragment", "DeferredTimePresenter", "DeferredTimeState", "setDeferredTime", "setNewDeferredTime"),
        "DeferredTimeFragment DeferredTimePresenter DeferredTimeState setDeferredTime setNewDeferredTime",
    ),
    TaskCase(
        "07-checkout-core-architecture",
        "Explain how checkout state is coordinated across context/order and context/core.",
        (
            "context/core/src/main/java/com/dodopizza/core/domain/state/StateAnalyzer.kt",
            "context/order/src/main/java/com/dodopizza/order/domain/workflow/checkout/CheckoutService.kt",
            "context/order/src/main/java/ru/dodopizza/app/presentation/checkout/state/CheckoutStateProvider.kt",
        ),
        "StateAnalyzer|CheckoutService|CheckoutStateProvider|CheckoutStateService|CheckoutDetailsServiceImpl",
        ("StateAnalyzer", "CheckoutService", "CheckoutStateProvider", "CheckoutStateService", "CheckoutDetailsServiceImpl"),
        "StateAnalyzer CheckoutService CheckoutStateProvider CheckoutStateService CheckoutDetailsServiceImpl",
    ),
    TaskCase(
        "08-checkout-payment-test-gaps",
        "Find state-changing checkout payment functions and nearby tests.",
        (
            "context/order/src/main/java/ru/dodopizza/app/presentation/checkout/state/orderprocessing/CheckoutOrderProcessingService.kt",
            "context/order/src/test/java/com/dodopizza/order/feature/checkout/state/presentation/orderprocessing/WhenChargePayment.kt",
            "context/order/src/test/java/com/dodopizza/order/feature/checkout/state/presentation/orderprocessing/WhenWaitForPaidOrder.kt",
        ),
        "chargePayment|chargeSbpPayment|chargeSavedCardPayment|createGooglePayRequest|confirm3DS|handlePaymentCanceled|setPaymentError|waitForPayedOrder",
        (
            "chargePayment",
            "chargeSbpPayment",
            "chargeSavedCardPayment",
            "createGooglePayRequest",
            "confirm3DS",
            "handlePaymentCanceled",
            "setPaymentError",
            "waitForPayedOrder",
        ),
        "chargePayment chargeSbpPayment chargeSavedCardPayment createGooglePayRequest confirm3DS handlePaymentCanceled setPaymentError waitForPayedOrder",
    ),
    TaskCase(
        "09-paid-order-response-vo-naming",
        "Find actual paid order response VO/model names and call sites.",
        (
            "context/order/src/main/java/com/dodopizza/order/feature/mainscreen/presentation/waitforpaidorder/PaidOrderResponseVO.kt",
            "domain/base/src/main/java/ru/dodopizza/app/domain/order/PaidOrderResponse.kt",
            "context/order/src/main/java/com/dodopizza/order/feature/mainscreen/presentation/MainScreenPresenter.kt",
        ),
        "PaidOrderResponseVO|PaidOrderResponse|handlePaidOrder|handleOrderResponse|toVO",
        ("PaidOrderResponseVO", "PaidOrderResponse", "handlePaidOrder", "handleOrderResponse", "toVO"),
        "PaidOrderResponseVO PaidOrderResponse handlePaidOrder handleOrderResponse toVO",
    ),
    TaskCase(
        "10-paid-order-reset-before-analytics",
        "Plan smallest patch so paid order handling resets state before analytics.",
        (
            "context/order/src/main/java/ru/dodopizza/app/presentation/checkout/state/orderprocessing/CheckoutOrderProcessingService.kt",
            "context/order/src/test/java/com/dodopizza/order/feature/checkout/state/presentation/orderprocessing/WhenWaitForPaidOrder.kt",
        ),
        "waitForPayedOrder|setupAppStateForNewOrder|trackPaymentFinished|OrderCreated|OrderIsBeingCreated",
        ("waitForPayedOrder", "setupAppStateForNewOrder", "trackPaymentFinished"),
        "waitForPayedOrder setupAppStateForNewOrder trackPaymentFinished OrderCreated OrderIsBeingCreated",
    ),
)


def run_command(args: list[str], cwd: Path, timeout: float) -> tuple[str, float, int]:
    start = time.perf_counter()
    completed = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    return completed.stdout, elapsed_ms, completed.returncode


def normalize_path(path: str, project_root: Path) -> str:
    cleaned = path.strip().strip('"').strip(",")
    if cleaned.startswith(str(project_root)):
        return str(Path(cleaned).relative_to(project_root))
    return cleaned


def unique_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            result.append(path)
    return result


def extract_paths(text: str, project_root: Path) -> list[str]:
    return unique_paths([normalize_path(match.group(0), project_root) for match in PATH_RE.finditer(text)])


def parse_json_paths(text: str, project_root: Path) -> list[str]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return extract_paths(text, project_root)
    rows: list[dict[str, Any]]
    if isinstance(data, list):
        rows = [row for row in data if isinstance(row, dict)]
    elif isinstance(data, dict):
        rows = []
        for key in ("symbols", "files", "references", "content_matches"):
            rows.extend(row for row in data.get(key, []) if isinstance(row, dict))
    else:
        rows = []
    paths = [normalize_path(str(row.get("path") or row.get("file_path") or ""), project_root) for row in rows]
    return unique_paths([path for path in paths if path])


def first_expected_rank(paths: list[str], expected_files: tuple[str, ...]) -> int | None:
    for index, path in enumerate(paths, start=1):
        if any(path == expected or path.endswith(expected) for expected in expected_files):
            return index
    return None


def token_estimate(text: str) -> int | None:
    match = TOKENS_RE.search(text)
    if not match:
        return None
    return int(match.group("tokens"))


def score_mode(paths: list[str], elapsed_ms: float, expected_files: tuple[str, ...], source_tokens: int | None = None) -> dict[str, Any]:
    rank = first_expected_rank(paths, expected_files)
    return {
        "first_expected_rank": rank,
        "hit": rank is not None,
        "result_count": len(paths),
        "latency_ms": round(elapsed_ms, 1),
        "source_tokens": source_tokens,
        "first_paths": paths[:5],
    }


def run_vanilla(task: TaskCase, project_root: Path) -> dict[str, Any]:
    output, elapsed_ms, returncode = run_command(
        ["rg", "-l", "--glob", "*.kt", "--glob", "*.java", task.vanilla_pattern, str(project_root)],
        cwd=project_root,
        timeout=20,
    )
    paths = [normalize_path(line, project_root) for line in output.splitlines() if line.strip()]
    result = score_mode(unique_paths(paths), elapsed_ms, task.expected_files)
    result["returncode"] = returncode
    return result


def run_ast_index(task: TaskCase, project_root: Path) -> dict[str, Any]:
    paths: list[str] = []
    elapsed = 0.0
    returncodes: list[int] = []
    for symbol in task.ast_symbols:
        output, elapsed_ms, returncode = run_command(
            ["ast-index", "--format", "json", "symbol", symbol],
            cwd=project_root,
            timeout=15,
        )
        elapsed += elapsed_ms
        returncodes.append(returncode)
        paths.extend(parse_json_paths(output, project_root))
    result = score_mode(unique_paths(paths), elapsed, task.expected_files)
    result["returncode"] = max(returncodes) if returncodes else 0
    return result


def run_rag(task: TaskCase, rag_root: Path, repo: str) -> dict[str, Any]:
    del rag_root
    token_path = Path.home() / ".rag" / "token"
    token = token_path.read_text().strip() if token_path.exists() else ""
    payload = json.dumps(
        {
            "query": task.rag_query,
            "repo": repo,
            "max_slices": 8,
            "max_source_tokens": 2400,
            "use_ast_index": True,
            "include_semantic": False,
        }
    ).encode()
    request = urllib.request.Request(
        f"{DEFAULT_RAG_URL}/context-pack",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode())
        elapsed_ms = (time.perf_counter() - start) * 1000
        paths = unique_paths([str(row.get("file_path", "")) for row in data.get("slices", []) if row.get("file_path")])
        result = score_mode(paths, elapsed_ms, task.expected_files, int(data.get("total_source_tokens", 0)))
        result["returncode"] = 0
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        result = score_mode([], elapsed_ms, task.expected_files, None)
        result["returncode"] = 1
        result["error"] = str(exc)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument("--rag-root", type=Path, default=DEFAULT_RAG_ROOT)
    parser.add_argument("--repo", default="dodo")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a Markdown table")
    args = parser.parse_args()

    rows: list[dict[str, Any]] = []
    for task in TASKS:
        rows.append(
            {
                "task_id": task.task_id,
                "vanilla": run_vanilla(task, args.project_root),
                "ast_index": run_ast_index(task, args.project_root),
                "rag": run_rag(task, args.rag_root, args.repo),
            }
        )

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    print("| Task | Mode | Hit | First Expected Rank | Results | Latency ms | Source Tokens | First Paths |")
    print("| --- | --- | --- | ---: | ---: | ---: | ---: | --- |")
    for row in rows:
        for mode in ("vanilla", "ast_index", "rag"):
            result = row[mode]
            first_paths = "<br>".join(result["first_paths"][:3])
            source_tokens = "" if result["source_tokens"] is None else str(result["source_tokens"])
            rank = "" if result["first_expected_rank"] is None else str(result["first_expected_rank"])
            print(
                f"| {row['task_id']} | {mode} | {result['hit']} | {rank} | "
                f"{result['result_count']} | {result['latency_ms']} | {source_tokens} | {first_paths} |"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
