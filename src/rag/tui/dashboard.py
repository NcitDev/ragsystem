"""Main TUI dashboard layout."""

from __future__ import annotations

from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Header, Static

from rag.tui.widgets import (
    IndexStatsWidget,
    LSPStatusWidget,
    ModelCard,
    QueryLogEntry,
)


class ModelsPanel(Static):
    """Panel showing model status."""

    DEFAULT_CSS = """
    ModelsPanel {
        height: auto;
        border: solid $accent;
        padding: 1;
        margin: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("[bold]Models[/bold]", id="models-title")
        yield ModelCard("Embedder", id="embedder-card")
        yield ModelCard("Reranker", id="reranker-card")
        yield ModelCard("Sparse", id="sparse-card")
        yield ModelCard("Agent LLM", id="agent-card")


class IndexPanel(Static):
    """Panel showing index statistics."""

    DEFAULT_CSS = """
    IndexPanel {
        height: auto;
        border: solid $accent;
        padding: 1;
        margin: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("[bold]Index[/bold]")
        yield IndexStatsWidget(id="index-stats")


class LSPPanel(Static):
    """Panel showing LSP server status."""

    DEFAULT_CSS = """
    LSPPanel {
        height: auto;
        border: solid $accent;
        padding: 1;
        margin: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("[bold]LSP Enrichment[/bold]")
        yield LSPStatusWidget(id="lsp-status")


class ServerPanel(Static):
    """Panel showing server info."""

    DEFAULT_CSS = """
    ServerPanel {
        height: 3;
        border: solid $accent;
        padding: 0 1;
        margin: 0 1;
    }
    """

    def __init__(self, host: str, port: int, **kwargs):
        super().__init__(**kwargs)
        self._host = host
        self._port = port

    def render(self) -> str:
        return f" Server: [green]\u25cf[/green] listening on [bold]{self._host}:{self._port}[/bold]"


class QueryLogPanel(VerticalScroll):
    """Scrollable query log."""

    DEFAULT_CSS = """
    QueryLogPanel {
        border: solid $accent;
        padding: 1;
        margin: 0 1;
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("[bold]Live Query Log[/bold]", id="log-title")
        yield Static("[dim]Waiting for queries...[/dim]", id="log-placeholder")

    def add_entry(self, query: str, results: int, latency_ms: float) -> None:
        placeholder = self.query_one("#log-placeholder", Static)
        if placeholder:
            placeholder.remove()

        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = QueryLogEntry(timestamp, query, results, latency_ms)
        self.mount(entry)
        self.scroll_end(animate=False)

    def clear_log(self) -> None:
        for child in list(self.children):
            if isinstance(child, QueryLogEntry):
                child.remove()
        if not self.query(QueryLogEntry):
            self.mount(Static("[dim]Waiting for queries...[/dim]", id="log-placeholder"))


class Dashboard(Vertical):
    """Main dashboard layout."""

    DEFAULT_CSS = """
    Dashboard {
        height: 1fr;
    }
    """

    def __init__(self, host: str, port: int, **kwargs):
        super().__init__(**kwargs)
        self._host = host
        self._port = port

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="left-column"):
                yield ModelsPanel()
                yield IndexPanel()
                yield LSPPanel()
            with Vertical(id="right-column"):
                yield ServerPanel(self._host, self._port)
                yield QueryLogPanel(id="query-log")
        yield Footer()
