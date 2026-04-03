"""Textual TUI app with embedded uvicorn HTTP server — single process."""

from __future__ import annotations

import asyncio

import structlog
import uvicorn
from textual.app import App, ComposeResult
from textual.binding import Binding

from rag.config import ensure_rag_home, get_settings
from rag.core.lsp import detect_lsp_servers
from rag.tui.dashboard import Dashboard
from rag.tui.dashboard import QueryLogPanel
from rag.tui.widgets import IndexStatsWidget, LSPStatusWidget, ModelCard

logger = structlog.get_logger()


class RAGApp(App):
    """RAG System TUI — dashboard + embedded HTTP server."""

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
        self._server: uvicorn.Server | None = None
        self._server_task: asyncio.Task | None = None
        self._poll_task: asyncio.Task | None = None

    def compose(self) -> ComposeResult:
        settings = get_settings()
        yield Dashboard(settings.server.host, settings.server.port)

    async def on_mount(self) -> None:
        ensure_rag_home()
        self._server_task = asyncio.create_task(self._run_server())
        # Give server a moment to start, then update UI
        self.set_timer(1.0, self._update_model_status)
        self.set_timer(2.0, self._update_lsp_status)
        self.set_timer(3.0, self._update_index_stats)
        # Start periodic polling for query log
        self._poll_task = asyncio.create_task(self._poll_status())

    async def _run_server(self) -> None:
        """Run uvicorn in the same event loop as Textual."""
        from rag.server import app as fastapi_app

        settings = get_settings()
        config = uvicorn.Config(
            fastapi_app,
            host=settings.server.host,
            port=settings.server.port,
            log_level="warning",
        )
        self._server = uvicorn.Server(config)
        await self._server.serve()

    async def _update_model_status(self) -> None:
        """Update model cards with current status."""
        settings = get_settings()

        try:
            embedder_card = self.query_one("#embedder-card", ModelCard)
            reranker_card = self.query_one("#reranker-card", ModelCard)
            sparse_card = self.query_one("#sparse-card", ModelCard)
            agent_card = self.query_one("#agent-card", ModelCard)

            # Check what provider the embedder selected
            from rag.server import _state

            embedder = _state.get("embedder")
            provider = embedder.provider if embedder else "initializing"

            embedder_card.update_info(
                settings.embeddings.model, provider, "running" if embedder else "unknown"
            )
            reranker_card.update_info(
                settings.reranker.model, "fastembed", "ready"
            )
            sparse_card.update_info(
                settings.sparse.model, "fastembed", "ready"
            )
            agent_card.update_info(
                settings.llm.agent_model, "ollama", "unknown"
            )
        except Exception as e:
            logger.debug("tui_update_error", error=str(e))

    async def _update_lsp_status(self) -> None:
        """Detect LSP servers and update the panel."""
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
        """Update index statistics."""
        try:
            from rag.server import _state

            vectorstore = _state.get("vectorstore")
            if vectorstore:
                settings = get_settings()
                stats = await vectorstore.collection_info(settings.qdrant.code_collection)
                stats_widget = self.query_one("#index-stats", IndexStatsWidget)
                stats_widget.update_stats(stats)
        except Exception as e:
            logger.debug("tui_update_error", error=str(e))

    async def _poll_status(self) -> None:
        """Periodically refresh index stats."""
        while True:
            await asyncio.sleep(10)
            await self._update_index_stats()

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
        """Shut down server and exit gracefully."""
        self.notify("Shutting down...")

        # Stop polling
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        # Signal server to stop and wait for drain
        if self._server:
            self._server.should_exit = True
            if self._server_task:
                try:
                    await asyncio.wait_for(self._server_task, timeout=5)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass

        # Close SQLite
        from rag.storage.db import close_connection
        close_connection()

        self.exit()
