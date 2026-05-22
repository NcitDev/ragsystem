"""RAG System TUI — redesigned dashboard.

Layout follows the Pencil mock in ragsystem.pen:

    ┌──────────────────────────────────────────────────────────────────┐
    │ • Home/Dashboard  ragsys 2 of 8                            14:32 │  status bar
    ├───────────┬──────────────────────────────────────────────────────┤
    │ Home      │                                                       │
    │ Search    │                                                       │
    │ Ask       │            <active screen content>                    │
    │ Index     │                                                       │
    │ Filters   │                                                       │
    │ Logs      │                                                       │
    │ Overview  │                                                       │
    │ Help      │                                                       │
    ├───────────┴──────────────────────────────────────────────────────┤
    │ :cmd  search payment processing                              ↵   │  cmd line
    └──────────────────────────────────────────────────────────────────┘

Colors: dark slate background, teal accent, violet for agent/model, blue for
identifiers. JetBrains Mono / Geist Mono only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import (
    Horizontal,
    Vertical,
    VerticalScroll,
    Container,
)
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
    Input,
    Label,
    ListItem,
    ListView,
    ProgressBar,
    RadioButton,
    RadioSet,
    RichLog,
    Static,
)

# Reuse the existing helper widgets for sub-content; full dashboard frame is new.
from rag.tui.widgets import (
    IndexStatsWidget,
    LSPStatusWidget,
    ModelCard,
    QueryLogEntry,
)


# ---------------------------------------------------------------------------
# Top status bar
# ---------------------------------------------------------------------------


class StatusBar(Static):
    """Always-visible top status bar — traffic-light buttons + state pills.

    Shows: mac-style window controls, screen name, daemon dot, repo,
    embedder model, generator model, qpm, mem usage, clock.
    """

    DEFAULT_CSS = """
    StatusBar {
        dock: top;
        height: 1;
        padding: 0 1;
        background: #12161e;
        color: #5a6a7a;
    }
    """

    daemon_ok = reactive(False)
    repo_name = reactive("(none)")
    embedder = reactive("?")
    gen_model = reactive("?")
    qpm = reactive(0.0)
    mem_mb = reactive(0)
    screen_name = reactive("Home")

    def render(self) -> str:
        lights = "[red]●[/red] [yellow]●[/yellow] [green]●[/green]"
        dot = "[green]●[/green]" if self.daemon_ok else "[red]●[/red]"
        clock = datetime.now().strftime("%H:%M")
        # Shorten model names to keep bar readable on narrow terminals
        embed_short = self.embedder.split(":")[0].replace("qwen3-embedding", "qwen3-emb")[:16]
        gen_short = self.gen_model[:12]
        repo_short = self.repo_name[:18]
        return (
            f"{lights}  [#5ee6d0 b]» {self.screen_name}[/]"
            f"  {dot} daemon"
            f"  [dim]repo=[/dim][#7fb6f0]{repo_short}[/]"
            f"  [dim]emb=[/dim][#5ee6d0]{embed_short}[/]"
            f"  [dim]gen=[/dim][#b084eb]{gen_short}[/]"
            f"  [dim]qpm=[/dim]{self.qpm:.0f}"
            f"  [dim]mem=[/dim]{self.mem_mb}MB"
            f"  [dim]·[/dim]  [#5a6a7a]{clock}[/]"
        )


# ---------------------------------------------------------------------------
# Left sidebar — 8-item nav
# ---------------------------------------------------------------------------


class Sidebar(Static):
    """Left nav. 8 items + section labels. Active row highlighted with
    a teal cursor block and brighter foreground."""

    DEFAULT_CSS = """
    Sidebar {
        dock: left;
        width: 24;
        background: #10161d;
        padding: 1 0;
        border-right: tall #1a1f2a;
    }
    """

    NAV = [
        ("home", "Home", "h"),
        ("search", "Search", "s"),
        ("ask", "Ask", "a"),
        ("index", "Index", "i"),
        ("filters", "Filters", "f"),
        ("overview", "Overview", "o"),
        ("logs", "Logs", "l"),
        ("help", "Help", "?"),
    ]

    active = reactive("home")

    def render(self) -> str:
        lines = ["", "  [#5a6a7a b]NAVIGATION[/]", ""]
        for key, label, hot in self.NAV:
            if key == self.active:
                lines.append(
                    f"  [#5ee6d0 on #141b23] █ {label:<10}[/]  [#5a6a7a]{hot}[/]"
                )
            else:
                lines.append(
                    f"    [#c8d6e5]{label:<10}[/]  [#5a6a7a]{hot}[/]"
                )
        lines += [
            "",
            "  [#5a6a7a b]ACTIONS[/]",
            "",
            "    [#c8d6e5]Palette[/]    [#5a6a7a]⌘K[/]",
            "    [#c8d6e5]Cmd line[/]   [#5a6a7a]:[/]",
            "    [#c8d6e5]Clear[/]      [#5a6a7a]c[/]",
            "    [#c8d6e5]Quit[/]       [#5a6a7a]q[/]",
            "",
            "  [#5a6a7a]──────────────[/]",
            "  [#5a6a7a]rag[/] [#5ee6d0]» tui[/]",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Bottom command line — REPL-style input
# ---------------------------------------------------------------------------


class CmdLine(Container):
    """Always-visible bottom command line.

    Type ``:search foo``, ``:ask "how does X work"``, ``:list is_singleton``,
    ``:index /abs/path``, ``:filter lang=kotlin``, ``:strategy hybrid``,
    ``:goto search`` from any screen.
    """

    DEFAULT_CSS = """
    CmdLine {
        dock: bottom;
        height: 1;
        background: #12161e;
        border-top: tall #1a1f2a;
    }
    CmdLine Label {
        width: 3;
        color: #5ee6d0;
        text-style: bold;
        padding: 0 1;
    }
    CmdLine Input {
        border: none;
        background: #12161e;
        color: #c8d6e5;
        height: 1;
        padding: 0;
    }
    CmdLine Input:focus {
        border: none;
        background: #141b23;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label(":")
            yield Input(
                placeholder='try: search payment · ask how does X work · list is_singleton --lang kotlin · goto logs',
                id="cmd-input",
            )


# ---------------------------------------------------------------------------
# Screen frames — each is a content panel switched into the main area
# ---------------------------------------------------------------------------


class ScreenBase(Container):
    """Common scaffolding for a screen — title row + content slot."""

    DEFAULT_CSS = """
    ScreenBase {
        height: 1fr;
        padding: 0 1;
    }
    .screen-title {
        height: 1;
        color: $accent;
        padding: 0 1;
    }
    """

    title = "Screen"

    def compose(self) -> ComposeResult:
        yield Static(f"[bold]» {self.title}[/bold]", classes="screen-title")
        yield from self.compose_body()

    def compose_body(self) -> ComposeResult:
        yield Static("(no body)")


# ---------- Home ----------


class HomeScreen(ScreenBase):
    title = "Home / Dashboard"

    DEFAULT_CSS = """
    HomeScreen .home-kpis {
        height: 7;
    }
    HomeScreen .kpi {
        border: round $primary 30%;
        padding: 1 2;
        width: 1fr;
        height: 7;
        margin: 0 1;
    }
    HomeScreen .kpi-val {
        color: $accent;
        text-style: bold;
    }
    HomeScreen .home-mid {
        height: 1fr;
    }
    HomeScreen .panel {
        border: round $primary 30%;
        padding: 1 1;
        margin: 0 1;
        height: 1fr;
    }
    """

    def compose_body(self) -> ComposeResult:
        with Horizontal(classes="home-kpis"):
            yield Static(
                "[dim]INDEX[/dim]\n[bold cyan]56 427[/bold cyan]\n[dim]chunks · 137 files[/dim]",
                classes="kpi",
                id="kpi-index",
            )
            yield Static(
                "[dim]EMBEDDER[/dim]\n[bold cyan]qwen3-emb-4b[/bold cyan]\n[dim]Ollama · 12ms[/dim]",
                classes="kpi",
                id="kpi-embedder",
            )
            yield Static(
                "[dim]GENERATOR[/dim]\n[bold magenta]qwen3:8b[/bold magenta]\n[dim]Ollama · streaming[/dim]",
                classes="kpi",
                id="kpi-gen",
            )
            yield Static(
                "[dim]UPTIME[/dim]\n[bold]4d 12h[/bold]\n[dim]42 restarts[/dim]",
                classes="kpi",
                id="kpi-uptime",
            )
        with Horizontal(classes="home-mid"):
            with Vertical(classes="panel"):
                yield Static("[bold]QPM (last 24h)[/bold]")
                yield Static(
                    "[cyan]▁▂▃▅▆▇█▇▆▅▃▂▁▂▄▆██▇▅▃▂▁▁[/cyan]   peak 38",
                    id="qpm-spark",
                )
                yield Static("")
                yield Static("[bold]Recent queries[/bold]")
                yield ListView(id="home-recent-queries")
            with Vertical(classes="panel"):
                yield Static("[bold]Plugins[/bold]")
                yield Static("[dim]loading...[/dim]", id="home-plugins")
                yield Static("")
                yield Static("[bold]Collections[/bold]")
                yield Static("[dim]loading...[/dim]", id="home-collections")


# ---------- Search ----------


class SearchScreen(ScreenBase):
    title = "Search"

    DEFAULT_CSS = """
    SearchScreen .search-input-row { height: 3; padding: 0 1; }
    SearchScreen #search-input { width: 1fr; }
    SearchScreen .search-mid { height: 1fr; }
    SearchScreen #search-results {
        width: 2fr;
        border: round $primary 30%;
        margin: 0 1;
    }
    SearchScreen #search-detail {
        width: 3fr;
        border: round $primary 30%;
        margin: 0 1;
    }
    SearchScreen #search-plan {
        height: 6;
        border: round $primary 30%;
        margin: 0 1;
        padding: 0 1;
    }
    """

    def compose_body(self) -> ComposeResult:
        with Horizontal(classes="search-input-row"):
            yield Input(
                placeholder="Query — Enter to search   (Ctrl+A toggles Ask mode)",
                id="search-input",
            )
        with Horizontal(classes="search-mid"):
            yield ListView(id="search-results")
            yield RichLog(highlight=True, markup=True, id="search-detail", wrap=False)
        yield Static("[dim]Planner inspector will show after first query.[/dim]", id="search-plan")


# ---------- Ask ----------


class AskScreen(ScreenBase):
    title = "Ask (RAG)"

    DEFAULT_CSS = """
    AskScreen .ask-input-row { height: 3; padding: 0 1; }
    AskScreen #ask-input { width: 1fr; }
    AskScreen .ask-mid { height: 1fr; }
    AskScreen #ask-answer {
        width: 3fr;
        border: round $primary 30%;
        margin: 0 1;
    }
    AskScreen #ask-citations {
        width: 2fr;
        border: round $primary 30%;
        margin: 0 1;
    }
    AskScreen #ask-meta {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    """

    def compose_body(self) -> ComposeResult:
        with Horizontal(classes="ask-input-row"):
            yield Input(
                placeholder="Ask a grounded question — Enter to run",
                id="ask-input",
            )
        with Horizontal(classes="ask-mid"):
            yield RichLog(highlight=True, markup=True, id="ask-answer")
            yield ListView(id="ask-citations")
        yield Static("", id="ask-meta")


# ---------- Index ----------


class IndexScreen(ScreenBase):
    title = "Index Manager"

    DEFAULT_CSS = """
    IndexScreen .index-input-row { height: 3; padding: 0 1; }
    IndexScreen #index-path { width: 3fr; }
    IndexScreen #index-go { width: 1fr; }
    IndexScreen #index-status {
        height: 3;
        border: round $primary 30%;
        padding: 0 1;
        margin: 0 1;
    }
    IndexScreen #index-progress {
        height: 1;
        margin: 0 2;
    }
    IndexScreen .index-mid { height: 1fr; }
    IndexScreen #index-repos {
        width: 2fr;
        border: round $primary 30%;
        margin: 0 1;
    }
    IndexScreen #index-recent {
        width: 3fr;
        border: round $primary 30%;
        margin: 0 1;
    }
    """

    def compose_body(self) -> ComposeResult:
        with Horizontal(classes="index-input-row"):
            yield Input(placeholder="/absolute/path/to/repo", id="index-path")
            yield Button("Index", id="index-go", variant="primary")
        yield Static("[dim]Idle. Pick a path above and press Index.[/dim]", id="index-status")
        yield ProgressBar(total=100, show_eta=False, id="index-progress")
        with Horizontal(classes="index-mid"):
            yield ListView(id="index-repos")
            yield ListView(id="index-recent")


# ---------- Filters ----------


class FiltersScreen(ScreenBase):
    title = "Filters & Strategy"

    DEFAULT_CSS = """
    FiltersScreen .filters-mid { height: 1fr; }
    FiltersScreen .filter-group {
        border: round $primary 30%;
        padding: 1 1;
        margin: 0 1;
        width: 1fr;
        height: auto;
    }
    FiltersScreen .group-title { color: $accent; }
    """

    def compose_body(self) -> ComposeResult:
        with Horizontal(classes="filters-mid"):
            with Vertical(classes="filter-group"):
                yield Static("[bold]Language[/bold]", classes="group-title")
                yield Checkbox("kotlin", id="f-lang-kotlin")
                yield Checkbox("java", id="f-lang-java")
                yield Checkbox("python", id="f-lang-python")
                yield Checkbox("dart", id="f-lang-dart")
                yield Checkbox("typescript", id="f-lang-typescript")
            with Vertical(classes="filter-group"):
                yield Static("[bold]Concurrency[/bold]", classes="group-title")
                yield Checkbox("is_suspend", id="f-is-suspend")
                yield Checkbox("uses_coroutines", id="f-uses-coroutines")
                yield Checkbox("uses_flow", id="f-uses-flow")
                yield Checkbox("uses_async_java", id="f-uses-async-java")
            with Vertical(classes="filter-group"):
                yield Static("[bold]Pattern[/bold]", classes="group-title")
                yield Checkbox("is_singleton", id="f-is-singleton")
                yield Checkbox("is_data_class", id="f-is-data-class")
                yield Checkbox("is_sealed", id="f-is-sealed")
                yield Checkbox("is_interface", id="f-is-interface")
                yield Checkbox("is_composable", id="f-is-composable")
                yield Checkbox("is_di_component", id="f-is-di-component")
            with Vertical(classes="filter-group"):
                yield Static("[bold]Strategy override[/bold]", classes="group-title")
                with RadioSet(id="f-strategy"):
                    yield RadioButton("auto (planner)", value=True, id="strat-auto")
                    yield RadioButton("hybrid", id="strat-hybrid")
                    yield RadioButton("filtered", id="strat-filtered")
                    yield RadioButton("graph_walk", id="strat-graph_walk")
                    yield RadioButton("aggregate", id="strat-aggregate")
                    yield RadioButton("global", id="strat-global")
                    yield RadioButton("naive", id="strat-naive")


# ---------- Logs ----------


class LogsScreen(ScreenBase):
    title = "Logs Tail"

    DEFAULT_CSS = """
    LogsScreen #logs-view {
        height: 1fr;
        border: round $primary 30%;
        margin: 0 1;
    }
    LogsScreen #logs-heatmap {
        height: 4;
        border: round $primary 30%;
        margin: 0 1;
        padding: 0 1;
        color: $text-muted;
    }
    """

    def compose_body(self) -> ComposeResult:
        yield RichLog(highlight=True, markup=True, id="logs-view", wrap=False, max_lines=2000)
        yield Static(
            "[bold]24h event volume (5-min bins)[/bold]\n"
            "[cyan]▁▁▂▂▃▃▄▄▅▅▆▆▇▇██▇▇▆▆▅▅▄▄▃▃▂▂▁▁▁▁▂▂▃▃▄▄▅▅▆▆▇▇██▇▇▆▆▅▅▄▄▃▃▂▂▁▁▁▁▂▂▃▃▄▄▅▅▆▆▇▇██▇▇▆▆▅▅[/cyan]\n"
            "[dim]00:00                                 12:00                                 23:59[/dim]",
            id="logs-heatmap",
        )


# ---------- Overview ----------


class OverviewScreen(ScreenBase):
    title = "Overview"

    DEFAULT_CSS = """
    OverviewScreen .overview-mid { height: 1fr; }
    OverviewScreen .panel {
        border: round $primary 30%;
        padding: 1 1;
        margin: 0 1;
        height: 1fr;
    }
    """

    def compose_body(self) -> ComposeResult:
        with Horizontal(classes="overview-mid"):
            with VerticalScroll(classes="panel"):
                yield Static("[bold]Module summaries[/bold]")
                yield Static("[dim]loading...[/dim]", id="ov-summaries")
            with VerticalScroll(classes="panel"):
                yield Static("[bold]Graph communities[/bold]")
                yield Static("[dim]loading...[/dim]", id="ov-communities")
                yield Static("")
                yield Static("[bold]Top connected nodes[/bold]")
                yield Static("[dim]loading...[/dim]", id="ov-nodes")


# ---------- Help ----------


class HelpScreen(ScreenBase):
    title = "Help"

    DEFAULT_CSS = """
    HelpScreen .help-grid { height: 1fr; }
    HelpScreen .panel {
        border: round $primary 30%;
        padding: 1 2;
        margin: 0 1;
        height: 1fr;
    }
    """

    def compose_body(self) -> ComposeResult:
        with Horizontal(classes="help-grid"):
            with VerticalScroll(classes="panel"):
                yield Static("[bold]Hotkeys[/bold]\n")
                yield Static(
                    "  [cyan]q[/cyan]           Quit\n"
                    "  [cyan]?[/cyan]           Toggle Help screen\n"
                    "  [cyan]ctrl+k[/cyan]      Command palette\n"
                    "  [cyan]:[/cyan]           Focus command line\n"
                    "  [cyan]h[/cyan]           Home\n"
                    "  [cyan]s[/cyan]           Search\n"
                    "  [cyan]a[/cyan]           Ask\n"
                    "  [cyan]i[/cyan]           Index\n"
                    "  [cyan]f[/cyan]           Filters\n"
                    "  [cyan]o[/cyan]           Overview\n"
                    "  [cyan]l[/cyan]           Logs\n"
                    "  [cyan]c[/cyan]           Clear active log / results\n"
                )
            with VerticalScroll(classes="panel"):
                yield Static("[bold]Active config[/bold]\n")
                yield Static("[dim]loading...[/dim]", id="help-config")
                yield Static("")
                yield Static("[bold]:cmd line examples[/bold]\n")
                yield Static(
                    "  [cyan]:search[/cyan] payment processing\n"
                    "  [cyan]:ask[/cyan] how does checkout work\n"
                    "  [cyan]:list[/cyan] is_singleton --lang kotlin\n"
                    "  [cyan]:index[/cyan] /path/to/repo\n"
                    "  [cyan]:filter[/cyan] lang=kotlin\n"
                    "  [cyan]:strategy[/cyan] hybrid\n"
                    "  [cyan]:goto[/cyan] logs\n"
                )


# ---------------------------------------------------------------------------
# Command palette modal (⌘K)
# ---------------------------------------------------------------------------


class CommandPalette(ModalScreen):
    """Fuzzy-search modal for any verb in the TUI.

    Returns the selected command string via ``self.dismiss(cmd)``.
    """

    BINDINGS = [Binding("escape", "dismiss", "Cancel")]

    DEFAULT_CSS = """
    CommandPalette {
        align: center middle;
    }
    CommandPalette > Container {
        background: $surface;
        border: thick $accent;
        padding: 1 2;
        width: 80;
        height: 24;
    }
    CommandPalette Input {
        width: 1fr;
        margin-bottom: 1;
    }
    CommandPalette ListView {
        height: 1fr;
    }
    CommandPalette .pal-group { color: $accent; }
    """

    COMMANDS = [
        ("ACTIONS", [
            ("search ...", "search"),
            ("ask ...", "ask"),
            ("list is_singleton", "list is_singleton"),
            ("list is_suspend", "list is_suspend"),
            ("list uses_coroutines", "list uses_coroutines"),
            ("index <path>", "index"),
            ("reload config", "reload"),
            ("clear log", "clear"),
        ]),
        ("NAVIGATE", [
            ("go to Home", "goto home"),
            ("go to Search", "goto search"),
            ("go to Ask", "goto ask"),
            ("go to Index", "goto index"),
            ("go to Filters", "goto filters"),
            ("go to Overview", "goto overview"),
            ("go to Logs", "goto logs"),
            ("go to Help", "goto help"),
        ]),
        ("DAEMON", [
            ("show /status", "status"),
            ("show /health detail", "health"),
            ("show recent events", "events"),
            ("show collections", "collections"),
            ("show plugins", "plugins"),
        ]),
    ]

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("[bold cyan]⌘ Command Palette[/bold cyan]  [dim]· type to filter, ↵ run, esc cancel[/dim]")
            yield Input(placeholder="Type a command…", id="pal-input")
            yield ListView(id="pal-list")

    async def on_mount(self) -> None:
        await self._populate("")

    async def _populate(self, q: str) -> None:
        lv = self.query_one("#pal-list", ListView)
        await lv.clear()
        q_low = q.strip().lower()
        for group_name, items in self.COMMANDS:
            await lv.append(ListItem(Static(f"[dim]{group_name}[/dim]")))
            for label, cmd in items:
                if q_low and q_low not in label.lower() and q_low not in cmd.lower():
                    continue
                item = ListItem(Static(f"  [bold]{label}[/bold]   [dim]→ {cmd}[/dim]"))
                item.command_value = cmd  # type: ignore[attr-defined]
                await lv.append(item)

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "pal-input":
            await self._populate(event.value)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        # Submit the first non-group item that matches
        lv = self.query_one("#pal-list", ListView)
        for item in lv.children:
            if isinstance(item, ListItem) and hasattr(item, "command_value"):
                self.dismiss(item.command_value)  # type: ignore[attr-defined]
                return
        self.dismiss(None)

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if hasattr(item, "command_value"):
            self.dismiss(item.command_value)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Dashboard frame — composes everything
# ---------------------------------------------------------------------------


class Dashboard(Container):
    """Outer frame: status bar (top), sidebar (left), cmd line (bottom),
    screen swap area (center)."""

    DEFAULT_CSS = """
    Dashboard {
        height: 1fr;
    }
    Dashboard #screen-area {
        height: 1fr;
        padding: 0 0;
    }
    """

    SCREENS = {
        "home": HomeScreen,
        "search": SearchScreen,
        "ask": AskScreen,
        "index": IndexScreen,
        "filters": FiltersScreen,
        "overview": OverviewScreen,
        "logs": LogsScreen,
        "help": HelpScreen,
    }

    def __init__(self, host: str, port: int, **kwargs):
        super().__init__(**kwargs)
        self._host = host
        self._port = port
        self._active = "home"

    def compose(self) -> ComposeResult:
        yield StatusBar(id="status-bar")
        yield Sidebar(id="sidebar")
        yield CmdLine(id="cmd-line")
        with Container(id="screen-area"):
            yield HomeScreen(id="screen-home")

    async def switch_screen(self, name: str) -> None:
        """Replace the screen-area contents with a new screen widget."""
        if name not in self.SCREENS:
            return
        if name == self._active:
            return
        self._active = name
        area = self.query_one("#screen-area", Container)
        for child in list(area.children):
            await child.remove()
        cls = self.SCREENS[name]
        new = cls(id=f"screen-{name}")
        await area.mount(new)
        try:
            self.query_one("#sidebar", Sidebar).active = name
            self.query_one("#status-bar", StatusBar).screen_name = cls.title
        except Exception:
            pass
