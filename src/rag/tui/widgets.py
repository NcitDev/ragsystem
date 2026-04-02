"""Custom TUI widgets for the RAG dashboard."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Static


class StatusIndicator(Static):
    """A colored status indicator: green dot = running, red = stopped."""

    status = reactive("unknown")

    def __init__(self, label: str, **kwargs):
        super().__init__(**kwargs)
        self._label = label

    def render(self) -> str:
        if self.status == "running":
            dot = "[green]\u25cf[/green]"
        elif self.status == "ready":
            dot = "[green]\u25cf[/green]"
        elif self.status == "missing":
            dot = "[red]\u2717[/red]"
        elif self.status == "degraded":
            dot = "[yellow]\u25cf[/yellow]"
        else:
            dot = "[dim]\u25cb[/dim]"
        return f" {dot} {self._label}: {self.status}"


class ModelCard(Static):
    """Displays model name, provider, and status."""

    def __init__(self, role: str, model: str = "", provider: str = "", **kwargs):
        super().__init__(**kwargs)
        self._role = role
        self._model = model
        self._provider = provider
        self._status = "unknown"

    def update_info(self, model: str, provider: str, status: str) -> None:
        self._model = model
        self._provider = provider
        self._status = status
        self.refresh()

    def render(self) -> str:
        if self._status == "running":
            dot = "[green]\u25cf[/green]"
        elif self._status == "ready":
            dot = "[green]\u25cf[/green]"
        else:
            dot = "[dim]\u25cb[/dim]"

        provider_str = f"({self._provider})" if self._provider else ""
        model_short = self._model.split("/")[-1] if self._model else "?"
        return f" {dot} {self._role}: [bold]{model_short}[/bold] [dim]{provider_str}[/dim]"


class QueryLogEntry(Static):
    """A single entry in the query log."""

    def __init__(self, timestamp: str, query: str, results: int, latency_ms: float, **kwargs):
        super().__init__(**kwargs)
        self._timestamp = timestamp
        self._query = query
        self._results = results
        self._latency = latency_ms

    def render(self) -> str:
        q = self._query[:50] + "..." if len(self._query) > 50 else self._query
        return f" [dim]{self._timestamp}[/dim]  {q}  [cyan]{self._results} res[/cyan]  [dim]{self._latency:.0f}ms[/dim]"


class LSPStatusWidget(Static):
    """Shows LSP server detection status with install hints."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._servers: list[dict] = []

    def update_servers(self, servers: list[dict]) -> None:
        self._servers = servers
        self.refresh()

    def render(self) -> str:
        if not self._servers:
            return " [dim]No languages detected[/dim]"

        lines = []
        missing_hints = []
        for s in self._servers:
            if s["found"]:
                lines.append(f" [green]\u25cf[/green] {s['name']:<20} [dim]{s['language']}[/dim]")
            else:
                lines.append(f" [red]\u2717[/red] {s['name']:<20} [dim]{s['language']}[/dim]")
                missing_hints.append(f"   {s['install_hint']}")

        if missing_hints:
            lines.append("")
            lines.append(" [yellow]\u26a0 Install for better search:[/yellow]")
            lines.extend(missing_hints)

        return "\n".join(lines)


class IndexStatsWidget(Static):
    """Shows index statistics."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._stats: dict = {}

    def update_stats(self, stats: dict) -> None:
        self._stats = stats
        self.refresh()

    def render(self) -> str:
        if not self._stats:
            return " [dim]No index data[/dim]"

        points = self._stats.get("points_count", 0)
        status = self._stats.get("status", "unknown")
        return f" Documents: [bold]{points}[/bold]  Status: {status}"
