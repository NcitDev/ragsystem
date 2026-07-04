"""RAG System TUI — dashboard widgets and screens.

Everything renders from a :class:`rag.tui.monitor.StackSnapshot`; widgets do no
I/O themselves. The Home screen is a stack-health dashboard (daemon, Ollama,
Docker, Qdrant, project indexes) that stays informative when services are
down — each card then shows what is wrong and the key/command that fixes it.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Input,
    ListItem,
    ListView,
    ProgressBar,
    RichLog,
    Static,
)

from rag.tui.monitor import DOWN, OFF, OK, WARN, StackSnapshot, humanize_ago

# Palette (single dark theme, matches the web dashboard)
C_BG = "#0a0e14"
C_PANEL = "#10161d"
C_BORDER = "#1a1f2a"
C_TEXT = "#c8d6e5"
C_DIM = "#5a6a7a"
C_ACCENT = "#5ee6d0"
C_VIOLET = "#b084eb"
C_BLUE = "#7fb6f0"
C_GREEN = "#7fd18b"
C_YELLOW = "#e0b466"
C_RED = "#e5687a"

STATE_DOT = {
    OK: f"[{C_GREEN}]●[/]",
    WARN: f"[{C_YELLOW}]●[/]",
    DOWN: f"[{C_RED}]●[/]",
    OFF: f"[{C_DIM}]○[/]",
}


def state_dot(state: str) -> str:
    return STATE_DOT.get(state, STATE_DOT[OFF])


# ---------------------------------------------------------------------------
# Chrome: header, sidebar, footer
# ---------------------------------------------------------------------------


class HeaderBar(Static):
    """Top bar: title, per-service dots, active screen, clock."""

    DEFAULT_CSS = f"""
    HeaderBar {{
        dock: top;
        height: 1;
        padding: 0 1;
        background: #12161e;
        color: {C_DIM};
    }}
    """

    screen_name = reactive("Dashboard")
    daemon_state = reactive(OFF)
    ollama_state = reactive(OFF)
    docker_state = reactive(OFF)
    qdrant_state = reactive(OFF)

    def on_mount(self) -> None:
        self.set_interval(30.0, self.refresh)

    def render(self) -> str:
        clock = datetime.now().strftime("%H:%M")
        return (
            f"[{C_ACCENT} b]RAG[/] [b]SYSTEM[/]"
            f"  [{C_DIM}]·[/]  [{C_TEXT}]{self.screen_name}[/]"
            f"   {state_dot(self.daemon_state)} daemon"
            f"  {state_dot(self.ollama_state)} ollama"
            f"  {state_dot(self.docker_state)} docker"
            f"  {state_dot(self.qdrant_state)} qdrant"
            f"   [{C_DIM}]{clock}[/]"
        )

    def update_snapshot(self, snap: StackSnapshot) -> None:
        self.daemon_state = snap.daemon.state
        self.ollama_state = snap.ollama.state
        self.docker_state = snap.docker.state
        self.qdrant_state = snap.qdrant.state


class NavSidebar(Static):
    """Left navigation. Highlights the active screen."""

    DEFAULT_CSS = f"""
    NavSidebar {{
        width: 20;
        height: 100%;
        background: {C_PANEL};
        border-right: solid {C_BORDER};
        padding: 1 0;
    }}
    """

    NAV = [
        ("home", "Dashboard", "h"),
        ("search", "Search", "s"),
        ("ask", "Ask", "a"),
        ("index", "Index", "i"),
        ("logs", "Logs", "l"),
        ("help", "Help", "?"),
    ]

    active = reactive("home")

    def render(self) -> str:
        lines = [f"  [{C_DIM} b]SCREENS[/]", ""]
        for key, label, hot in self.NAV:
            if key == self.active:
                lines.append(f" [{C_ACCENT} on #141b23]▌ {label:<11}[/][{C_DIM}]{hot}[/]")
            else:
                lines.append(f"   [{C_TEXT}]{label:<11}[/][{C_DIM}]{hot}[/]")
        lines += [
            "",
            f"  [{C_DIM} b]ACTIONS[/]",
            "",
            f"   [{C_TEXT}]Start daemon[/] [{C_DIM}]D[/]",
            f"   [{C_TEXT}]Start qdrant[/] [{C_DIM}]U[/]",
            f"   [{C_TEXT}]Web dash    [/] [{C_DIM}]W[/]",
            f"   [{C_TEXT}]Refresh     [/] [{C_DIM}]r[/]",
            f"   [{C_TEXT}]Quit        [/] [{C_DIM}]q[/]",
        ]
        return "\n".join(lines)


class FooterBar(Static):
    """One-line footer with the essential keys."""

    DEFAULT_CSS = f"""
    FooterBar {{
        dock: bottom;
        height: 1;
        padding: 0 1;
        background: #12161e;
        color: {C_DIM};
    }}
    """

    def render(self) -> str:
        return (
            f" [{C_ACCENT}]h[/] dashboard  [{C_ACCENT}]s[/] search  [{C_ACCENT}]a[/] ask"
            f"  [{C_ACCENT}]i[/] index  [{C_ACCENT}]l[/] logs  [{C_ACCENT}]?[/] help"
            f"  [{C_DIM}]│[/]  [{C_ACCENT}]D[/] start daemon  [{C_ACCENT}]U[/] start qdrant"
            f"  [{C_ACCENT}]W[/] web  [{C_ACCENT}]r[/] refresh  [{C_ACCENT}]q[/] quit"
        )


# ---------------------------------------------------------------------------
# Home / Dashboard
# ---------------------------------------------------------------------------


class ServiceCard(Static):
    """One service health card: dot + name + headline, detail lines, fix hint."""

    DEFAULT_CSS = f"""
    ServiceCard {{
        border: round {C_BORDER};
        background: {C_PANEL};
        width: 1fr;
        height: 100%;
        padding: 0 1;
        margin: 0 1 0 0;
    }}
    """

    def __init__(self, title: str, **kwargs):
        super().__init__(**kwargs)
        self._title = title
        self._body = f"[{C_DIM}]checking…[/]"

    def render(self) -> str:
        return f"[{C_DIM} b]{self._title}[/]\n{self._body}"

    def show(self, svc) -> None:
        color = {OK: C_GREEN, WARN: C_YELLOW, DOWN: C_RED}.get(svc.state, C_DIM)
        lines = [f"{state_dot(svc.state)} [{color}]{svc.headline or svc.state}[/]"]
        lines += [f"[{C_TEXT}]{ln}[/]" for ln in svc.lines[:4]]
        if svc.hint and svc.state != OK:
            lines.append(f"[{C_YELLOW}]→ {svc.hint}[/]")
        self._body = "\n".join(lines)
        self.refresh()


class HomeScreen(Container):
    """Stack dashboard: service cards, project indexes, activity, LSP."""

    name_title = "Dashboard"

    DEFAULT_CSS = f"""
    HomeScreen {{
        padding: 1 1 0 1;
    }}
    HomeScreen #home-cards {{
        height: 9;
        margin-bottom: 1;
    }}
    HomeScreen #repos-panel {{
        height: 1fr;
        border: round {C_BORDER};
        background: {C_PANEL};
        margin: 0 1 1 0;
    }}
    HomeScreen #repos-title {{
        height: 1;
        padding: 0 1;
        background: #12161e;
        color: {C_DIM};
    }}
    HomeScreen #repos-table {{
        height: 1fr;
        background: {C_PANEL};
    }}
    HomeScreen #home-bottom {{
        height: 9;
    }}
    HomeScreen .bottom-panel {{
        border: round {C_BORDER};
        background: {C_PANEL};
        height: 100%;
        margin: 0 1 0 0;
        padding: 0 1;
    }}
    HomeScreen #activity-panel {{ width: 3fr; }}
    HomeScreen #lsp-panel {{ width: 2fr; }}
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="home-cards"):
            yield ServiceCard("DAEMON", id="card-daemon")
            yield ServiceCard("OLLAMA", id="card-ollama")
            yield ServiceCard("DOCKER", id="card-docker")
            yield ServiceCard("QDRANT", id="card-qdrant")
        with Vertical(id="repos-panel"):
            yield Static(f"[{C_DIM} b]PROJECT INDEXES[/]", id="repos-title")
            yield DataTable(id="repos-table")
        with Horizontal(id="home-bottom"):
            yield Static(f"[{C_DIM} b]ACTIVITY[/]\n[{C_DIM}]waiting for daemon…[/]",
                         id="activity-panel", classes="bottom-panel")
            yield Static(f"[{C_DIM} b]LSP / SERVICE[/]\n[{C_DIM}]checking…[/]",
                         id="lsp-panel", classes="bottom-panel")

    def on_mount(self) -> None:
        table = self.query_one("#repos-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.add_columns("", "PROJECT", "PATH", "CHUNKS", "FILES", "LAST INDEXED", "COLLECTION")

    # -- render helpers -----------------------------------------------------

    def update_snapshot(self, snap: StackSnapshot) -> None:
        self.query_one("#card-daemon", ServiceCard).show(snap.daemon)
        self.query_one("#card-ollama", ServiceCard).show(snap.ollama)
        self.query_one("#card-docker", ServiceCard).show(snap.docker)
        self.query_one("#card-qdrant", ServiceCard).show(snap.qdrant)
        self._update_repos(snap)
        self._update_activity(snap)
        self._update_lsp(snap)

    def update_fast(self, snap: StackSnapshot) -> None:
        """High-frequency subset: daemon card + activity only."""
        self.query_one("#card-daemon", ServiceCard).show(snap.daemon)
        self._update_activity(snap)

    def _update_repos(self, snap: StackSnapshot) -> None:
        title = self.query_one("#repos-title", Static)
        src = "live from daemon" if snap.repos_source == "daemon" else "local registry (daemon down)"
        title.update(f"[{C_DIM} b]PROJECT INDEXES[/]  [{C_DIM}]· {src}[/]")

        table = self.query_one("#repos-table", DataTable)
        table.clear()
        if not snap.repos:
            table.add_row("", Text("no indexes yet — run: rag index /path/to/repo", style=C_DIM),
                          "", "", "", "", "")
            return
        # Projects first, default collections after.
        ordered = [r for r in snap.repos if r.kind == "repo"] + [
            r for r in snap.repos if r.kind != "repo"
        ]
        for r in ordered:
            missing = r.status == "not_found"
            dot = Text("●", style=C_RED if missing else (C_GREEN if r.points else C_DIM))
            name_style = C_BLUE if r.kind == "repo" else C_DIM
            path = r.path.replace(str(Path.home()), "~") if r.path else "—"
            table.add_row(
                dot,
                Text(r.name, style=f"bold {name_style}"),
                Text(path, style=C_DIM),
                Text(f"{r.points:,}" if r.points else ("missing" if missing else "0"),
                     style=C_TEXT if r.points else C_DIM, justify="right"),
                Text(f"{r.files:,}" if r.files else "—", style=C_DIM, justify="right"),
                Text(r.last_indexed or "—", style=C_DIM),
                Text(r.collection, style=C_DIM),
            )

    def _update_activity(self, snap: StackSnapshot) -> None:
        panel = self.query_one("#activity-panel", Static)
        if not snap.daemon_up:
            panel.update(
                f"[{C_DIM} b]ACTIVITY[/]\n"
                f"[{C_DIM}]daemon down — no query telemetry[/]\n"
                f"[{C_YELLOW}]→ press D to start the daemon[/]"
            )
            return
        stats = snap.stats
        head = (
            f"[{C_DIM} b]ACTIVITY[/]  "
            f"[{C_TEXT}]{stats.get('count', 0)} recent[/] [{C_DIM}]·[/] "
            f"[{C_TEXT}]qpm {stats.get('qpm', 0):.0f}[/] [{C_DIM}]·[/] "
            f"[{C_TEXT}]p50 {stats.get('p50_ms', 0):.0f}ms[/] [{C_DIM}]·[/] "
            f"[{C_TEXT}]p95 {stats.get('p95_ms', 0):.0f}ms[/]"
        )
        lines = [head]
        # Running index jobs get top billing.
        for job_id, job in list(snap.jobs.items())[-2:]:
            status = job.get("status", "?")
            if status in ("running", "pending"):
                done = job.get("files_processed", 0)
                total = job.get("total_files", 0)
                lines.append(
                    f"[{C_VIOLET}]⚙ index {job_id[:8]}[/] [{C_TEXT}]{status} "
                    f"{done}/{total} files[/]"
                )
        for q in snap.queries[:5]:
            ts = humanize_ago(q.get("timestamp")) or ""
            text = str(q.get("query", ""))[:46]
            n = q.get("results_count")
            lat = q.get("latency_ms")
            meta = []
            if n is not None:
                meta.append(f"{n} hits")
            if lat:
                meta.append(f"{float(lat):.0f}ms")
            lines.append(
                f"[{C_DIM}]{ts:>9}[/]  [{C_TEXT}]{text:<46}[/] [{C_DIM}]{' · '.join(meta)}[/]"
            )
        if len(lines) == 1:
            lines.append(f"[{C_DIM}]no queries yet — try the Search screen (s)[/]")
        panel.update("\n".join(lines))

    def _update_lsp(self, snap: StackSnapshot) -> None:
        panel = self.query_one("#lsp-panel", Static)
        lines = [f"[{C_DIM} b]LSP / SERVICE[/]"]
        if snap.lsp:
            found = [s for s in snap.lsp if s.found]
            missing = [s for s in snap.lsp if not s.found]
            langs = " ".join(f"[{C_GREEN}]{s.language}[/]" for s in found)
            lines.append(f"[{C_TEXT}]{len(found)} LSP found:[/] {langs}")
            if missing:
                miss = " ".join(s.language for s in missing)
                lines.append(f"[{C_DIM}]missing: {miss}[/]")
        else:
            lines.append(f"[{C_DIM}]no LSP servers detected[/]")
        if snap.service:
            inst = snap.service.get("installed")
            loaded = snap.service.get("loaded")
            if inst:
                state = f"[{C_GREEN}]loaded[/]" if loaded else f"[{C_YELLOW}]installed, not loaded[/]"
            else:
                state = f"[{C_DIM}]not installed — rag service install[/]"
            lines.append(f"[{C_TEXT}]launchd:[/] {state}")
        panel.update("\n".join(lines))


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class SearchScreen(Container):
    name_title = "Search"

    DEFAULT_CSS = f"""
    SearchScreen {{ padding: 1 1 0 1; }}
    SearchScreen #search-form {{ height: 3; margin: 0 1 1 0; }}
    SearchScreen #search-input {{ width: 1fr; margin-right: 1; }}
    SearchScreen #search-repo {{ width: 26; }}
    SearchScreen #search-mid {{ height: 1fr; }}
    SearchScreen #search-results {{
        width: 2fr;
        border: round {C_BORDER};
        background: {C_PANEL};
        margin: 0 1 0 0;
    }}
    SearchScreen #search-detail {{
        width: 3fr;
        border: round {C_BORDER};
        background: #060a10;
        margin: 0 1 0 0;
        padding: 0 1;
    }}
    SearchScreen #search-plan {{
        height: 3;
        color: {C_DIM};
        padding: 0 1;
    }}
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="search-form"):
            yield Input(placeholder="search the index — Enter to run", id="search-input")
            yield Input(placeholder="repo (optional)", id="search-repo")
        with Horizontal(id="search-mid"):
            yield ListView(id="search-results")
            yield RichLog(highlight=True, markup=True, id="search-detail", wrap=False)
        yield Static(f"[{C_DIM}]plan appears here after the first query[/]", id="search-plan")


# ---------------------------------------------------------------------------
# Ask
# ---------------------------------------------------------------------------


class AskScreen(Container):
    name_title = "Ask"

    DEFAULT_CSS = f"""
    AskScreen {{ padding: 1 1 0 1; }}
    AskScreen #ask-form {{ height: 3; margin: 0 1 1 0; }}
    AskScreen #ask-input {{ width: 1fr; margin-right: 1; }}
    AskScreen #ask-repo {{ width: 26; }}
    AskScreen #ask-mid {{ height: 1fr; }}
    AskScreen #ask-answer {{
        width: 3fr;
        border: round {C_BORDER};
        background: {C_PANEL};
        margin: 0 1 0 0;
        padding: 0 1;
    }}
    AskScreen #ask-citations {{
        width: 2fr;
        border: round {C_BORDER};
        background: {C_PANEL};
        margin: 0 1 0 0;
    }}
    AskScreen #ask-meta {{ height: 1; padding: 0 1; color: {C_DIM}; }}
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="ask-form"):
            yield Input(placeholder="ask a grounded question about the indexed code — Enter to run",
                        id="ask-input")
            yield Input(placeholder="repo (optional)", id="ask-repo")
        with Horizontal(id="ask-mid"):
            yield RichLog(highlight=True, markup=True, id="ask-answer", wrap=True)
            yield ListView(id="ask-citations")
        yield Static("", id="ask-meta")


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------


