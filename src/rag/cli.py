"""Typer CLI — thin client that talks to the RAG daemon via HTTP."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from rag.config import CONFIG_PATH, ensure_rag_home, get_or_create_token, get_settings

app = typer.Typer(
    name="rag",
    help="Standalone RAG system for code search",
    no_args_is_help=True,
)
console = Console()
PROJECT_ROOT = Path(__file__).resolve().parents[2]
QDRANT_COMPOSE_FILE = PROJECT_ROOT / "compose.qdrant.yml"


def _base_url() -> str:
    settings = get_settings()
    return f"http://{settings.server.host}:{settings.server.port}"


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {get_or_create_token()}"}


def _check_daemon() -> bool:
    import httpx

    try:
        # /health is unauthenticated by design — keep this probe simple.
        resp = httpx.get(f"{_base_url()}/health", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


def _require_daemon() -> None:
    if not _check_daemon():
        console.print("[red]RAG daemon is not running. Start it with: rag start[/red]")
        raise typer.Exit(1)


def _post_json(path: str, payload: dict, timeout: int = 120) -> dict:
    import httpx

    try:
        resp = httpx.post(
            f"{_base_url()}{path}",
            json=payload,
            headers=_auth_headers(),
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        error = e.response.json() if e.response.headers.get("content-type", "").startswith("application/json") else {}
        console.print(f"[red]Request failed: {error.get('detail', e)}[/red]")
        raise typer.Exit(1)
    except httpx.ConnectError:
        console.print("[red]Connection lost to daemon.[/red]")
        raise typer.Exit(1)


def _emit_json(data: dict) -> None:
    import json
    import sys

    sys.stdout.write(json.dumps(data, indent=2, ensure_ascii=False))
    sys.stdout.write("\n")


# --- Core Commands ---


@app.command()
def init(
    path: str = typer.Argument(".", help="Repository path to initialize"),
):
    """Initialize RAG: create config, start daemon, index current directory."""
    import subprocess
    import sys
    import time as _time

    abs_path = str(Path(path).resolve())
    ensure_rag_home()

    # Create config if not exists
    if not CONFIG_PATH.exists():
        from shutil import copy2
        from rag.config import DEFAULT_CONFIG
        if DEFAULT_CONFIG.exists():
            copy2(DEFAULT_CONFIG, CONFIG_PATH)
    console.print(f"[green]Config:[/green] {CONFIG_PATH}")

    # Start daemon in background
    console.print("[green]Starting daemon...[/green]")
    subprocess.Popen(
        [sys.executable, "-m", "rag", "start", "--headless"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for daemon to be ready
    for _ in range(20):
        _time.sleep(0.5)
        if _check_daemon():
            break
    else:
        console.print("[red]Daemon failed to start. Check: rag diagnose[/red]")
        return

    console.print(f"[green]Daemon:[/green] running on {_base_url()}")

    # Index
    console.print(f"[green]Indexing:[/green] {abs_path}")
    import httpx
    try:
        resp = httpx.post(
            f"{_base_url()}/index",
            json={"repo_path": abs_path},
            headers=_auth_headers(),
            timeout=600,
        )
        data = resp.json()
        console.print(f"[green]Done:[/green] {data.get('files_processed', 0)} files, {data.get('chunks_indexed', 0)} chunks")
    except Exception as e:
        console.print(f"[red]Index failed: {e}[/red]")
        return

    console.print("\n[bold]Ready! Try:[/bold]")
    console.print("  rag search \"your query\"")
    console.print("  rag overview")
    console.print("  rag diagnose")


@app.command("install-agent")
def install_agent(
    target: str = typer.Argument("codex", help="Agent to configure. Currently supports: codex"),
):
    """Install project-owned agent guidance such as Codex skills."""
    import subprocess

    if target != "codex":
        console.print("[red]Only 'codex' is currently supported.[/red]")
        raise typer.Exit(1)
    installer = PROJECT_ROOT / "scripts" / "install-codex-skills.sh"
    if not installer.exists():
        console.print(f"[red]Installer not found: {installer}[/red]")
        raise typer.Exit(1)
    proc = subprocess.run([str(installer)], cwd=PROJECT_ROOT)
    if proc.returncode != 0:
        raise typer.Exit(proc.returncode)


@app.command()
def start(
    headless: bool = typer.Option(
        False,
        "--headless",
        "--no-tui",
        help="Alias for default behavior (server only). Kept for back-compat.",
    ),
    tui: bool = typer.Option(
        False,
        "--tui",
        help="Convenience: spawn daemon in background, then launch TUI in foreground.",
    ),
    watch: bool = typer.Option(False, "--watch", "-w", help="Enable file watcher for auto re-index"),
):
    """Start the RAG daemon (HTTP server). Use 'rag tui' for the dashboard."""
    ensure_rag_home()

    if tui:
        # Spawn daemon in background, wait for /health, then run TUI in foreground.
        import subprocess
        import sys
        import time as _time

        if _check_daemon():
            console.print(f"[green]Daemon already running on {_base_url()}[/green]")
        else:
            console.print("[green]Starting daemon in background...[/green]")
            cmd = [sys.executable, "-m", "rag", "start"]
            if watch:
                cmd.append("--watch")
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            for _ in range(20):
                _time.sleep(0.5)
                if _check_daemon():
                    break
            else:
                console.print("[red]Daemon failed to start. Check: rag diagnose[/red]")
                raise typer.Exit(1)
            console.print(f"[green]Daemon:[/green] running on {_base_url()}")

        from rag.app import RAGApp

        RAGApp().run()
        return

    # Default + --headless: run the daemon (HTTP server) in this process.
    # This is the supervised entrypoint for launchd/systemd.
    _ = headless  # accepted for back-compat; default behavior is server-only now.
    if watch:
        import os

        os.environ["RAG_WATCH_PATH"] = str(Path.cwd().resolve())
        console.print(f"[green]Watching:[/green] {os.environ['RAG_WATCH_PATH']}")
    import uvicorn

    from rag.integration.logging_setup import configure_logging
    from rag.server import app as fastapi_app

    # Rotated structured logging so the supervised daemon can't fill the disk.
    log_path = configure_logging(to_file=True)

    settings = get_settings()
    console.print(
        f"[green]Starting RAG server on {settings.server.host}:{settings.server.port}[/green]"
    )
    if log_path:
        console.print(f"[dim]Logging to {log_path} (rotating, ~50 MB cap)[/dim]")
    uvicorn.run(
        fastapi_app,
        host=settings.server.host,
        port=settings.server.port,
        # Logging is owned by our rotating handler; don't let uvicorn install
        # its own root config on top of it.
        log_config=None,
        log_level="info",
    )


@app.command("qdrant-up")
def qdrant_up():
    """Start local Qdrant server via Docker Compose."""
    import subprocess

    ensure_rag_home()
    cmd = ["docker", "compose", "-f", str(QDRANT_COMPOSE_FILE), "up", "-d"]
    try:
        subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)
    except FileNotFoundError:
        console.print("[red]Docker is not installed or not on PATH.[/red]")
        raise typer.Exit(1)
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Failed to start Qdrant: {e}[/red]")
        raise typer.Exit(e.returncode)
    console.print("[green]Qdrant server running at http://127.0.0.1:6333[/green]")
    console.print("[dim]Storage: ~/.rag/qdrant_server[/dim]")


@app.command("qdrant-down")
def qdrant_down():
    """Stop local Qdrant server started by qdrant-up."""
    import subprocess

    cmd = ["docker", "compose", "-f", str(QDRANT_COMPOSE_FILE), "down"]
    try:
        subprocess.run(cmd, cwd=PROJECT_ROOT, check=True)
    except FileNotFoundError:
        console.print("[red]Docker is not installed or not on PATH.[/red]")
        raise typer.Exit(1)
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Failed to stop Qdrant: {e}[/red]")
        raise typer.Exit(e.returncode)
    console.print("[green]Qdrant server stopped.[/green]")


@app.command("qdrant-status")
def qdrant_status():
    """Show configured Qdrant backend and server health."""
    import httpx

    settings = get_settings()
    console.print(f"Mode: [cyan]{settings.qdrant.mode}[/cyan]")
    if settings.qdrant.mode == "server":
        console.print(f"URL:  [cyan]{settings.qdrant.url}[/cyan]")
        try:
            resp = httpx.get(f"{settings.qdrant.url}/healthz", timeout=3)
            ok = resp.status_code == 200
            color = "green" if ok else "red"
            console.print(f"Health: [{color}]{resp.status_code}[/{color}]")
        except Exception as e:
            console.print(f"Health: [red]unreachable[/red] ({e})")
    else:
        console.print(f"Path: [cyan]{settings.qdrant.resolved_path}[/cyan]")


@app.command("benchmark-embeddings")
def benchmark_embeddings(
    path: str | None = typer.Argument(None, help="Optional repo path to sample real files"),
    batch_sizes: str = typer.Option("64,128,256", "--batch-sizes", help="Comma-separated batch sizes"),
    samples: int = typer.Option(256, "--samples", help="Number of texts to embed per batch size"),
    chars: int = typer.Option(1600, "--chars", help="Max characters per sampled text"),
):
    """Benchmark sequential Ollama embedding throughput for batch-size tuning."""
    import asyncio
    from time import perf_counter

    from rag.core.chunker import supported_extensions
    from rag.core.embedder import DOCUMENT_INSTRUCTION, OllamaEmbedder

    settings = get_settings()

    def _parse_sizes() -> list[int]:
        parsed = []
        for part in batch_sizes.split(","):
            value = part.strip()
            if not value:
                continue
            parsed.append(int(value))
        return parsed

    def _sample_texts() -> list[str]:
        texts: list[str] = []
        if path:
            root = Path(path).resolve()
            skip_dirs = set(settings.index.skip_dirs)
            exts = set(supported_extensions())
            for fp in root.rglob("*"):
                if len(texts) >= samples:
                    break
                if not fp.is_file() or fp.suffix not in exts:
                    continue
                if any(part in skip_dirs for part in fp.parts):
                    continue
                try:
                    content = fp.read_text(encoding="utf-8", errors="replace").strip()
                except Exception:
                    continue
                if content:
                    texts.append(content[:chars])
        if texts:
            return texts[:samples]
        template = (
            "class OrderService {\n"
            "  suspend fun loadOrder(id: String): Order {\n"
            "    return repository.fetchOrder(id)\n"
            "  }\n"
            "}\n"
        )
        return [(template * max(1, chars // len(template)))[:chars] for _ in range(samples)]

    async def _run() -> None:
        sizes = _parse_sizes()
        if not sizes:
            console.print("[red]No batch sizes provided.[/red]")
            raise typer.Exit(1)
        texts = [f"{DOCUMENT_INSTRUCTION}{text}" for text in _sample_texts()]
        embedder = OllamaEmbedder()
        await embedder.verify_model()

        table = Table(title="Embedding Batch Benchmark")
        table.add_column("Batch", style="cyan", justify="right")
        table.add_column("Texts", justify="right")
        table.add_column("Seconds", justify="right")
        table.add_column("Texts/sec", justify="right", style="green")

        # Warm one tiny batch so model load cost does not dominate the first row.
        await embedder._embed_batch(texts[:1], batch_size=1)

        for size in sizes:
            t0 = perf_counter()
            await embedder._embed_batch(texts, batch_size=size)
            elapsed = perf_counter() - t0
            throughput = len(texts) / elapsed if elapsed else 0.0
            table.add_row(str(size), str(len(texts)), f"{elapsed:.2f}", f"{throughput:.2f}")

        console.print(table)
        console.print("[dim]Pick the largest batch that improves throughput without hurting interactivity.[/dim]")

    asyncio.run(_run())


@app.command()
def tui():
    """Launch the read-only TUI dashboard. Requires a running daemon."""
    ensure_rag_home()
    if not _check_daemon():
        console.print("[red]RAG daemon is not running.[/red]")
        console.print("[dim]Start it with: rag start  (or: rag start --tui to auto-spawn)[/dim]")
        raise typer.Exit(1)

    from rag.app import RAGApp

    RAGApp().run()


@app.command()
def web(
    open_browser: bool = typer.Option(
        True, "--open/--no-open", help="Open the dashboard in your default browser"
    ),
):
    """Open the web dashboard (v2) served by the daemon. Requires a running daemon."""
    ensure_rag_home()
    if not _check_daemon():
        console.print("[red]RAG daemon is not running.[/red]")
        console.print("[dim]Start it with: rag start[/dim]")
        raise typer.Exit(1)

    url = _base_url() + "/"
    console.print(f"[green]Web dashboard:[/green] {url}")
    if open_browser:
        import webbrowser

        webbrowser.open(url)
    else:
        console.print("[dim]Open the URL above in your browser.[/dim]")


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    top_k: int = typer.Option(5, "--top-k", "-k", help="Number of results"),
    # ``--no-rerank`` is kept as a no-op for back-compat with existing
    # scripts; the reranker was removed alongside FastEmbed.
    no_rerank: bool = typer.Option(False, "--no-rerank", help="(deprecated, ignored)"),
    repo: str = typer.Option(None, "--repo", "-r", help="Search specific repo by name"),
    explain: bool = typer.Option(False, "--explain", help="Print the planner's queries and filters"),
):
    """Search the indexed codebase."""
    _require_daemon()
    import httpx

    try:
        resp = httpx.post(
            f"{_base_url()}/search",
            json={"query": query, "top_k": top_k, "repo": repo, "rerank": not no_rerank},
            headers=_auth_headers(),
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        error = e.response.json() if e.response.headers.get("content-type", "").startswith("application/json") else {}
        console.print(f"[red]Search failed: {error.get('detail', e)}[/red]")
        raise typer.Exit(1)
    except httpx.ConnectError:
        console.print("[red]Connection lost to daemon.[/red]")
        raise typer.Exit(1)

    plan = data.get("plan") or {}
    if plan.get("strategy"):
        console.print(f"[dim]Strategy: {plan['strategy']}[/dim]")
    if explain and plan:
        console.print(f"[dim]Queries: {plan.get('queries', [])}[/dim]")
        console.print(f"[dim]Filters: {plan.get('filters', {})}[/dim]")

    if not data["results"]:
        console.print("[yellow]No results found.[/yellow]")
        return

    console.print(f"\n[bold]Results for:[/bold] {data['query']}  ({data['total']} hits, {data['latency_ms']}ms)\n")

    for i, result in enumerate(data["results"], 1):
        console.print(f"[bold cyan]{i}. {result['file_path']}:{result['lines']}[/bold cyan]")
        console.print(f"   [dim]{result['chunk_type']}[/dim] [green]{result['name']}[/green]  score={result['score']}")
        code_lines = result["code"].split("\n")[:5]
        for line in code_lines:
            console.print(f"   [dim]{line}[/dim]")
        console.print()


@app.command()
def context_pack(
    query: str = typer.Argument(..., help="Context query"),
    repo: str = typer.Option(None, "--repo", "-r", help="Search specific repo by name"),
    max_slices: int = typer.Option(8, "--max-slices", "-n", help="Maximum source slices"),
    max_source_tokens: int = typer.Option(6000, "--max-source-tokens", "-t", help="Source token budget"),
    no_ast_index: bool = typer.Option(False, "--no-ast-index", help="Skip ast-index precision lookup"),
    no_semantic: bool = typer.Option(False, "--no-semantic", help="Only use exact/lexical matches"),
):
    """Return a token-bounded source context pack."""
    _require_daemon()
    import httpx

    try:
        resp = httpx.post(
            f"{_base_url()}/context-pack",
            json={
                "query": query,
                "repo": repo,
                "max_slices": max_slices,
                "max_source_tokens": max_source_tokens,
                "use_ast_index": not no_ast_index,
                "include_semantic": not no_semantic,
            },
            headers=_auth_headers(),
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        error = e.response.json() if e.response.headers.get("content-type", "").startswith("application/json") else {}
        console.print(f"[red]Context pack failed: {error.get('detail', e)}[/red]")
        raise typer.Exit(1)
    except httpx.ConnectError:
        console.print("[red]Connection lost to daemon.[/red]")
        raise typer.Exit(1)

    console.print(
        f"\n[bold]Context pack:[/bold] {data['query']} "
        f"({data['total']} slices, ~{data['total_source_tokens']} source tokens, {data['latency_ms']}ms)\n"
    )
    for i, item in enumerate(data["slices"], 1):
        console.print(f"[bold cyan]{i}. {item['file_path']}:{item['lines']}[/bold cyan]")
        console.print(
            f"   [dim]{item['why_included']} · {item['chunk_type']}[/dim] "
            f"[green]{item['name']}[/green] score={item['score']} tokens~{item['token_estimate']}"
        )
        for line in item["code"].split("\n")[:12]:
            console.print(f"   [dim]{line}[/dim]")
        console.print()


@app.command("repo-agent")
def repo_agent(
    query: str = typer.Argument(..., help="Developer task or code-navigation question"),
    repo: str = typer.Option(..., "--repo", "-r", help="Named repo to retrieve against"),
    max_slices: int = typer.Option(8, "--max-slices", "-n", help="Maximum exact context slices"),
    max_source_tokens: int = typer.Option(6000, "--max-source-tokens", "-t", help="Source token budget"),
    definitions: int = typer.Option(8, "--definitions", "-d", help="Maximum definition slices"),
    usages: int = typer.Option(12, "--usages", "-u", help="Maximum usage slices"),
    min_exact_slices: int = typer.Option(3, "--min-exact-slices", help="Semantic fallback threshold"),
    no_semantic_fallback: bool = typer.Option(
        False,
        "--no-semantic-fallback",
        help="Never use embeddings; return only AST/exact/lexical context",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
):
    """Central repo-agent retrieval: planner -> AST/exact context -> semantic fallback.

    The local model is only a retrieval planner.  Source context is fetched via
    deterministic AST/exact/lexical routes first; semantic search is used only
    when exact retrieval is too thin and fallback is allowed.
    """
    _require_daemon()
    import asyncio
    import json
    import time

    import httpx

    from rag.agents.repo_agent import (
        build_eval_metrics,
        build_repo_agent_plan,
        collect_modules,
        collect_tests,
        collect_top_files,
        compact_slice,
        disambiguate_symbols,
        filter_resolve_usages,
        infer_risks,
        should_use_semantic_fallback,
        total_source_tokens,
    )
    from rag.agents.retrieval import plan_search

    start = time.time()

    async def _plan():
        return await plan_search(query)

    planner = asyncio.run(_plan())
    plan = build_repo_agent_plan(
        query,
        planner,
        allow_semantic_fallback=not no_semantic_fallback,
    )

    def _post(path: str, payload: dict, timeout: int = 120) -> dict:
        resp = httpx.post(
            f"{_base_url()}{path}",
            json=payload,
            headers=_auth_headers(),
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()

    try:
        resolve_data: dict | None = None
        if plan.symbols:
            resolve_data = _post(
                "/resolve",
                {
                    "repo": repo,
                    "symbols": plan.symbols,
                    "definitions_limit": definitions,
                    "usages_limit": usages,
                },
            )
            # Two-phase blast radius: filter usages to most relevant
            resolve_data = filter_resolve_usages(
                resolve_data, plan.symbols, max_usages=usages,
            )

        exact_pack = _post(
            "/context-pack",
            {
                "repo": repo,
                "query": plan.context_query,
                "max_slices": max_slices,
                "max_source_tokens": max_source_tokens,
                "use_ast_index": True,
                "include_semantic": False,
                "strategy": plan.planner.strategy,
            },
        )

        reuse_packs: list[dict] = []
        for reuse_query in plan.reuse_queries:
            reuse_packs.append(
                _post(
                    "/context-pack",
                    {
                        "repo": repo,
                        "query": reuse_query,
                        "max_slices": min(max_slices, 6),
                        "max_source_tokens": min(max_source_tokens, 3000),
                        "use_ast_index": True,
                        "include_semantic": False,
                        "strategy": plan.planner.strategy,
                    },
                )
            )

        architecture_data: dict | None = None
        if plan.architecture_query:
            architecture_data = _post(
                "/project-understand",
                {
                    "repo": repo,
                    "query": plan.architecture_query,
                    "max_modules": 10,
                    "max_slices": min(max_slices, 8),
                    "max_source_tokens": min(max_source_tokens, 5000),
                },
                timeout=180,
            )

        call_trees: list[dict] = []
        for symbol in plan.call_tree_symbols:
            call_trees.append(
                _post(
                    "/call-tree",
                    {
                        "repo": repo,
                        "symbol": symbol,
                        "limit": 20,
                    },
                )
            )

        doc_searches: list[dict] = []
        for doc_query in plan.documentation_queries:
            try:
                doc_searches.append(
                    _post(
                        "/docs-search",
                        {
                            "query": doc_query,
                            "top_k": 5,
                        },
                    )
                )
            except httpx.HTTPStatusError:
                # Docs/spec indexing is optional. Keep repo-agent useful even
                # when no docs collection exists yet.
                doc_searches.append({"query": doc_query, "results": [], "total": 0, "latency_ms": 0})

        semantic_pack: dict | None = None
        semantic_used = False
        if (
            plan.semantic_fallback_allowed
            and should_use_semantic_fallback(exact_pack, min_exact_slices=min_exact_slices)
        ):
            semantic_pack = _post(
                "/context-pack",
                {
                    "repo": repo,
                    "query": plan.context_query,
                    "max_slices": max_slices,
                    "max_source_tokens": max_source_tokens,
                    "use_ast_index": True,
                    "include_semantic": True,
                },
            )
            semantic_used = any(
                item.get("why_included") == "semantic_match"
                for item in semantic_pack.get("slices", [])
            )
    except httpx.HTTPStatusError as e:
        error = (
            e.response.json()
            if e.response.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        console.print(f"[red]Repo-agent failed: {error.get('detail', e)}[/red]")
        raise typer.Exit(1)
    except httpx.ConnectError:
        console.print("[red]Connection lost to daemon.[/red]")
        raise typer.Exit(1)

    chosen_pack = semantic_pack or exact_pack
    first = (chosen_pack.get("slices") or [None])[0]
    elapsed = round((time.time() - start) * 1000, 1)
    all_context_packs = [exact_pack, *reuse_packs]
    if architecture_data:
        all_context_packs.append(
            {
                "slices": architecture_data.get("slices", []),
                "total_source_tokens": architecture_data.get("total_source_tokens", 0),
            }
        )
    if semantic_pack:
        all_context_packs.append(semantic_pack)
    token_total = total_source_tokens(*all_context_packs)
    docs_source_tokens = sum(
        max(1, len(result.get("code", "")) // 4)
        for search in doc_searches
        for result in search.get("results", [])
    )
    ambiguities = disambiguate_symbols(resolve_data)
    tests = collect_tests(*all_context_packs)
    evidence_bundle = {
        "top_files": collect_top_files(*all_context_packs),
        "symbols": plan.symbols,
        "callers": [
            {
                "symbol": tree.get("symbol", ""),
                "total": tree.get("total", 0),
                "nodes": [compact_slice(item) | {"depth": item.get("depth", 0)} for item in tree.get("nodes", [])[:8]],
            }
            for tree in call_trees
        ],
        "tests": tests,
        "modules": collect_modules(architecture_data),
        "docs": [
            {
                "query": search.get("query", ""),
                "total": search.get("total", 0),
                "results": [compact_slice(item) for item in search.get("results", [])],
            }
            for search in doc_searches
        ],
        "symbol_ambiguities": ambiguities,
        "risks": infer_risks(query, semantic_used=semantic_used, ambiguities=ambiguities, tests=tests),
    }
    metrics = build_eval_metrics(
        first_slice=first,
        exact_pack=exact_pack,
        semantic_pack=semantic_pack,
        total_tokens=token_total,
    )
    report = {
        "repo": repo,
        "query": query,
        "planner": {
            "strategy": planner.strategy,
            "queries": planner.queries,
            "filters": planner.filters,
            "top_k": planner.top_k,
        },
        "symbols": plan.symbols,
        "context_query": plan.context_query,
        "reuse_queries": plan.reuse_queries,
        "documentation_queries": plan.documentation_queries,
        "architecture_query": plan.architecture_query,
        "call_tree_symbols": plan.call_tree_symbols,
        "first_relevant": compact_slice(first) if first else None,
        "exact": {
            "total": exact_pack.get("total", 0),
            "total_source_tokens": exact_pack.get("total_source_tokens", 0),
            "latency_ms": exact_pack.get("latency_ms", 0),
            "slices": [compact_slice(item) for item in exact_pack.get("slices", [])],
        },
        "reuse_context": [
            {
                "query": reuse_pack.get("query", ""),
                "total": reuse_pack.get("total", 0),
                "total_source_tokens": reuse_pack.get("total_source_tokens", 0),
                "latency_ms": reuse_pack.get("latency_ms", 0),
                "slices": [compact_slice(item) for item in reuse_pack.get("slices", [])],
            }
            for reuse_pack in reuse_packs
        ],
        "architecture": {
            "query": architecture_data.get("query", "") if architecture_data else "",
            "total_source_tokens": architecture_data.get("total_source_tokens", 0) if architecture_data else 0,
            "latency_ms": architecture_data.get("latency_ms", 0) if architecture_data else 0,
            "modules": collect_modules(architecture_data),
            "symbols": (architecture_data or {}).get("symbols", [])[:12],
            "slices": [compact_slice(item) for item in (architecture_data or {}).get("slices", [])],
        },
        "call_trees": [
            {
                "symbol": tree.get("symbol", ""),
                "total": tree.get("total", 0),
                "latency_ms": tree.get("latency_ms", 0),
                "nodes": [compact_slice(item) | {"depth": item.get("depth", 0)} for item in tree.get("nodes", [])],
            }
            for tree in call_trees
        ],
        "docs_context": [
            {
                "query": search.get("query", ""),
                "total": search.get("total", 0),
                "latency_ms": search.get("latency_ms", 0),
                "results": [compact_slice(item) for item in search.get("results", [])],
            }
            for search in doc_searches
        ],
        "resolve": {
            "definitions": resolve_data.get("total_definitions", 0) if resolve_data else 0,
            "usages": len((resolve_data or {}).get("usages", [])),
            "usages_raw": resolve_data.get("total_usages_raw", resolve_data.get("total_usages", 0)) if resolve_data else 0,
            "definition_slices": [
                compact_slice(item) for item in (resolve_data or {}).get("definitions", [])
            ],
            "usage_slices": [
                compact_slice(item) for item in (resolve_data or {}).get("usages", [])
            ],
        },
        "semantic": {
            "allowed": plan.semantic_fallback_allowed,
            "used": semantic_used,
            "fallback_ran": semantic_pack is not None,
            "total": semantic_pack.get("total", 0) if semantic_pack else 0,
            "total_source_tokens": semantic_pack.get("total_source_tokens", 0) if semantic_pack else 0,
        },
        "evidence_bundle": evidence_bundle,
        "metrics": metrics,
        "docs_source_tokens": docs_source_tokens,
        "docs_embeddings_used": bool(doc_searches),
        "total_source_tokens": token_total,
        "latency_ms": elapsed,
        "enough_without_whole_files": bool(chosen_pack.get("slices")),
    }

    if json_output:
        import sys

        sys.stdout.write(json.dumps(report, indent=2, ensure_ascii=False))
        sys.stdout.write("\n")
        return

    console.print(f"\n[bold]Repo agent:[/bold] {query}")
    console.print(
        f"[dim]planner={planner.strategy} semantic_used={semantic_used} "
        f"source_tokens~{report['total_source_tokens']} latency={elapsed}ms[/dim]\n"
    )
    if plan.symbols:
        console.print(f"[bold]Symbols[/bold] [dim]{', '.join(plan.symbols)}[/dim]")
    if plan.reuse_queries:
        console.print(f"[bold]Reuse checks[/bold] [dim]{len(plan.reuse_queries)} exact query(s), semantic disabled[/dim]")
    if plan.documentation_queries:
        console.print(
            "[bold]Doc/spec queries[/bold] "
            f"[dim]{len(plan.documentation_queries)} suggested query(s) for indexed docs[/dim]"
        )
    if plan.architecture_query:
        console.print("[bold]Architecture check[/bold] [dim]project-understand enabled[/dim]")
    if plan.call_tree_symbols:
        console.print(f"[bold]Call trees[/bold] [dim]{', '.join(plan.call_tree_symbols)}[/dim]")
    if first:
        console.print("\n[bold]First Relevant Slice[/bold]")
        console.print(f"[bold cyan]{first['file_path']}:{first['lines']}[/bold cyan]")
        console.print(
            f"   [dim]{first['why_included']} · {first['chunk_type']}[/dim] "
            f"[green]{first['name']}[/green] tokens~{first['token_estimate']}"
        )

    if resolve_data:
        console.print(
            f"\n[bold]Resolve[/bold] "
            f"{resolve_data.get('total_definitions', 0)} definitions, "
            f"{resolve_data.get('total_usages', 0)} usages"
        )
        for i, item in enumerate(resolve_data.get("definitions", [])[:5], 1):
            console.print(f"  [cyan]D{i}[/cyan] {item['file_path']}:{item['lines']} [dim]{item['name']}[/dim]")
        for i, item in enumerate(resolve_data.get("usages", [])[:5], 1):
            console.print(f"  [cyan]U{i}[/cyan] {item['file_path']}:{item['lines']} [dim]{item['name']}[/dim]")

    console.print("\n[bold]Context[/bold]")
    for i, item in enumerate(chosen_pack.get("slices", []), 1):
        console.print(f"[bold cyan]{i}. {item['file_path']}:{item['lines']}[/bold cyan]")
        console.print(
            f"   [dim]{item['why_included']} · {item['chunk_type']}[/dim] "
            f"[green]{item['name']}[/green] score={item['score']} tokens~{item['token_estimate']}"
        )
        for line in item["code"].split("\n")[:8]:
            console.print(f"   [dim]{line}[/dim]")
        console.print()

    for reuse_pack in reuse_packs:
        if not reuse_pack.get("slices"):
            continue
        console.print(f"\n[bold]Reuse Context[/bold] [dim]{reuse_pack.get('query', '')}[/dim]")
        for i, item in enumerate(reuse_pack.get("slices", [])[:5], 1):
            console.print(f"[bold cyan]{i}. {item['file_path']}:{item['lines']}[/bold cyan]")
            console.print(
                f"   [dim]{item['why_included']} · {item['chunk_type']}[/dim] "
                f"[green]{item['name']}[/green] score={item['score']} tokens~{item['token_estimate']}"
            )

    if evidence_bundle["modules"]:
        console.print("\n[bold]Modules[/bold]")
        for module in evidence_bundle["modules"][:6]:
            console.print(f"  [cyan]{module['path']}[/cyan] [dim]{module['file_count']} files score={module['score']}[/dim]")
    if evidence_bundle["docs"]:
        console.print("\n[bold]Docs[/bold]")
        for doc in evidence_bundle["docs"]:
            console.print(f"  [cyan]{doc['query']}[/cyan] [dim]{doc['total']} result(s)[/dim]")
    if evidence_bundle["symbol_ambiguities"]:
        console.print("\n[bold]Ambiguous Symbols[/bold]")
        for ambiguity in evidence_bundle["symbol_ambiguities"][:3]:
            console.print(f"  [yellow]{ambiguity['symbol']}[/yellow] has {len(ambiguity['definitions'])} definitions")
    if evidence_bundle["risks"]:
        console.print("\n[bold]Risks[/bold]")
        for risk in evidence_bundle["risks"]:
            console.print(f"  [yellow]-[/yellow] {risk}")
    console.print(
        "\n[bold]Metrics[/bold] "
        f"rank={metrics['first_relevant_rank']} "
        f"tokens~{metrics['source_tokens']} "
        f"embeddings_used={metrics['embeddings_used']} "
        f"whole_file_reads_avoided={metrics['whole_file_reads_avoided']}"
    )


@app.command()
def resolve(
    symbol: list[str] = typer.Argument(..., help="Symbol(s) to resolve"),
    repo: str = typer.Option(..., "--repo", "-r", help="Named repo to resolve against"),
    usages: int = typer.Option(20, "--usages", "-u", help="Maximum usage slices"),
    definitions: int = typer.Option(20, "--definitions", "-d", help="Maximum definition slices"),
):
    """Resolve exact symbol definitions and usages via ast-index."""
    _require_daemon()
    import httpx

    try:
        resp = httpx.post(
            f"{_base_url()}/resolve",
            json={
                "repo": repo,
                "symbols": symbol,
                "definitions_limit": definitions,
                "usages_limit": usages,
            },
            headers=_auth_headers(),
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        error = e.response.json() if e.response.headers.get("content-type", "").startswith("application/json") else {}
        console.print(f"[red]Resolve failed: {error.get('detail', e)}[/red]")
        raise typer.Exit(1)
    except httpx.ConnectError:
        console.print("[red]Connection lost to daemon.[/red]")
        raise typer.Exit(1)

    console.print(
        f"\n[bold]Resolved:[/bold] {', '.join(data['symbols'])} "
        f"({data['total_definitions']} definitions, {data['total_usages']} usages, {data['latency_ms']}ms)\n"
    )
    if data["definitions"]:
        console.print("[bold]Definitions[/bold]")
        for i, item in enumerate(data["definitions"], 1):
            console.print(f"[bold cyan]{i}. {item['file_path']}:{item['lines']}[/bold cyan]")
            console.print(f"   [green]{item['name']}[/green] [dim]{item['chunk_type']} tokens~{item['token_estimate']}[/dim]")
    if data["usages"]:
        console.print("\n[bold]Usages[/bold]")
        for i, item in enumerate(data["usages"], 1):
            console.print(f"[bold cyan]{i}. {item['file_path']}:{item['lines']}[/bold cyan]")
            first = item["code"].strip().split("\n")[0] if item["code"].strip() else ""
            console.print(f"   [dim]{first}[/dim]")


@app.command()
def call_tree(
    symbol: str = typer.Argument(..., help="Function/symbol to trace"),
    repo: str = typer.Option(..., "--repo", "-r", help="Named repo to trace against"),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum call-tree nodes"),
):
    """Show AST call tree nodes with compact source slices."""
    _require_daemon()
    import httpx

    try:
        resp = httpx.post(
            f"{_base_url()}/call-tree",
            json={"repo": repo, "symbol": symbol, "limit": limit},
            headers=_auth_headers(),
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        error = e.response.json() if e.response.headers.get("content-type", "").startswith("application/json") else {}
        console.print(f"[red]Call tree failed: {error.get('detail', e)}[/red]")
        raise typer.Exit(1)
    except httpx.ConnectError:
        console.print("[red]Connection lost to daemon.[/red]")
        raise typer.Exit(1)

    console.print(f"\n[bold]Call tree:[/bold] {data['symbol']} ({data['total']} nodes, {data['latency_ms']}ms)\n")
    for item in data["nodes"]:
        indent = "  " * int(item.get("depth", 0))
        console.print(f"{indent}[bold cyan]{item['file_path']}:{item['lines']}[/bold cyan] [green]{item['name']}[/green]")
        first = item["code"].strip().split("\n")[0] if item["code"].strip() else ""
        if first:
            console.print(f"{indent}  [dim]{first}[/dim]")


@app.command()
def files(
    repo: str = typer.Option(..., "--repo", "-r", help="Named repo"),
    query: str = typer.Argument("", help="Optional file/symbol query"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum files"),
    tests_only: bool = typer.Option(False, "--tests-only", help="Only return likely test files"),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
):
    """List indexed files without scanning the filesystem."""
    _require_daemon()
    data = _post_json(
        "/graph/files",
        {"repo": repo, "query": query, "limit": limit, "tests_only": tests_only},
    )
    if json_output:
        _emit_json(data)
        return
    console.print(f"\n[bold]Files:[/bold] {repo} ({data['total']} files, {data['latency_ms']}ms)\n")
    for item in data["files"]:
        console.print(
            f"[bold cyan]{item['file_path']}[/bold cyan] "
            f"[dim]{item['language']} chunks={item['chunk_count']} symbols={item['symbol_count']}[/dim]"
        )
        if item.get("symbols"):
            console.print(f"  [dim]{', '.join(item['symbols'][:8])}[/dim]")


@app.command()
def node(
    symbol: str = typer.Argument(..., help="Symbol to inspect"),
    repo: str = typer.Option(..., "--repo", "-r", help="Named repo"),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum definitions/usages"),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
):
    """Get a symbol's definitions and usages."""
    _require_daemon()
    data = _post_json("/graph/node", {"repo": repo, "symbol": symbol, "limit": limit})
    if json_output:
        _emit_json(data)
        return
    console.print(
        f"\n[bold]Node:[/bold] {data['symbol']} "
        f"({data['total_definitions']} definitions, {data['total_usages']} usages, {data['latency_ms']}ms)\n"
    )
    for section in ("definitions", "usages"):
        if not data[section]:
            continue
        console.print(f"[bold]{section.title()}[/bold]")
        for item in data[section][:10]:
            console.print(f"  [cyan]{item['file_path']}:{item['lines']}[/cyan] [green]{item['name']}[/green]")


