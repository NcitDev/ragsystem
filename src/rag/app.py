"""Textual TUI app — read-only HTTP client to the RAG daemon."""

from __future__ import annotations

import asyncio

import httpx
import structlog
from textual.app import App, ComposeResult
from textual.binding import Binding

from rag.config import ensure_rag_home, get_or_create_token, get_settings
from rag.core.lsp import detect_lsp_servers
from rag.tui.dashboard import Dashboard
from rag.tui.dashboard import QueryLogPanel
from rag.tui.widgets import IndexStatsWidget, LSPStatusWidget, ModelCard

logger = structlog.get_logger()


class RAGApp(App):
    """RAG System TUI — dashboard for the running daemon."""

    TITLE = "RAG System"
    SUB_TITLE = "Code Search Engine"

    CSS = """
    Screen {
        layout: vertical;
    }
    #left-column {
        width: 45;
        min-width: 40;
    }
    #right-column {
        width: 1fr;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("i", "reindex", "Reindex"),
        Binding("c", "clear_log", "Clear Log"),
    ]

    def __init__(self):
        super().__init__()
        self._poll_task: asyncio.Task | None = None
        self._daemon_warned = False

    def compose(self) -> ComposeResult:
        settings = get_settings()
        yield Dashboard(settings.server.host, settings.server.port)

    async def on_mount(self) -> None:
        ensure_rag_home()
        # All state comes from the daemon over HTTP — no in-process server.
        self.set_timer(0.5, self._update_model_status)
        self.set_timer(1.5, self._update_lsp_status)
        self.set_timer(1.0, self._update_index_stats)
        # Periodic refresh
        self._poll_task = asyncio.create_task(self._poll_status())

    # --- HTTP plumbing ---

    def _base_url(self) -> str:
        settings = get_settings()
        return f"http://{settings.server.host}:{settings.server.port}"

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {get_or_create_token()}"}

    async def _http_get(self, path: str, *, auth: bool = True, timeout: float = 3.0) -> dict | None:
        """GET helper that returns JSON dict or None on failure."""
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                headers = self._auth_headers() if auth else {}
                resp = await client.get(f"{self._base_url()}{path}", headers=headers)
                if resp.status_code == 200:
                    return resp.json()
                logger.debug("tui_http_non_200", path=path, status=resp.status_code)
                return None
        except Exception as e:
            logger.debug("tui_http_error", path=path, error=str(e))
            return None

    def _warn_daemon_down(self) -> None:
        if not self._daemon_warned:
            self._daemon_warned = True
            try:
                self.notify(
                    "Daemon not reachable. Start with: rag start --headless",
                    severity="warning",
                    timeout=10,
                )
            except Exception:
                pass

    # --- UI updates ---

    async def _update_model_status(self) -> None:
        """Update model cards from daemon /health and /status."""
        settings = get_settings()

        try:
            embedder_card = self.query_one("#embedder-card", ModelCard)
            agent_card = self.query_one("#agent-card", ModelCard)

            health = await self._http_get("/health", auth=False)
            status = await self._http_get("/status")

            if health is None and status is None:
                self._warn_daemon_down()
                embedder_card.update_info(settings.embeddings.model, "?", "daemon down")
                agent_card.update_info(settings.llm.agent_model, "ollama", "daemon down")
                return

            # Daemon is up — clear warned flag so reconnect re-arms it on next outage.
            self._daemon_warned = False

            components = (health or {}).get("components", {}) if health else {}
            provider = (status or {}).get("embedder_provider") or components.get("embedder", "?")
            embedder_model = (status or {}).get("embedder_model") or settings.embeddings.model

            embedder_card.update_info(
                embedder_model, str(provider), "running" if provider not in ("?", "not_initialized") else "unknown"
            )
            ollama_status = components.get("ollama", "unknown")
            agent_card.update_info(settings.llm.agent_model, "ollama", ollama_status)
        except Exception as e:
            logger.debug("tui_update_error", error=str(e))

    async def _update_lsp_status(self) -> None:
        """Detect LSP servers locally and update the panel.

        LSP detection is a local subprocess probe — it doesn't go through the daemon.
        """
        try:
            lsp_widget = self.query_one("#lsp-status", LSPStatusWidget)
            servers = detect_lsp_servers()
            lsp_widget.update_servers([
                {
                    "language": s.language,
                    "name": s.name,
                    "found": s.found,
                    "install_hint": s.install_hint,
                }
                for s in servers
            ])
        except Exception as e:
            logger.debug("tui_update_error", error=str(e))

    async def _update_index_stats(self) -> None:
        """Update index statistics from /status collections list."""
        try:
            data = await self._http_get("/status")
            if not data:
                self._warn_daemon_down()
                return

            settings = get_settings()
            code_coll = settings.qdrant.code_collection
            stats = None
            for coll in data.get("collections", []) or []:
                if coll.get("name") == code_coll:
                    stats = coll
                    break
            if stats is None and data.get("collections"):
                stats = data["collections"][0]

            if stats:
                stats_widget = self.query_one("#index-stats", IndexStatsWidget)
                stats_widget.update_stats(stats)
        except Exception as e:
            logger.debug("tui_update_error", error=str(e))

    async def _poll_status(self) -> None:
        """Periodically refresh model + index stats."""
        while True:
            await asyncio.sleep(10)
            await self._update_index_stats()
            await self._update_model_status()

    # --- Actions ---

    def action_reindex(self) -> None:
        """Trigger reindex of current directory."""
        self.notify("Reindexing... use 'rag index <path>' from another terminal")

    def action_clear_log(self) -> None:
        """Clear the query log."""
        try:
            log = self.query_one("#query-log", QueryLogPanel)
            log.clear_log()
        except Exception as e:
            logger.debug("tui_update_error", error=str(e))

    async def action_quit(self) -> None:
        """Exit gracefully. Daemon keeps running."""
        # Stop polling
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        # Close any local SQLite connection (query log, etc).
        try:
            from rag.storage.db import close_connection
            close_connection()
        except Exception:
            pass

        self.exit()