class IndexScreen(Container):
    name_title = "Index"

    DEFAULT_CSS = f"""
    IndexScreen {{ padding: 1 1 0 1; }}
    IndexScreen #index-form {{ height: 3; }}
    IndexScreen #index-path {{ width: 3fr; margin-right: 1; }}
    IndexScreen #index-full {{ width: 14; }}
    IndexScreen #index-go {{ width: 12; }}
    IndexScreen #index-status {{
        height: 3;
        border: round {C_BORDER};
        background: {C_PANEL};
        padding: 0 1;
        margin: 1 1 0 0;
    }}
    IndexScreen #index-progress {{ margin: 1 2; height: 1; }}
    IndexScreen #index-jobs {{
        height: 1fr;
        border: round {C_BORDER};
        background: {C_PANEL};
        margin: 0 1 0 0;
        padding: 0 1;
    }}
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="index-form"):
            yield Input(placeholder="/absolute/path/to/repo   (Enter or button to index)",
                        id="index-path")
            yield Checkbox("full", id="index-full")
            yield Button("Index", id="index-go", variant="primary")
        yield Static(f"[{C_DIM}]idle — daemon runs the job, progress shows here[/]",
                     id="index-status")
        yield ProgressBar(total=100, show_eta=False, id="index-progress")
        yield RichLog(markup=True, id="index-jobs", wrap=False, max_lines=500)

    def update_jobs(self, jobs: dict) -> None:
        log = self.query_one("#index-jobs", RichLog)
        log.clear()
        if not jobs:
            log.write(f"[{C_DIM}]no index jobs this daemon session[/]")
            return
        log.write(f"[{C_DIM} b]JOBS[/]")
        for job_id, job in list(jobs.items())[-20:]:
            status = job.get("status", "?")
            color = {"completed": C_GREEN, "failed": C_RED, "running": C_VIOLET}.get(status, C_DIM)
            log.write(
                f"[{C_DIM}]{job_id[:8]}[/] [{color}]{status:<10}[/] "
                f"[{C_TEXT}]{job.get('files_processed', 0)}/{job.get('total_files', 0)} files · "
                f"{job.get('chunks_indexed', 0)} chunks[/] "
                f"[{C_DIM}]{job.get('repo_path', '')}[/]"
            )


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------


class LogsScreen(Container):
    name_title = "Logs"

    DEFAULT_CSS = f"""
    LogsScreen {{ padding: 1 1 0 1; }}
    LogsScreen #logs-view {{
        height: 1fr;
        border: round {C_BORDER};
        background: #060a10;
        margin: 0 1 0 0;
        padding: 0 1;
    }}
    """

    def compose(self) -> ComposeResult:
        yield RichLog(highlight=True, markup=True, id="logs-view", wrap=False, max_lines=2000)

    def append_events(self, events: list[dict]) -> None:
        view = self.query_one("#logs-view", RichLog)
        for ev in events:
            ts = datetime.fromtimestamp(float(ev.get("ts", 0.0))).strftime("%H:%M:%S")
            name = ev.get("event", "?")
            payload = {k: v for k, v in ev.items() if k not in ("ts", "event")}
            view.write(f"[{C_DIM}]{ts}[/] [{C_ACCENT} b]{name}[/] [{C_TEXT}]{payload}[/]")


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------


class HelpScreen(Container):
    name_title = "Help"

    DEFAULT_CSS = f"""
    HelpScreen {{ padding: 1 1 0 1; }}
    HelpScreen .panel {{
        border: round {C_BORDER};
        background: {C_PANEL};
        padding: 1 2;
        margin: 0 1 0 0;
        height: 1fr;
    }}
    """

    def compose(self) -> ComposeResult:
        with Horizontal():
            with VerticalScroll(classes="panel"):
                yield Static(
                    f"[b]Keys[/b]\n\n"
                    f"  [{C_ACCENT}]h[/]  Dashboard — stack health + project indexes\n"
                    f"  [{C_ACCENT}]s[/]  Search the index\n"
                    f"  [{C_ACCENT}]a[/]  Ask (grounded RAG answer)\n"
                    f"  [{C_ACCENT}]i[/]  Index a repository\n"
                    f"  [{C_ACCENT}]l[/]  Daemon event log\n"
                    f"  [{C_ACCENT}]?[/]  This help\n\n"
                    f"  [{C_ACCENT}]D[/]  Start the daemon (background)\n"
                    f"  [{C_ACCENT}]U[/]  Start the Qdrant docker container\n"
                    f"  [{C_ACCENT}]W[/]  Open the web dashboard\n"
                    f"  [{C_ACCENT}]r[/]  Refresh all checks now\n"
                    f"  [{C_ACCENT}]q[/]  Quit  ·  [{C_ACCENT}]esc[/] leave an input field\n"
                )
            with VerticalScroll(classes="panel"):
                yield Static("[b]Active config[/b]\n")
                yield Static(f"[{C_DIM}]loading…[/]", id="help-config")
                yield Static(
                    f"\n[b]CLI equivalents[/b]\n\n"
                    f"  [{C_ACCENT}]rag start[/]        run the daemon\n"
                    f"  [{C_ACCENT}]rag qdrant-up[/]    start Qdrant (docker compose)\n"
                    f"  [{C_ACCENT}]rag index PATH[/]   index a repository\n"
                    f"  [{C_ACCENT}]rag search "
                    f'"q"[/]   search from the shell\n'
                    f"  [{C_ACCENT}]rag diagnose[/]     full health check\n"
                    f"  [{C_ACCENT}]rag web[/]          browser dashboard\n"
                )

    def show_config(self, settings) -> None:
        gen = settings.llm.gen_model or settings.llm.agent_model
        self.query_one("#help-config", Static).update(
            f"  [{C_ACCENT}]embedder[/] {settings.embeddings.model}\n"
            f"  [{C_ACCENT}]agent   [/] {settings.llm.agent_model}\n"
            f"  [{C_ACCENT}]gen     [/] {gen}\n"
            f"  [{C_ACCENT}]planner [/] {settings.retrieval_agent.provider} "
            f"({settings.retrieval_agent.model})\n"
            f"  [{C_ACCENT}]ollama  [/] {settings.llm.ollama_url}\n"
            f"  [{C_ACCENT}]qdrant  [/] {settings.qdrant.mode} · {settings.qdrant.url}\n"
            f"  [{C_ACCENT}]daemon  [/] {settings.server.host}:{settings.server.port}\n"
        )


SCREENS = {
    "home": HomeScreen,
    "search": SearchScreen,
    "ask": AskScreen,
    "index": IndexScreen,
    "logs": LogsScreen,
    "help": HelpScreen,
}


def make_result_item(i: int, r: dict) -> ListItem:
    """List row for one /search result."""
    return ListItem(
        Static(
            f"{i:2d}. [{C_BLUE}]{r.get('language', '?')}[/] "
            f"[{C_TEXT}]{r.get('file_path', '?')}:{r.get('lines', '?')}[/]\n"
            f"     [{C_DIM}]{r.get('name', '')}  score={r.get('score', 0)}[/]"
        )
    )