@app.command()
def callers(
    symbol: str = typer.Argument(..., help="Symbol to inspect"),
    repo: str = typer.Option(..., "--repo", "-r", help="Named repo"),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum callers"),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
):
    """Find one-hop callers of a symbol."""
    _require_daemon()
    data = _post_json("/graph/callers", {"repo": repo, "symbol": symbol, "limit": limit})
    if json_output:
        _emit_json(data)
        return
    console.print(f"\n[bold]Callers:[/bold] {data['symbol']} ({data['total']} nodes, {data['latency_ms']}ms)\n")
    for item in data["nodes"]:
        console.print(f"[cyan]{item['file_path']}:{item['lines']}[/cyan] [green]{item['name']}[/green]")


@app.command()
def callees(
    symbol: str = typer.Argument(..., help="Symbol to inspect"),
    repo: str = typer.Option(..., "--repo", "-r", help="Named repo"),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum callees"),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
):
    """Find likely callees from a symbol body."""
    _require_daemon()
    data = _post_json("/graph/callees", {"repo": repo, "symbol": symbol, "limit": limit})
    if json_output:
        _emit_json(data)
        return
    console.print(
        f"\n[bold]Callees:[/bold] {data['symbol']} "
        f"({data['total']} nodes, source={data['relation_source']}, {data['latency_ms']}ms)\n"
    )
    for item in data["nodes"]:
        console.print(f"[cyan]{item['file_path']}:{item['lines']}[/cyan] [green]{item['name']}[/green]")


