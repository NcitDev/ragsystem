"""Main TUI dashboard layout."""

from __future__ import annotations

from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    ProgressBar,
    RadioButton,
    RadioSet,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
)

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
        # Reranker + sparse cards were removed when FastEmbed was nuked.
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


class ConnectionPanel(Static):
    """Single-line connection indicator (dot + label)."""

    DEFAULT_CSS = """
    ConnectionPanel {
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(self, host: str, port: int, **kwargs):
        super().__init__(**kwargs)
        self._host = host
        self._port = port
        self._ok = True
        self._reconnects = 0

    def set_state(self, ok: bool, reconnects: int = 0) -> None:
        self._ok = ok
        self._reconnects = reconnects
        self.refresh()

    def render(self) -> str:
        dot = "[green]●[/green]" if self._ok else "[red]●[/red]"
        state = "connected" if self._ok else "DISCONNECTED"
        rc = f" reconnects={self._reconnects}" if self._reconnects else ""
        return f"{dot} {self._host}:{self._port}  [dim]{state}{rc}[/dim]"


class StatsPanel(Static):
    """Rolling latency + qpm + avg results."""

    DEFAULT_CSS = """
    StatsPanel {
        height: auto;
        border: solid $accent;
        padding: 1;
        margin: 0 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._stats = {"count": 0, "p50_ms": 0, "p95_ms": 0, "qpm": 0.0, "avg_results": 0.0}

    def update_stats(self, stats: dict) -> None:
        self._stats = stats
        self.refresh()

    def render(self) -> str:
        s = self._stats
        return (
            f"[bold]Query Stats[/bold]\n"
            f" Count:  {s.get('count', 0)}\n"
            f" p50:    {s.get('p50_ms', 0)} ms\n"
            f" p95:    {s.get('p95_ms', 0)} ms\n"
            f" QPM:    {s.get('qpm', 0)}\n"
            f" Avg results: {s.get('avg_results', 0)}"
        )


class PluginsPanel(VerticalScroll):
    """List of loaded plugins."""

    DEFAULT_CSS = """
    PluginsPanel {
        height: auto;
        border: solid $accent;
        padding: 1;
        margin: 0 1;
    }
    """

    def on_mount(self) -> None:
        self.mount(Static("[bold]Plugins[/bold]"))
        self.mount(Static("[dim]loading...[/dim]", id="plugins-body"))

    def update_plugins(self, plugins: list[dict]) -> None:
        body = self.query_one("#plugins-body", Static)
        if not plugins:
            body.update("[dim]no plugins[/dim]")
            return
        lines = [
            f" {p.get('name', '?')} v{p.get('version', '?')}  patterns={p.get('patterns', 0)}  domains={p.get('domains', 0)}"
            for p in plugins
        ]
        body.update("\n".join(lines))


class CollectionsPanel(VerticalScroll):
    """Multi-repo collection cards."""

    DEFAULT_CSS = """
    CollectionsPanel {
        height: auto;
        border: solid $accent;
        padding: 1;
        margin: 0 1;
    }
    """

    def on_mount(self) -> None:
        self.mount(Static("[bold]Collections[/bold]"))
        self.mount(Static("[dim]loading...[/dim]", id="collections-body"))

    def update_collections(self, cols: list[dict]) -> None:
        body = self.query_one("#collections-body", Static)
        if not cols:
            body.update("[dim]none[/dim]")
            return
        lines = []
        for c in cols:
            status = c.get("status", "?")
            color = "green" if status == "green" else ("yellow" if status == "ok" else "red")
            lines.append(
                f" [{color}]●[/{color}] {c.get('name', '?')}  points={c.get('points_count', 0)}"
            )
        body.update("\n".join(lines))


# ---------------------------------------------------------------------------
# Search tab — input + results list + detail pane
# ---------------------------------------------------------------------------


class SearchTab(Vertical):
    """Search tab: input bar, results list, detail pane."""

    DEFAULT_CSS = """
    SearchTab {
        height: 1fr;
    }
    #search-row {
        height: 3;
        padding: 0 1;
    }
    #search-input {
        width: 2fr;
    }
    #search-mode {
        width: 1fr;
        height: 3;
    }
    #search-strategy {
        width: 1fr;
        height: 3;
    }
    #search-results {
        width: 1fr;
        height: 1fr;
        border: solid $accent;
        margin: 0 1;
    }
    #search-detail {
        width: 2fr;
        height: 1fr;
        border: solid $accent;
        margin: 0 1;
    }
    #search-plan {
        height: auto;
        border: solid $accent;
        padding: 0 1;
        margin: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="search-row"):
            yield Input(placeholder="Type query, Enter to search   (Ctrl+A toggles Ask mode)", id="search-input")
        yield Static("[dim]Strategy: hybrid (planner default)[/dim]", id="search-plan")
        with Horizontal():
            yield ListView(id="search-results")
            yield RichLog(highlight=True, markup=True, id="search-detail")


class AskTab(Vertical):
    """Ask tab: question input, answer pane, citations list."""

    DEFAULT_CSS = """
    AskTab {
        height: 1fr;
    }
    #ask-row {
        height: 3;
        padding: 0 1;
    }
    #ask-input {
        width: 1fr;
    }
    #ask-answer {
        height: 2fr;
        border: solid $accent;
        margin: 0 1;
    }
    #ask-citations {
        height: 1fr;
        border: solid $accent;
        margin: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="ask-row"):
            yield Input(placeholder="Ask a grounded question about the indexed codebase", id="ask-input")
        yield RichLog(highlight=True, markup=True, id="ask-answer")
        yield ListView(id="ask-citations")


