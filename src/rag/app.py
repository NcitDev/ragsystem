"""Textual TUI — stack dashboard + interactive client for the RAG daemon.

Unlike the daemon-only predecessor, this app monitors the whole stack
directly (daemon over HTTP; Ollama, Docker and Qdrant probed like
``rag diagnose`` does), so it stays useful — and tells you how to fix
things — when parts of the stack are down. It can also start the daemon
and the Qdrant container itself (D / U keys).

All rendering happens from :class:`StackSnapshot`; polling runs on two
cadences (fast: daemon + activity, slow: external probes).
"""

from __future__ import annotations

import asyncio
import webbrowser

import structlog
from rich.syntax import Syntax
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Button, ContentSwitcher, Input, ListView, ProgressBar, RichLog, Static

from rag.config import ensure_rag_home, get_settings
from rag.tui.dashboard import (
    SCREENS,
    FooterBar,
    HeaderBar,
    HelpScreen,
    HomeScreen,
    IndexScreen,
    LogsScreen,
    NavSidebar,
    make_result_item,
)
from rag.tui.monitor import StackMonitor, StackSnapshot

logger = structlog.get_logger()

_DEFAULT_TOP_K = 8
FAST_POLL_S = 2.5
SLOW_POLL_S = 12.0


class RAGApp(App):
    """RAG System TUI — stack dashboard for the daemon and its dependencies."""

    TITLE = "RAG System"
    SUB_TITLE = "Code Search Engine"

    CSS = """
    Screen {
        background: #0a0e14;
        color: #c8d6e5;
    }
    Input {
        background: #10161d;
        border: tall #1a1f2a;
    }
    Input:focus {
        background: #141b23;
        border: tall #5ee6d0;
    }
    ListView {
        background: #10161d;
    }
    ListView > ListItem {
        background: transparent;
        padding: 0 1;
    }
    ListView > ListItem.--highlight {
        background: #1a2330;
    }
    ProgressBar > Bar {
        color: #5ee6d0;
    }
    DataTable {
        background: #10161d;
    }
    DataTable > .datatable--header {
        background: #12161e;
        color: #5a6a7a;
    }
    DataTable > .datatable--cursor {
        background: #1a2330;
    }
    #body {
        height: 1fr;
    }
    #content {
        height: 1fr;
        width: 1fr;
    }
    """

    BINDINGS = [
        Binding("h", "goto('home')", "Dashboard"),
        Binding("s", "goto('search')", "Search"),
        Binding("a", "goto('ask')", "Ask"),
        Binding("i", "goto('index')", "Index"),
        Binding("l", "goto('logs')", "Logs"),
        Binding("question_mark", "goto('help')", "Help", show=False),
        Binding("r", "refresh_now", "Refresh"),
        Binding("D", "start_daemon", "Start daemon"),
        Binding("U", "start_qdrant", "Start qdrant"),
        Binding("W", "open_web", "Web dashboard", show=False),
        Binding("escape", "blur_input", "Unfocus", show=False),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, initial_screen: str = "home"):
        super().__init__()
        self._initial = initial_screen if initial_screen in SCREENS else "home"
        self.monitor: StackMonitor | None = None
        self._seen_event_ts = 0.0
        self._last_results: list[dict] = []
        self._job_task: asyncio.Task | None = None
        self._repo_prefilled = False

    # ------------------------------------------------------------------
    # Compose / lifecycle
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield HeaderBar(id="header")
        yield FooterBar(id="footer")
        with Horizontal(id="body"):
            yield NavSidebar(id="nav")
            with ContentSwitcher(initial=f"screen-{self._initial}", id="content"):
                for key, cls in SCREENS.items():
                    yield cls(id=f"screen-{key}")

    async def on_mount(self) -> None:
        ensure_rag_home()
        self.monitor = StackMonitor()
        try:
            self.query_one("#screen-help", HelpScreen).show_config(get_settings())
        except Exception as e:
            logger.debug("tui_help_config_error", error=str(e))
        self._sync_chrome(self._initial)
        # One full pass immediately, then steady-state cadences.
        self.run_worker(self._poll(full=True), group="poll-slow", exclusive=True)
        self.set_interval(FAST_POLL_S, self._poll_fast)
        self.set_interval(SLOW_POLL_S, self._poll_slow)

    async def on_unmount(self) -> None:
        if self.monitor:
            await self.monitor.close()

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    def _poll_fast(self) -> None:
        self.run_worker(self._poll(full=False), group="poll-fast", exclusive=True)

    def _poll_slow(self) -> None:
        self.run_worker(self._poll(full=True), group="poll-slow", exclusive=True)

    async def _poll(self, *, full: bool) -> None:
        if not self.monitor:
            return
        snap = await self.monitor.snapshot(fast_only=not full)
        self._apply_snapshot(snap, full=full)

    def _apply_snapshot(self, snap: StackSnapshot, *, full: bool) -> None:
        try:
            header = self.query_one("#header", HeaderBar)
            if full:
                header.update_snapshot(snap)
            else:
                header.daemon_state = snap.daemon.state
            home = self.query_one("#screen-home", HomeScreen)
            if full:
                home.update_snapshot(snap)
            else:
                home.update_fast(snap)
            # Logs: append only unseen events.
            fresh = [e for e in snap.events if float(e.get("ts", 0.0)) > self._seen_event_ts]
            if fresh:
                self._seen_event_ts = max(float(e.get("ts", 0.0)) for e in fresh)
                self.query_one("#screen-logs", LogsScreen).append_events(fresh)
            self.query_one("#screen-index", IndexScreen).update_jobs(snap.jobs)
            self._prefill_repo(snap)
        except Exception as e:
            logger.debug("tui_apply_snapshot_error", error=str(e))

    def _prefill_repo(self, snap: StackSnapshot) -> None:
        """Once: default the Search/Ask repo boxes to the first project when
        the default code collection is empty or missing (searching it would
        500), so Enter-to-search works out of the box."""
        if self._repo_prefilled:
            return
        default_has_data = any(
            r.kind != "repo" and r.points > 0 for r in snap.repos
        )
        projects = [r for r in snap.repos if r.kind == "repo" and r.points > 0]
        if default_has_data or not projects:
            return
        self._repo_prefilled = True
        for wid in ("#search-repo", "#ask-repo"):
            try:
                box = self.query_one(wid, Input)
                if not box.value:
                    box.value = projects[0].name
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Navigation / actions
    # ------------------------------------------------------------------

    def _sync_chrome(self, name: str) -> None:
        cls = SCREENS[name]
        try:
            self.query_one("#nav", NavSidebar).active = name
            self.query_one("#header", HeaderBar).screen_name = cls.name_title
        except Exception:
            pass

    def action_goto(self, name: str) -> None:
        if name not in SCREENS:
            return
        self.query_one("#content", ContentSwitcher).current = f"screen-{name}"
        self._sync_chrome(name)
        # Land focus in the natural input of interactive screens.
        focus_id = {"search": "#search-input", "ask": "#ask-input", "index": "#index-path"}.get(name)
        if focus_id:
            try:
                self.query_one(focus_id, Input).focus()
            except Exception:
                pass

    def action_blur_input(self) -> None:
        self.set_focus(None)

    def action_refresh_now(self) -> None:
        self.run_worker(self._poll(full=True), group="poll-slow", exclusive=True)
        self.notify("refreshing all checks…", timeout=2)

    def action_start_daemon(self) -> None:
        if not self.monitor:
            return
        self.notify(self.monitor.spawn_daemon(), timeout=6)

    def action_start_qdrant(self) -> None:
        async def _run() -> None:
            msg = await self.monitor.start_qdrant() if self.monitor else "monitor not ready"
            self.notify(msg, timeout=8)
            await asyncio.sleep(2.0)
            await self._poll(full=True)

        self.run_worker(_run(), group="action-qdrant", exclusive=True)

    def action_open_web(self) -> None:
        if not self.monitor:
            return
        url = self.monitor.base_url + "/"
        webbrowser.open(url)
        self.notify(f"opened {url}", timeout=4)

    async def action_quit(self) -> None:
        self.exit()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def _run_search(self, query: str) -> None:
        if not query.strip() or not self.monitor:
            return
        plan_w = self.query_one("#search-plan", Static)
        plan_w.update("[#5a6a7a]searching…[/]")
        payload: dict = {"query": query, "top_k": _DEFAULT_TOP_K}
        repo = self.query_one("#search-repo", Input).value.strip()
        if repo:
            payload["repo"] = repo
        ok, data = await self.monitor.daemon_post("/search", payload, timeout=120.0)
        if not ok:
            plan_w.update(f"[#e5687a]search failed: {data}[/]")
            return
        plan = data.get("plan") or {}
        plan_w.update(
            f"[b]strategy[/b] {plan.get('strategy', '?')}  "
            f"[b]queries[/b] {plan.get('queries', [])}  "
            f"[#5a6a7a]{data.get('total', 0)} hits · {data.get('latency_ms', 0):.0f}ms[/]"
        )
        results = data.get("results", []) or []
        self._last_results = results
        lv = self.query_one("#search-results", ListView)
        await lv.clear()
        for i, r in enumerate(results, 1):
            await lv.append(make_result_item(i, r))
        if results:
            self._show_result_detail(0)
        else:
            self.query_one("#search-detail", RichLog).clear()

    def _show_result_detail(self, idx: int) -> None:
        if not (0 <= idx < len(self._last_results)):
            return
        r = self._last_results[idx]
        detail = self.query_one("#search-detail", RichLog)
        detail.clear()
        detail.write(
            f"[bold #5ee6d0]{r.get('file_path', '?')}:{r.get('lines', '?')}[/]\n"
            f"[#5a6a7a]{r.get('chunk_type', '?')}  {r.get('name', '')}  "
            f"score={r.get('score', 0)}[/]\n"
        )
        code = r.get("code", "") or ""
        lang = r.get("language", "") or "text"
        try:
            detail.write(Syntax(code, lang, theme="monokai", line_numbers=False, word_wrap=False))
        except Exception:
            detail.write(code)

    # ------------------------------------------------------------------
    # Ask
    # ------------------------------------------------------------------

    async def _run_ask(self, question: str) -> None:
        if not question.strip() or not self.monitor:
            return
        ans = self.query_one("#ask-answer", RichLog)
        ans.clear()
        ans.write("[#5a6a7a]asking… (retrieval + generation can take a while)[/]")
        payload: dict = {"question": question, "top_k": _DEFAULT_TOP_K}
        repo = self.query_one("#ask-repo", Input).value.strip()
        if repo:
            payload["repo"] = repo
        ok, data = await self.monitor.daemon_post("/ask", payload, timeout=300.0)
        ans.clear()
        if not ok:
            ans.write(f"[#e5687a]ask failed: {data}[/]")
            return
        if data.get("insufficient_context"):
            ans.write("[#e0b466]insufficient context — index more code or rephrase[/]\n")
        ans.write(data.get("answer", ""))
        lv = self.query_one("#ask-citations", ListView)
        await lv.clear()
        for i, c in enumerate(data.get("citations", []) or [], 1):
            await lv.append(make_result_item(i, c))
        self.query_one("#ask-meta", Static).update(
            f"[#5a6a7a]model {data.get('model', '?')} · "
            f"retrieval {data.get('retrieval_ms', 0):.0f}ms · "
            f"generation {data.get('generation_ms', 0):.0f}ms · "
            f"total {data.get('latency_ms', 0):.0f}ms[/]"
        )

    # ------------------------------------------------------------------
    # Index
    # ------------------------------------------------------------------

    async def _start_index_job(self) -> None:
        if not self.monitor:
            return
        path = self.query_one("#index-path", Input).value.strip()
        if not path:
            self.notify("enter a repository path first", severity="warning")
            return
        full = self.query_one("#index-full").value
        status = self.query_one("#index-status", Static)
        status.update(f"[#5a6a7a]starting index job for {path}…[/]")
        ok, data = await self.monitor.daemon_post(
            "/index/start", {"repo_path": path, "full": bool(full)}, timeout=30.0
        )
        if not ok:
            status.update(f"[#e5687a]failed: {data}[/]")
            return
        job_id = data.get("job_id", "")
        if self._job_task and not self._job_task.done():
            self._job_task.cancel()
        self._job_task = asyncio.create_task(self._watch_index_job(job_id))

    async def _watch_index_job(self, job_id: str) -> None:
        status = self.query_one("#index-status", Static)
        bar = self.query_one("#index-progress", ProgressBar)
        while True:
            data = await self.monitor.daemon_get(f"/index/progress/{job_id}") if self.monitor else None
            if data:
                state = data.get("status", "?")
                total = int(data.get("total_files", 0) or 0)
                done = int(data.get("files_processed", 0) or 0)
                chunks = int(data.get("chunks_indexed", 0) or 0)
                cur = data.get("current_file", "")
                if total:
                    bar.update(total=total, progress=done)
                status.update(
                    f"[b]{state}[/b]  files {done}/{total} · chunks {chunks:,}  "
                    f"[#5ee6d0]{cur}[/]"
                )
                if state in ("completed", "failed"):
                    color = "#7fd18b" if state == "completed" else "#e5687a"
                    status.update(
                        f"[{color} b]{state}[/]  files {done}/{total} · chunks {chunks:,}"
                    )
                    return
            await asyncio.sleep(1.0)

    # ------------------------------------------------------------------
    # Widget events
    # ------------------------------------------------------------------

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-input":
            await self._run_search(event.value)
        elif event.input.id == "ask-input":
            await self._run_ask(event.value)
        elif event.input.id == "index-path":
            await self._start_index_job()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "index-go":
            await self._start_index_job()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id == "search-results" and event.list_view.index is not None:
            self._show_result_detail(event.list_view.index)


__all__ = ["RAGApp"]