@app.command()
def impact(
    symbol: str = typer.Argument(..., help="Symbol to inspect"),
    repo: str = typer.Option(..., "--repo", "-r", help="Named repo"),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum graph nodes/tests"),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
):
    """Analyze likely impact radius for a symbol change."""
    _require_daemon()
    data = _post_json("/graph/impact", {"repo": repo, "symbol": symbol, "limit": limit})
    if json_output:
        _emit_json(data)
        return
    metrics = data["metrics"]
    console.print(
        f"\n[bold]Impact:[/bold] {data['symbol']} "
        f"defs={metrics.get('definition_count', 0)} usages={metrics.get('usage_count', 0)} "
        f"callers={metrics.get('caller_count', 0)} tests={metrics.get('test_count', 0)}\n"
    )
    if data["affected_files"]:
        console.print("[bold]Affected Files[/bold]")
        for path in data["affected_files"][:20]:
            console.print(f"  [cyan]{path}[/cyan]")
    if data["tests"]:
        console.print("\n[bold]Likely Tests[/bold]")
        for item in data["tests"][:20]:
            console.print(f"  [cyan]{item['file_path']}[/cyan] [dim]score={item['score']}[/dim]")
    if data["risks"]:
        console.print("\n[bold]Risks[/bold]")
        for risk in data["risks"]:
            console.print(f"  [yellow]-[/yellow] {risk}")


