"""Typer CLI — thin client that talks to the RAG daemon via HTTP."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from rag.config import CONFIG_PATH, ensure_rag_home, get_or_create_token, get_settings

app = typer.Typer(
    name="rag",
    help="Standalone RAG system for code search",
    no_args_is_help=True,
)
console = Console()


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
    proc = subprocess.Popen(
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
            subprocess.Popen(
                [sys.executable, "-m", "rag", "start"],
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
    import uvicorn

    from rag.server import app as fastapi_app

    settings = get_settings()
    console.print(
        f"[green]Starting RAG server on {settings.server.host}:{settings.server.port}[/green]"
    )
    uvicorn.run(
        fastapi_app,
        host=settings.server.host,
        port=settings.server.port,
        log_level="info",
    )


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
            json={"query": query, "top_k": top_k, "rerank": not no_rerank},
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
    if name:
        from rag.core.repos import RepoManager
        mgr = RepoManager()
        mgr.register(name, abs_path)
        console.print(f"[green]Registered repo '{name}' at {abs_path}[/green]")

    console.print(f"[green]Indexing {abs_path}...[/green]")

    try:
        resp = httpx.post(
            f"{_base_url()}/index",
            json={"repo_path": abs_path, "full": full, "languages": languages},
            headers=_auth_headers(),
            timeout=600,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        error = e.response.json() if e.response.headers.get("content-type", "").startswith("application/json") else {}
        console.print(f"[red]Index failed: {error.get('detail', e)}[/red]")
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
    if data["errors"]:
        table.add_row("Errors", str(len(data["errors"])))
    console.print(table)


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
    import asyncio
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
    console.print(f"  Data:      {settings.qdrant.resolved_path}")

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
