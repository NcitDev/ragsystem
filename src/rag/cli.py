"""Typer CLI — thin client that talks to the RAG daemon via HTTP."""

from __future__ import annotations

import sys

import typer
from rich.console import Console
from rich.table import Table

from rag.config import CONFIG_PATH, ensure_rag_home, get_settings

app = typer.Typer(
    name="rag",
    help="Standalone RAG system for code search",
    no_args_is_help=True,
)
console = Console()

DEFAULT_BASE_URL = "http://127.0.0.1:7890"


def _base_url() -> str:
    settings = get_settings()
    return f"http://{settings.server.host}:{settings.server.port}"


def _check_daemon():
    """Check if daemon is running."""
    import httpx

    try:
        resp = httpx.get(f"{_base_url()}/health", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


@app.command()
def start(
    headless: bool = typer.Option(False, "--headless", help="Run without TUI"),
):
    """Start the RAG daemon (TUI + HTTP server)."""
    ensure_rag_home()

    if headless:
        import uvicorn

        from rag.server import app as fastapi_app

        settings = get_settings()
        console.print(f"[green]Starting RAG server on {settings.server.host}:{settings.server.port}[/green]")
        uvicorn.run(fastapi_app, host=settings.server.host, port=settings.server.port, log_level="info")
    else:
        from rag.app import RAGApp

        tui = RAGApp()
        tui.run()


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    top_k: int = typer.Option(5, "--top-k", "-k", help="Number of results"),
    no_rerank: bool = typer.Option(False, "--no-rerank", help="Skip reranking"),
):
    """Search the indexed codebase."""
    if not _check_daemon():
        console.print("[red]RAG daemon is not running. Start it with: rag start[/red]")
        raise typer.Exit(1)

    import httpx

    resp = httpx.post(
        f"{_base_url()}/search",
        json={"query": query, "top_k": top_k, "rerank": not no_rerank},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()

    if not data["results"]:
        console.print("[yellow]No results found.[/yellow]")
        return

    console.print(f"\n[bold]Results for:[/bold] {data['query']}  ({data['total']} hits, {data['latency_ms']}ms)\n")

    for i, result in enumerate(data["results"], 1):
        console.print(f"[bold cyan]{i}. {result['file_path']}:{result['lines']}[/bold cyan]")
        console.print(f"   [dim]{result['chunk_type']}[/dim] [green]{result['name']}[/green]  score={result['score']}")
        # Show first 5 lines of code
        code_lines = result["code"].split("\n")[:5]
        for line in code_lines:
            console.print(f"   [dim]{line}[/dim]")
        console.print()


@app.command()
def index(
    path: str = typer.Argument(".", help="Path to repository"),
    full: bool = typer.Option(False, "--full", help="Force full re-index"),
    languages: list[str] = typer.Option(None, "--lang", "-l", help="Languages to index"),
):
    """Index a repository."""
    if not _check_daemon():
        console.print("[red]RAG daemon is not running. Start it with: rag start[/red]")
        raise typer.Exit(1)

    import httpx

    from pathlib import Path as P

    abs_path = str(P(path).resolve())
    console.print(f"[green]Indexing {abs_path}...[/green]")

    resp = httpx.post(
        f"{_base_url()}/index",
        json={"repo_path": abs_path, "full": full, "languages": languages},
        timeout=600,
    )
    resp.raise_for_status()
    data = resp.json()

    table = Table(title="Index Results")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Files processed", str(data["files_processed"]))
    table.add_row("Chunks indexed", str(data["chunks_indexed"]))
    table.add_row("Files skipped", str(data["files_skipped"]))
    table.add_row("Files deleted", str(data["files_deleted"]))
    if data["errors"]:
        table.add_row("Errors", str(len(data["errors"])))

    console.print(table)


@app.command()
def status():
    """Show system status."""
    if not _check_daemon():
        console.print("[red]RAG daemon is not running. Start it with: rag start[/red]")
        raise typer.Exit(1)

    import httpx

    resp = httpx.get(f"{_base_url()}/status", timeout=5)
    resp.raise_for_status()
    data = resp.json()

    table = Table(title="RAG System Status")
    table.add_column("Component", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Status", data["status"])
    table.add_row("Embedder", f"{data['embedder_model']} ({data['embedder_provider']})")
    table.add_row("Reranker", data["reranker_model"])
    table.add_row("Uptime", f"{data['uptime_seconds']:.0f}s")

    for coll in data["collections"]:
        table.add_row(
            f"Collection: {coll['name']}",
            f"{coll.get('points_count', '?')} points ({coll.get('status', '?')})",
        )

    console.print(table)


@app.command()
def config():
    """Open config file in $EDITOR."""
    import os
    import subprocess

    ensure_rag_home()

    if not CONFIG_PATH.exists():
        # Copy default config
        from shutil import copy2

        from rag.config import DEFAULT_CONFIG

        if DEFAULT_CONFIG.exists():
            copy2(DEFAULT_CONFIG, CONFIG_PATH)
            console.print(f"[green]Created config at {CONFIG_PATH}[/green]")
        else:
            CONFIG_PATH.write_text("# RAG System Configuration\n# See config/default.toml for all options\n")

    editor = os.environ.get("EDITOR", "vim")
    subprocess.run([editor, str(CONFIG_PATH)])