@app.command()
def affected(
    repo: str = typer.Option(..., "--repo", "-r", help="Named repo"),
    file: list[str] = typer.Option(None, "--file", "-f", help="Changed file path; repeatable"),
    since: str = typer.Option("HEAD", "--since", help="Git ref for changed files when --file is omitted"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum tests/files"),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
):
    """Find likely affected indexed files and tests for changed files."""
    _require_daemon()
    data = _post_json(
        "/graph/affected",
        {"repo": repo, "files": file or [], "since": since, "limit": limit},
    )
    if json_output:
        _emit_json(data)
        return
    console.print(
        f"\n[bold]Affected:[/bold] changed={len(data['changed_files'])} "
        f"indexed={len(data['affected_files'])} tests={len(data['tests'])} ({data['latency_ms']}ms)\n"
    )
    if data["changed_files"]:
        console.print("[bold]Changed Files[/bold]")
        for path in data["changed_files"][:20]:
            console.print(f"  [cyan]{path}[/cyan]")
    if data["tests"]:
        console.print("\n[bold]Likely Tests[/bold]")
        for item in data["tests"][:20]:
            console.print(f"  [cyan]{item['file_path']}[/cyan] [dim]score={item['score']}[/dim]")
    if data["risks"]:
        console.print("\n[bold]Risks[/bold]")
        for risk in data["risks"]:
            console.print(f"  [yellow]-[/yellow] {risk}")


@app.command()
def understand(
    query: str = typer.Argument(..., help="Project topic to understand"),
    repo: str = typer.Option(..., "--repo", "-r", help="Named repo"),
    max_modules: int = typer.Option(8, "--max-modules", help="Maximum module summaries"),
    max_slices: int = typer.Option(8, "--max-slices", help="Maximum recommended context slices"),
    max_source_tokens: int = typer.Option(6000, "--max-source-tokens", help="Source token budget"),
):
    """Return project map plus recommended source slices for a topic."""
    _require_daemon()
    import httpx

    try:
        resp = httpx.post(
            f"{_base_url()}/project-understand",
            json={
                "repo": repo,
                "query": query,
                "max_modules": max_modules,
                "max_slices": max_slices,
                "max_source_tokens": max_source_tokens,
            },
            headers=_auth_headers(),
            timeout=180,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        error = e.response.json() if e.response.headers.get("content-type", "").startswith("application/json") else {}
        console.print(f"[red]Understand failed: {error.get('detail', e)}[/red]")
        raise typer.Exit(1)
    except httpx.ConnectError:
        console.print("[red]Connection lost to daemon.[/red]")
        raise typer.Exit(1)

    console.print(
        f"\n[bold]Project understanding:[/bold] {data['query']} "
        f"({len(data['slices'])} slices, ~{data['total_source_tokens']} source tokens, {data['latency_ms']}ms)\n"
    )
    if data["modules"]:
        console.print("[bold]Modules[/bold]")
        for module in data["modules"]:
            console.print(f"  [cyan]{module['path']}[/cyan] [dim]{module['file_count']} files score={module['score']}[/dim]")
    if data["symbols"]:
        console.print("\n[bold]Likely Symbols[/bold]")
        for symbol in data["symbols"][:10]:
            console.print(f"  [green]{symbol['name']}[/green] [dim]{symbol['kind']} {symbol['path']}:{symbol['line']}[/dim]")
    if data["slices"]:
        console.print("\n[bold]Recommended Context[/bold]")
        for i, item in enumerate(data["slices"], 1):
            console.print(f"[bold cyan]{i}. {item['file_path']}:{item['lines']}[/bold cyan]")
            console.print(f"   [dim]{item['why_included']} tokens~{item['token_estimate']}[/dim]")


@app.command()
def backfill_code_index(
    repo: str = typer.Option(None, "--repo", "-r", help="Named repo to backfill"),
    collection: str = typer.Option(None, "--collection", "-c", help="Qdrant collection to backfill"),
    keep_existing: bool = typer.Option(False, "--keep-existing", help="Do not clear existing SQLite code-index rows first"),
):
    """Backfill exact/context-pack SQLite index from existing Qdrant payloads."""
    _require_daemon()
    import httpx

    try:
        resp = httpx.post(
            f"{_base_url()}/index/backfill-code-index",
            json={"repo": repo, "collection": collection, "clear": not keep_existing},
            headers=_auth_headers(),
            timeout=600,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        error = e.response.json() if e.response.headers.get("content-type", "").startswith("application/json") else {}
        console.print(f"[red]Backfill failed: {error.get('detail', e)}[/red]")
        raise typer.Exit(1)
    except httpx.ConnectError:
        console.print("[red]Connection lost to daemon.[/red]")
        raise typer.Exit(1)

    console.print(
        f"[green]Backfilled[/green] {data['chunks_indexed']} chunks "
        f"from {data['collection']} in {data['latency_ms']}ms"
    )
    if data.get("chunks_skipped"):
        console.print(f"[yellow]Skipped {data['chunks_skipped']} payloads without content.[/yellow]")


@app.command()
def ask(
    question: str = typer.Argument(..., help="Question about the indexed codebase"),
    top_k: int = typer.Option(8, "--top-k", "-k", help="Chunks to retrieve as grounding context"),
    repo: str = typer.Option(None, "--repo", "-r", help="Restrict to named repo or file_path"),
):
    """Ask a grounded question (retrieves + LLM-generates with citations)."""
    _require_daemon()
    import httpx

    try:
        resp = httpx.post(
            f"{_base_url()}/ask",
            json={"question": question, "top_k": top_k, "repo": repo},
            headers=_auth_headers(),
            timeout=300,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        error = e.response.json() if e.response.headers.get("content-type", "").startswith("application/json") else {}
        console.print(f"[red]Ask failed: {error.get('detail', e)}[/red]")
        raise typer.Exit(1)
    except httpx.ConnectError:
        console.print("[red]Connection lost to daemon.[/red]")
        raise typer.Exit(1)

    console.print(f"\n[bold]Q:[/bold] {data['question']}")
    console.print(f"[dim]model={data['model']} retrieval={data['retrieval_ms']}ms gen={data['generation_ms']}ms total={data['latency_ms']}ms[/dim]\n")
    console.print(f"[bold green]A:[/bold green] {data['answer']}\n")

    if data["citations"]:
        console.print("[bold]Citations:[/bold]")
        for i, c in enumerate(data["citations"], 1):
            console.print(f"  [cyan]\\[{i}][/cyan] {c['file_path']}:{c['lines']} [dim]({c['name']}) score={c['score']}[/dim]")


@app.command("list")
def list_cmd(
    flag: str = typer.Argument(..., help="Payload flag (e.g. is_singleton, is_suspend, uses_coroutines, is_data_class)"),
    language: str = typer.Option(None, "--lang", help="Restrict to language (kotlin, java, python, ...)"),
    limit: int = typer.Option(500, "--limit", help="Max results"),
    value: str = typer.Option("true", "--value", help="Expected payload value (default 'true')"),
    show_lines: bool = typer.Option(False, "--lines", help="Show line ranges"),
):
    """Exhaustively enumerate all chunks matching a payload flag.

    Examples:
        rag list is_singleton --lang kotlin
        rag list is_suspend
        rag list uses_coroutines --lang kotlin --limit 2000
        rag list is_data_class
    """
    _require_daemon()
    import httpx

    filters: dict = {flag: value}
    if language:
        filters["language"] = language

    try:
        resp = httpx.post(
            f"{_base_url()}/enumerate",
            json={
                "filters": filters,
                "limit": limit,
                "fields": ["file_path", "name", "language", "chunk_type", "start_line", "end_line"],
            },
            headers=_auth_headers(),
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        error = e.response.json() if e.response.headers.get("content-type", "").startswith("application/json") else {}
        console.print(f"[red]List failed: {error.get('detail', e)}[/red]")
        raise typer.Exit(1)
    except httpx.ConnectError:
        console.print("[red]Connection lost to daemon.[/red]")
        raise typer.Exit(1)

    results = data.get("results", [])
    console.print(f"[bold]{data['count']}[/bold] matches for [cyan]{filters}[/cyan]"
                  + (" [yellow](truncated)[/yellow]" if data.get("truncated") else ""))
    # Dedupe by file_path for cleaner output
    seen_paths = set()
    for r in results:
        fp = r.get("file_path", "")
        if not show_lines:
            if fp in seen_paths:
                continue
            seen_paths.add(fp)
            console.print(f"  {fp}  [dim]{r.get('language', '?')} {r.get('chunk_type', '?')} {r.get('name') or ''}[/dim]")
        else:
            lines = f"{r.get('start_line', '?')}-{r.get('end_line', '?')}"
            console.print(f"  {fp}:{lines}  [dim]{r.get('chunk_type', '?')} {r.get('name') or ''}[/dim]")
    if not show_lines and len(seen_paths) < data["count"]:
        console.print(f"\n[dim]Deduplicated to {len(seen_paths)} files. Use --lines to see all chunks.[/dim]")


@app.command()
def index(
    path: str = typer.Argument(".", help="Path to repository"),
    full: bool = typer.Option(False, "--full", help="Force full re-index"),
    languages: list[str] = typer.Option(None, "--lang", "-l", help="Languages to index"),
    name: str = typer.Option(None, "--name", "-n", help="Register as named repo for multi-repo"),
):
    """Index a repository."""
    _require_daemon()
    import httpx

    abs_path = str(Path(path).resolve())

    # Register as named repo if --name provided
    collection = None
    if name:
        from rag.core.repos import RepoManager
        mgr = RepoManager()
        repo_info = mgr.register(name, abs_path)
        collection = repo_info.collection
        console.print(f"[green]Registered repo '{name}' at {abs_path}[/green]")

    console.print(f"[green]Indexing {abs_path}...[/green]")

    def _matching_job_id() -> str | None:
        try:
            jobs_resp = httpx.get(
                f"{_base_url()}/index/jobs",
                headers=_auth_headers(),
                timeout=10,
            )
            jobs_resp.raise_for_status()
            jobs = jobs_resp.json().get("jobs", {})
        except httpx.HTTPError:
            return None
        import time as _time

        now = _time.time()
        matches: list[tuple[float, str]] = []
        for candidate_id, job in jobs.items():
            status = job.get("status")
            if status not in {"queued", "scanning", "running", "completed"}:
                continue
            if status == "completed" and now - float(job.get("finished_at") or 0) > 120:
                continue
            if job.get("repo_path") != abs_path:
                continue
            if job.get("collection") != collection:
                continue
            if bool(job.get("full")) != bool(full):
                continue
            if (job.get("languages") or None) != (languages or None):
                continue
            matches.append((float(job.get("started_at") or 0), candidate_id))
        if not matches:
            return None
        return max(matches)[1]

    def _poll_job(job_id: str) -> dict:
        data = {}
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.fields[files_label]}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task_id = progress.add_task("indexing", total=1, files_label="0/0 files")
            poll_timeouts = 0
            while True:
                try:
                    poll = httpx.get(
                        f"{_base_url()}/index/progress/{job_id}",
                        headers=_auth_headers(),
                        timeout=10,
                    )
                except httpx.TimeoutException:
                    poll_timeouts += 1
                    progress.update(task_id, description="waiting for daemon")
                    if poll_timeouts >= 12:
                        raise
                    continue
                poll_timeouts = 0
                poll.raise_for_status()
                data = poll.json()
                total = int(data.get("total_files") or 0)
                processed = int(data.get("files_processed") or 0)
                chunks_indexed = int(data.get("chunks_indexed") or 0)
                chunks_seen = int(data.get("chunks_seen") or 0)
                chunks_estimate = int(data.get("chunks_total_estimate") or 0)
                current_file = data.get("current_file") or ""
                status = data.get("status", "running")
                desc = f"{status}"
                if current_file:
                    desc += f" · {current_file[-70:]}"
                visible_total = max(total, 1)
                visible_completed = (
                    visible_total
                    if status == "completed" and total == 0
                    else min(processed, visible_total)
                )
                progress.update(
                    task_id,
                    total=visible_total,
                    completed=visible_completed,
                    description=desc,
                    files_label=(
                        f"{processed}/{total} files · {chunks_indexed}/{chunks_estimate} chunks"
                        if chunks_estimate
                        else f"{processed}/{total} files · {chunks_seen} chunks seen"
                    ),
                )
                if status in {"completed", "failed"}:
                    break
                import time as _time

                _time.sleep(1)
        return data

    try:
        resp = httpx.post(
            f"{_base_url()}/index/start",
            json={
                "repo_path": abs_path,
                "full": full,
                "languages": languages,
                "collection": collection,
            },
            headers=_auth_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        job_id = resp.json()["job_id"]
        console.print(f"[dim]Job:[/dim] {job_id}")
        data = _poll_job(job_id)
        if data.get("status") == "failed":
            console.print(f"[red]Index failed: {data.get('error', 'unknown error')}[/red]")
            raise typer.Exit(1)
    except httpx.HTTPStatusError as e:
        error = e.response.json() if e.response.headers.get("content-type", "").startswith("application/json") else {}
        console.print(f"[red]Index failed: {error.get('detail', e)}[/red]")
        raise typer.Exit(1)
    except httpx.TimeoutException:
        job_id = _matching_job_id()
        if not job_id:
            console.print("[red]Index request timed out before a job was created.[/red]")
            raise typer.Exit(1)
        console.print(f"[yellow]Index start response timed out; attached to running job {job_id}.[/yellow]")
        data = _poll_job(job_id)
        if data.get("status") == "failed":
            console.print(f"[red]Index failed: {data.get('error', 'unknown error')}[/red]")
            raise typer.Exit(1)

    # Update repo stats if named
    if name:
        from rag.core.repos import RepoManager
        mgr = RepoManager()
        mgr.update_stats(name, data["chunks_indexed"])

    table = Table(title="Index Results")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Files processed", str(data["files_processed"]))
    table.add_row("Chunks indexed", str(data["chunks_indexed"]))
    table.add_row("Files skipped", str(data["files_skipped"]))
    table.add_row("Files deleted", str(data["files_deleted"]))
    timings = data.get("timings_ms") or {}
    if timings:
        started_at = float(data.get("started_at") or 0)
        finished_at = float(data.get("finished_at") or 0)
        if started_at and finished_at:
            table.add_row("Job duration", f"{finished_at - started_at:.1f}s")
        for key in (
            "scan_ms",
            "collection_reset_ms",
            "chunk_ms",
            "cache_lookup_ms",
            "embed_ms",
            "cache_write_ms",
            "point_build_ms",
            "qdrant_upsert_ms",
            "ensure_collection_ms",
            "delete_old_chunks_ms",
            "lsp_ms",
            "graph_summary_ms",
            "state_save_ms",
        ):
            if key in timings:
                label = key.removesuffix("_ms").replace("_", " ")
                table.add_row(f"  {label}", f"{float(timings[key]) / 1000:.1f}s")
    if data["errors"]:
        table.add_row("Errors", str(len(data["errors"])))
    console.print(table)


@app.command("index-docs")
def index_docs(
    path: str = typer.Argument(..., help="Documentation file or directory to index"),
    collection: str = typer.Option(None, "--collection", "-c", help="Docs collection override"),
    doc_type: list[str] = typer.Option(None, "--doc-type", help="Document type: markdown or text"),
    full: bool = typer.Option(False, "--full", help="Recreate the docs collection before indexing"),
):
    """Index Markdown/text docs into the docs collection."""
    _require_daemon()
    import httpx

    abs_path = str(Path(path).resolve())
    try:
        resp = httpx.post(
            f"{_base_url()}/index/docs",
            json={
                "docs_path": abs_path,
                "collection": collection,
                "doc_types": doc_type,
                "full": full,
            },
            headers=_auth_headers(),
            timeout=600,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        error = e.response.json() if e.response.headers.get("content-type", "").startswith("application/json") else {}
        console.print(f"[red]Docs index failed: {error.get('detail', e)}[/red]")
        raise typer.Exit(1)
    except httpx.ConnectError:
        console.print("[red]Connection lost to daemon.[/red]")
        raise typer.Exit(1)

    console.print(
        f"[green]Indexed docs[/green] {data['files_processed']} files, "
        f"{data['chunks_indexed']} chunks"
    )
    if data.get("errors"):
        for error in data["errors"][:5]:
            console.print(f"[yellow]{error}[/yellow]")


@app.command("generate-event-catalog")
def generate_event_catalog(
    repo_path: str = typer.Argument(..., help="Repository path to scan"),
    output: str = typer.Option(None, "--output", "-o", help="Markdown output path"),
    repo_name: str = typer.Option("repo", "--repo-name", help="Display name in generated catalog"),
    index_result: bool = typer.Option(False, "--index", help="Index the generated catalog into RAG docs"),
    full: bool = typer.Option(False, "--full", help="Recreate docs collection before indexing"),
):
    """Generate a Markdown analytics/event catalog from repo code."""
    from rag.core.events import discover_event_entries, render_event_catalog

    repo_root = Path(repo_path).resolve()
    if not repo_root.exists():
        console.print(f"[red]Repo path does not exist: {repo_root}[/red]")
        raise typer.Exit(1)
    output_path = (
        Path(output).resolve()
        if output
        else PROJECT_ROOT / "generated" / f"{repo_name}-event-catalog.md"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    entries = discover_event_entries(repo_root)
    output_path.write_text(render_event_catalog(repo_name, entries), encoding="utf-8")
    console.print(f"[green]Wrote[/green] {output_path} [dim]({len(entries)} entries)[/dim]")

    if index_result:
        _require_daemon()
        import httpx

        try:
            resp = httpx.post(
                f"{_base_url()}/index/docs",
                json={
                    "docs_path": str(output_path),
                    "doc_types": ["markdown"],
                    "full": full,
                },
                headers=_auth_headers(),
                timeout=600,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            error = e.response.json() if e.response.headers.get("content-type", "").startswith("application/json") else {}
            console.print(f"[red]Event catalog index failed: {error.get('detail', e)}[/red]")
            raise typer.Exit(1)
        except httpx.ConnectError:
            console.print("[red]Connection lost to daemon.[/red]")
            raise typer.Exit(1)

        console.print(
            f"[green]Indexed event catalog[/green] "
            f"{data['files_processed']} files, {data['chunks_indexed']} chunks"
        )


@app.command()
def status():
    """Show system status."""
    _require_daemon()
    import httpx

    try:
        resp = httpx.get(f"{_base_url()}/status", headers=_auth_headers(), timeout=5)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        console.print(f"[red]Status check failed: {e}[/red]")
        raise typer.Exit(1)

    table = Table(title="RAG System Status")
    table.add_column("Component", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Status", data["status"])
    table.add_row("Embedder", f"{data['embedder_model']} ({data['embedder_provider']})")
    table.add_row("Reranker", "removed")
    table.add_row("Uptime", f"{data['uptime_seconds']:.0f}s")

    for coll in data["collections"]:
        table.add_row(
            f"Collection: {coll['name']}",
            f"{coll.get('points_count', '?')} points ({coll.get('status', '?')})",
        )
    console.print(table)


config_app = typer.Typer(
    name="config",
    help="Edit or hot-reload daemon config",
    no_args_is_help=False,
    invoke_without_command=True,
)


@config_app.callback()
def config_main(ctx: typer.Context):
    """Open config file in $EDITOR (default action)."""
    if ctx.invoked_subcommand is not None:
        return

    import os
    import subprocess

    ensure_rag_home()

    if not CONFIG_PATH.exists():
        from shutil import copy2
        from rag.config import DEFAULT_CONFIG

        if DEFAULT_CONFIG.exists():
            copy2(DEFAULT_CONFIG, CONFIG_PATH)
            console.print(f"[green]Created config at {CONFIG_PATH}[/green]")
        else:
            CONFIG_PATH.write_text("# RAG System Configuration\n# See config/default.toml for all options\n")

    editor = os.environ.get("EDITOR", "vim")
    subprocess.run([editor, str(CONFIG_PATH)])


@config_app.command("reload")
def config_reload(
    force: bool = typer.Option(False, "--force", help="Allow embedding-model swap (invalidates index)"),
):
    """Tell the running daemon to re-read config and swap models if changed."""
    _require_daemon()
    import httpx

    try:
        resp = httpx.post(
            f"{_base_url()}/admin/reload",
            json={"force": force},
            headers=_auth_headers(),
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        try:
            error = e.response.json()
        except Exception:
            error = {}
        console.print(f"[red]Reload failed: {error.get('detail', e)}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Reload failed: {e}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]Config reloaded.[/green] {data.get('detail', '')}")
    if data.get("embedder_reinitialized"):
        console.print("  embedder reinitialized")


app.add_typer(config_app, name="config")


# --- Multi-repo Commands ---


@app.command()
def repos():
    """List registered repositories."""
    from rag.core.repos import RepoManager

    mgr = RepoManager()
    repo_list = mgr.list_repos()

    if not repo_list:
        console.print("[yellow]No repos registered. Use: rag index <path> --name <name>[/yellow]")
        return

    table = Table(title="Registered Repositories")
    table.add_column("Name", style="cyan")
    table.add_column("Path", style="dim")
    table.add_column("Chunks", style="green")
    table.add_column("Last Indexed", style="dim")

    for r in repo_list:
        table.add_row(r.name, r.path, str(r.chunks_count), r.last_indexed or "never")
    console.print(table)


# --- Export/Import Commands ---


@app.command()
def export(
    output: str = typer.Argument(..., help="Output file path (.jsonl)"),
    collection: str = typer.Option(None, "--collection", "-c", help="Collection name (default: code_chunks)"),
):
    """Export indexed data to JSONL file."""
    _require_daemon()
    import asyncio
    from rag.core.export import export_collection
    from rag.core.vectorstore import QdrantVectorStore

    async def _export():
        vs = QdrantVectorStore()
        coll = collection or get_settings().qdrant.code_collection
        count = await export_collection(vs, coll, output)
        await vs.close()
        return count

    count = asyncio.run(_export())
    console.print(f"[green]Exported {count} chunks to {output}[/green]")


@app.command(name="import")
def import_cmd(
    input_file: str = typer.Argument(..., help="Input JSONL file"),
    collection: str = typer.Option(None, "--collection", "-c", help="Target collection"),
):
    """Import data from JSONL file."""
    _require_daemon()
    import asyncio
    from rag.core.export import import_collection
    from rag.core.vectorstore import QdrantVectorStore

    async def _import():
        vs = QdrantVectorStore()
        coll = collection or get_settings().qdrant.code_collection
        count = await import_collection(vs, coll, input_file)
        await vs.close()
        return count

    count = asyncio.run(_import())
    console.print(f"[green]Imported {count} chunks from {input_file}[/green]")


# --- Diff Search ---


@app.command()
def diff(
    query: str = typer.Argument(..., help="Search query"),
    since: str = typer.Option("HEAD~5", "--since", "-s", help="Git ref or date (e.g., HEAD~5, 3 days ago)"),
    path: str = typer.Option(".", "--path", "-p", help="Repository path"),
    top_k: int = typer.Option(5, "--top-k", "-k", help="Number of results"),
):
    """Search within recent git changes."""
    _require_daemon()
    import asyncio
    from rag.core.diff import get_changed_files_since, search_in_diff
    from rag.core.vectorstore import QdrantVectorStore

    abs_path = str(Path(path).resolve())
    changed = get_changed_files_since(abs_path, since)

    if not changed:
        console.print(f"[yellow]No files changed since {since}[/yellow]")
        return

    console.print(f"[dim]{len(changed)} files changed since {since}[/dim]\n")

    async def _search():
        vs = QdrantVectorStore()
        results = await search_in_diff(abs_path, since, query, vs, top_k)
        await vs.close()
        return results

    results = asyncio.run(_search())

    if not results:
        console.print("[yellow]No matching results in changed files.[/yellow]")
        return

    for i, r in enumerate(results, 1):
        fp = r.get("file_path", r.payload.get("file_path", "?")) if hasattr(r, "payload") else r.get("file_path", "?")
        name = r.get("name", "?") if isinstance(r, dict) else getattr(r, "payload", {}).get("name", "?")
        console.print(f"[bold cyan]{i}. {fp}[/bold cyan] [green]{name}[/green]")


# --- Overview ---


@app.command()
def overview():
    """Show codebase overview (language distribution, patterns, complexity)."""
    _require_daemon()
    import httpx

    try:
        resp = httpx.get(f"{_base_url()}/overview", headers=_auth_headers(), timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        console.print(f"[red]Overview failed: {e}[/red]")
        raise typer.Exit(1)

    console.print(f"\n[bold]Codebase Overview[/bold]  ({data['total_chunks']} chunks)\n")

    if data["languages"]:
        table = Table(title="Languages")
        table.add_column("Language", style="cyan")
        table.add_column("Chunks", style="green")
        for lang, count in data["languages"].items():
            table.add_row(lang, str(count))
        console.print(table)

    if data["patterns"]:
        table = Table(title="Design Patterns")
        table.add_column("Pattern", style="cyan")
        table.add_column("Count", style="green")
        for pat, count in data["patterns"].items():
            table.add_row(pat, str(count))
        console.print(table)

    cx = data["complexity"]
    console.print(f"\n[bold]Complexity:[/bold] avg={cx['average']}, max={cx['max']}, high (>10): {cx['high_count']}")


# --- Claude Code Integration ---


@app.command()
def install_claude():
    """Install Claude Code slash command for RAG search."""
    from rag.integration.claude_code import generate_slash_command

    path = generate_slash_command()
    console.print(f"[green]Installed Claude Code slash command at {path}[/green]")
    console.print("[dim]Use /rag <query> in Claude Code to search your indexed codebase.[/dim]")


# --- Plugin Management ---


@app.command()
def plugins():
    """List installed plugins."""
    from rag.core.plugins import discover_plugins

    found = discover_plugins()
    if not found:
        console.print("[yellow]No plugins found. Place YAML manifests in ~/.rag/plugins/[/yellow]")
        return

    table = Table(title="Installed Plugins")
    table.add_column("Name", style="cyan")
    table.add_column("Version", style="green")
    table.add_column("Patterns", style="dim")
    table.add_column("Domains", style="dim")
    for p in found:
        table.add_row(p.name, p.version, str(len(p.patterns)), str(len(p.domain_keywords)))
    console.print(table)


# --- Collection Management ---


@app.command()
def collections(
    action: str = typer.Argument("list", help="Action: list or delete"),
    name: str = typer.Argument(None, help="Collection name (for delete)"),
):
    """Manage Qdrant collections (list, delete)."""
    import asyncio
    from rag.core.vectorstore import QdrantVectorStore

    async def _run():
        vs = QdrantVectorStore()
        client = await vs._get_client()

        if action == "list":
            colls = await client.get_collections()
            if not colls.collections:
                console.print("[yellow]No collections found.[/yellow]")
                return
            table = Table(title="Collections")
            table.add_column("Name", style="cyan")
            table.add_column("Points", style="green")
            table.add_column("Status", style="dim")
            for c in colls.collections:
                info = await vs.collection_info(c.name)
                table.add_row(c.name, str(info.get("points_count", "?")), info.get("status", "?"))
            console.print(table)

        elif action == "delete":
            if not name:
                console.print("[red]Specify collection name: rag collections delete <name>[/red]")
                return
            await client.delete_collection(name)
            console.print(f"[green]Deleted collection: {name}[/green]")

        else:
            console.print(f"[red]Unknown action: {action}. Use 'list' or 'delete'.[/red]")

        await vs.close()

    asyncio.run(_run())


# --- Verify + Repair ---


@app.command()
def verify(
    path: str = typer.Argument(".", help="Repository path to verify"),
):
    """Check index integrity: orphaned chunks, duplicates, missing files."""
    import asyncio
    from rag.core.vectorstore import QdrantVectorStore

    abs_path = str(Path(path).resolve())

    async def _run():
        vs = QdrantVectorStore()
        client = await vs._get_client()
        settings = get_settings()
        collection = settings.qdrant.code_collection

        try:
            colls = await client.get_collections()
            if collection not in [c.name for c in colls.collections]:
                console.print(f"[yellow]Collection '{collection}' not found. Run 'rag index' first.[/yellow]")
                return
        except Exception:
            console.print(f"[yellow]Collection '{collection}' not found. Run 'rag index' first.[/yellow]")
            return

        # Scroll all points
        indexed_files: dict[str, int] = {}  # file_path -> chunk count
        duplicates: dict[str, int] = {}  # content_hash -> count
        total_points = 0

        offset = None
        while True:
            points, offset = await client.scroll(
                collection_name=collection,
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            if not points:
                break
            for p in points:
                total_points += 1
                if p.payload:
                    fp = p.payload.get("file_path", "")
                    indexed_files[fp] = indexed_files.get(fp, 0) + 1
                    ch = p.payload.get("content_hash", "")
                    if ch:
                        duplicates[ch] = duplicates.get(ch, 0) + 1
            if offset is None:
                break

        # Check for orphans (indexed but file doesn't exist on disk)
        orphans = []
        for fp in indexed_files:
            full = Path(abs_path) / fp
            if not full.exists():
                orphans.append(fp)

        # Check for duplicates
        dup_count = sum(1 for c in duplicates.values() if c > 1)

        console.print(f"\n[bold]Index Verification: {abs_path}[/bold]\n")
        console.print(f"  Total chunks: {total_points}")
        console.print(f"  Unique files:  {len(indexed_files)}")
        console.print(f"  Orphaned files (indexed but deleted): [{'red' if orphans else 'green'}]{len(orphans)}[/{'red' if orphans else 'green'}]")
        if orphans:
            for o in orphans[:10]:
                console.print(f"    - {o}")
            if len(orphans) > 10:
                console.print(f"    ... and {len(orphans) - 10} more")
        console.print(f"  Duplicate chunks: [{'yellow' if dup_count else 'green'}]{dup_count}[/{'yellow' if dup_count else 'green'}]")

        if orphans or dup_count:
            console.print("\n  [dim]Run 'rag repair' to fix issues.[/dim]")
        else:
            console.print("\n  [green]Index is healthy.[/green]")

        await vs.close()

    asyncio.run(_run())


@app.command()
def repair(
    path: str = typer.Argument(".", help="Repository path"),
    remove_orphans: bool = typer.Option(True, "--remove-orphans/--keep-orphans", help="Remove orphaned chunks"),
):
    """Repair index by removing orphaned chunks and duplicates."""
    import asyncio
    from rag.core.vectorstore import QdrantVectorStore

    abs_path = str(Path(path).resolve())

    async def _run():
        vs = QdrantVectorStore()
        client = await vs._get_client()
        settings = get_settings()
        collection = settings.qdrant.code_collection

        removed = 0

        if remove_orphans:
            # Find orphaned files
            offset = None
            orphan_files: set[str] = set()
            while True:
                points, offset = await client.scroll(
                    collection_name=collection,
                    limit=100,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                if not points:
                    break
                for p in points:
                    if p.payload:
                        fp = p.payload.get("file_path", "")
                        if fp and not (Path(abs_path) / fp).exists():
                            orphan_files.add(fp)
                if offset is None:
                    break

            for fp in orphan_files:
                await vs.delete_by_filter(collection, "file_path", fp)
                removed += 1
                console.print(f"  [dim]Removed orphan: {fp}[/dim]")

        console.print(f"\n[green]Repair complete. Removed {removed} orphaned file groups.[/green]")
        await vs.close()

    asyncio.run(_run())


# --- Diagnose ---


@app.command()
def diagnose():
    """Run full system health check."""
    import httpx

    console.print("\n[bold]RAG System Diagnostics[/bold]\n")

    # 1. Daemon
    try:
        resp = httpx.get(f"{_base_url()}/health", timeout=3)
        data = resp.json()
        components = data.get("components", {})
        console.print(f"  Daemon:    [green]running[/green] on {_base_url()}")
        for comp, status in components.items():
            color = "green" if status in ("ok", "enabled") else "yellow" if status == "unavailable" else "red"
            console.print(f"    {comp}: [{color}]{status}[/{color}]")
    except Exception:
        console.print("  Daemon:    [red]not running[/red]")
        console.print("  [dim]Start with: rag start --headless[/dim]")
        return

    # 2. Ollama
    settings = get_settings()
    try:
        resp = httpx.get(f"{settings.llm.ollama_url}/api/tags", timeout=3)
        models = [m["name"] for m in resp.json().get("models", [])]
        console.print(f"\n  Ollama:    [green]running[/green] ({len(models)} models)")
        # Check for required models
        embed_model = settings.embeddings.model.split("/")[-1].lower()
        has_embed = any(embed_model in m.lower() for m in models)
        has_agent = any(settings.llm.agent_model in m for m in models)
        console.print(f"    Embedder ({settings.embeddings.model}): [{'green' if has_embed else 'red'}]{'found' if has_embed else 'not found'}[/{'green' if has_embed else 'red'}]")
        console.print(f"    Agent ({settings.llm.agent_model}): [{'green' if has_agent else 'yellow'}]{'found' if has_agent else 'not found'}[/{'green' if has_agent else 'yellow'}]")
    except Exception:
        console.print(f"\n  Ollama:    [red]not running[/red] at {settings.llm.ollama_url}")
        console.print("  [dim]Start with: ollama serve[/dim]")

    # 3. LSP
    from rag.core.lsp import detect_lsp_servers
    servers = detect_lsp_servers()
    found = [s for s in servers if s.found]
    missing = [s for s in servers if not s.found]
    console.print(f"\n  LSP:       [green]{len(found)} found[/green], [yellow]{len(missing)} missing[/yellow]")
    for s in missing:
        console.print(f"    [dim]{s.language}: {s.install_hint}[/dim]")

    # 4. Config
    console.print(f"\n  Config:    {CONFIG_PATH}")
    if settings.qdrant.mode == "server":
        console.print(f"  Qdrant:    server ({settings.qdrant.url})")
        console.print("  Data:      ~/.rag/qdrant_server (Docker volume mount)")
    else:
        console.print(f"  Qdrant:    embedded ({settings.qdrant.resolved_path})")

    # 5. Cache
    try:
        from rag.core.cache import EmbeddingCache
        cache = EmbeddingCache()
        stats = cache.stats()
        console.print(f"  Cache:     {stats['total_entries']} entries, {stats['hit_count']} hits, {stats['miss_count']} misses")
    except Exception:
        console.print("  Cache:     [dim]not initialized[/dim]")

    console.print()


# --- Service (launchd / systemd) ---

service_app = typer.Typer(
    name="service",
    help="Install/uninstall the RAG daemon as an OS-level service",
    no_args_is_help=True,
)


@service_app.command("install")
def service_install():
    """Install the RAG daemon as a launchd agent (macOS) so it auto-starts."""
    import sys
    from rag.integration.supervisor import install_service

    try:
        result = install_service(python_executable=sys.executable)
    except NotImplementedError as e:
        console.print(f"[yellow]{e}[/yellow]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Service install failed: {e}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]Installed:[/green] {result['plist_path']}")
    console.print(f"[green]Logs:[/green] {result['stdout_log']}")
    console.print(f"[green]Errors:[/green] {result['stderr_log']}")
    console.print("[dim]Daemon will auto-start on login and restart on crash.[/dim]")


@service_app.command("uninstall")
def service_uninstall():
    """Remove the RAG daemon launchd agent."""
    from rag.integration.supervisor import uninstall_service

    try:
        path = uninstall_service()
    except NotImplementedError as e:
        console.print(f"[yellow]{e}[/yellow]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Service uninstall failed: {e}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]Uninstalled:[/green] {path}")


@service_app.command("status")
def service_status():
    """Report whether the launchd agent is registered."""
    from rag.integration.supervisor import service_status as _status

    try:
        info = _status()
    except NotImplementedError as e:
        console.print(f"[yellow]{e}[/yellow]")
        raise typer.Exit(1)

    console.print(f"  Plist:      {info['plist_path']}")
    console.print(f"  Installed:  {'[green]yes[/green]' if info['installed'] else '[yellow]no[/yellow]'}")
    console.print(f"  Loaded:     {'[green]yes[/green]' if info['loaded'] else '[yellow]no[/yellow]'}")


app.add_typer(service_app, name="service")