class IndexTab(Vertical):
    """Index tab: path input, run button, progress bar, recent files."""

    DEFAULT_CSS = """
    IndexTab {
        height: 1fr;
    }
    #index-row {
        height: 3;
        padding: 0 1;
    }
    #index-path {
        width: 3fr;
    }
    #index-go {
        width: 1fr;
    }
    #index-progress {
        height: 3;
        padding: 0 1;
    }
    #index-status {
        height: 3;
        padding: 0 1;
    }
    #index-recent {
        height: 1fr;
        border: solid $accent;
        margin: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="index-row"):
            yield Input(placeholder="/absolute/path/to/repo  (--full re-index via checkbox)", id="index-path")
            yield Button("Index", id="index-go", variant="primary")
        yield Checkbox("Full re-index (ignore SHA cache)", value=False, id="index-full")
        yield Static("[dim]Idle.[/dim]", id="index-status")
        yield ProgressBar(total=100, show_eta=False, id="index-progress")
        yield ListView(id="index-recent")


class FiltersTab(Vertical):
    """Filter builder + strategy picker (applied to next Search query)."""

    DEFAULT_CSS = """
    FiltersTab {
        height: 1fr;
        padding: 1;
    }
    .filter-group {
        height: auto;
        border: solid $accent;
        padding: 1;
        margin: 0 0 1 0;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("[bold]Language[/bold]", classes="filter-label")
        with Vertical(classes="filter-group"):
            yield Checkbox("kotlin", id="f-lang-kotlin")
            yield Checkbox("java", id="f-lang-java")
            yield Checkbox("python", id="f-lang-python")
            yield Checkbox("dart", id="f-lang-dart")
            yield Checkbox("typescript", id="f-lang-typescript")
        yield Static("[bold]Concurrency[/bold]")
        with Vertical(classes="filter-group"):
            yield Checkbox("is_suspend = true", id="f-is-suspend")
            yield Checkbox("uses_coroutines = true", id="f-uses-coroutines")
            yield Checkbox("uses_flow = true", id="f-uses-flow")
            yield Checkbox("uses_async_java = true", id="f-uses-async-java")
        yield Static("[bold]Chunk type[/bold]")
        with Vertical(classes="filter-group"):
            yield Checkbox("function", id="f-ct-function")
            yield Checkbox("class", id="f-ct-class")
            yield Checkbox("file", id="f-ct-file")
        yield Static("[bold]Strategy override[/bold]")
        with RadioSet(id="f-strategy"):
            yield RadioButton("auto (planner)", value=True, id="strat-auto")
            yield RadioButton("hybrid", id="strat-hybrid")
            yield RadioButton("filtered", id="strat-filtered")
            yield RadioButton("graph_walk", id="strat-graph_walk")
            yield RadioButton("aggregate", id="strat-aggregate")
            yield RadioButton("global", id="strat-global")
            yield RadioButton("naive", id="strat-naive")


class LogsTab(Vertical):
    """Live log tail from daemon /events/recent."""

    DEFAULT_CSS = """
    LogsTab {
        height: 1fr;
    }
    #logs-view {
        height: 1fr;
        border: solid $accent;
        margin: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("[dim]Live event stream from daemon. Bound to last 500 events.[/dim]")
        yield RichLog(highlight=True, markup=True, id="logs-view", wrap=False, max_lines=2000)


class OverviewTab(VerticalScroll):
    """Module summaries + KG communities + top nodes."""

    DEFAULT_CSS = """
    OverviewTab {
        height: 1fr;
        padding: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("[bold]Module Summaries[/bold]", id="ov-summaries-title")
        yield Static("[dim]loading...[/dim]", id="ov-summaries")
        yield Static("\n[bold]Graph Communities[/bold]", id="ov-comm-title")
        yield Static("[dim]loading...[/dim]", id="ov-communities")
        yield Static("\n[bold]Top Connected Nodes[/bold]", id="ov-nodes-title")
        yield Static("[dim]loading...[/dim]", id="ov-nodes")


class DiffTab(Vertical):
    """Wrap rag diff CLI: enter query + since-ref, render output."""

    DEFAULT_CSS = """
    DiffTab {
        height: 1fr;
        padding: 0 1;
    }
    #diff-row {
        height: 3;
    }
    #diff-q {
        width: 2fr;
    }
    #diff-since {
        width: 1fr;
    }
    #diff-go {
        width: 1fr;
    }
    #diff-output {
        height: 1fr;
        border: solid $accent;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="diff-row"):
            yield Input(placeholder="Query", id="diff-q")
            yield Input(placeholder="--since (e.g. HEAD~5)", value="HEAD~5", id="diff-since")
            yield Button("Run", id="diff-go", variant="primary")
        yield RichLog(highlight=True, markup=True, id="diff-output")


class HelpTab(VerticalScroll):
    """Help modal content — hotkeys + config snapshot."""

    DEFAULT_CSS = """
    HelpTab {
        height: 1fr;
        padding: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("[bold]Hotkeys[/bold]")
        yield Static(
            "  q          Quit\n"
            "  ?          Toggle this help\n"
            "  i          Focus Index tab\n"
            "  s          Focus Search tab\n"
            "  a          Focus Ask tab\n"
            "  l          Focus Logs tab\n"
            "  f          Focus Filters tab\n"
            "  o          Focus Overview tab\n"
            "  d          Focus Diff tab\n"
            "  c          Clear active log/results\n"
            "  t          Toggle theme (dark/light)\n"
            "  Ctrl+A     Toggle Ask vs Search mode in Search tab",
            id="help-hotkeys",
        )
        yield Static("\n[bold]Config[/bold]", id="help-config-title")
        yield Static("[dim]loading...[/dim]", id="help-config")


class Dashboard(Vertical):
    """Main dashboard layout — tabbed."""

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
        yield ConnectionPanel(self._host, self._port, id="conn-bar")
        with TabbedContent(initial="tab-home"):
            with TabPane("Home", id="tab-home"):
                with Horizontal():
                    with Vertical(id="home-left"):
                        yield ModelsPanel()
                        yield IndexPanel()
                        yield LSPPanel()
                        yield StatsPanel(id="stats-panel")
                    with Vertical(id="home-right"):
                        yield ServerPanel(self._host, self._port)
                        yield CollectionsPanel(id="collections-panel")
                        yield PluginsPanel(id="plugins-panel")
                        yield QueryLogPanel(id="query-log")
            with TabPane("Search", id="tab-search"):
                yield SearchTab()
            with TabPane("Ask", id="tab-ask"):
                yield AskTab()
            with TabPane("Index", id="tab-index"):
                yield IndexTab()
            with TabPane("Filters", id="tab-filters"):
                yield FiltersTab()
            with TabPane("Overview", id="tab-overview"):
                yield OverviewTab()
            with TabPane("Diff", id="tab-diff"):
                yield DiffTab()
            with TabPane("Logs", id="tab-logs"):
                yield LogsTab()
            with TabPane("Help", id="tab-help"):
                yield HelpTab()
        yield Footer()
