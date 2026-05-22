"""Textual TUI app — HTTP client to the RAG daemon.

The TUI is an interactive front-end: search, ask, index, and inspect the daemon
in real time. State (collections, query log, events, plugins, etc.) is fetched
from the daemon over HTTP — the TUI process holds no model or vectorstore.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

import httpx
import structlog
from rich.syntax import Syntax
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    ListItem,
    ListView,
    ProgressBar,
    RadioSet,
    RichLog,
    Static,
)

from rag.config import ensure_rag_home, get_or_create_token, get_settings
from rag.core.lsp import detect_lsp_servers
from rag.tui.dashboard import (
    CollectionsPanel,
    ConnectionPanel,
    Dashboard,
    PluginsPanel,
    QueryLogPanel,
    StatsPanel,
)
from rag.tui.widgets import IndexStatsWidget, LSPStatusWidget, ModelCard

logger = structlog.get_logger()

_DEFAULT_TOP_K = 8


class RAGApp(App):
    """RAG System TUI — interactive dashboard for the running daemon."""

    TITLE = "RAG System"
    SUB_TITLE = "Code Search Engine"

    CSS = """
    Screen {
        layout: vertical;
    }
    #home-left {
        width: 50;
        min-width: 40;
    }
    #home-right {
        width: 1fr;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "show_help", "Help"),
        Binding("s", "focus_tab('tab-search')", "Search"),
        Binding("a", "focus_tab('tab-ask')", "Ask"),
        Binding("i", "focus_tab('tab-index')", "Index"),
        Binding("f", "focus_tab('tab-filters')", "Filters"),
        Binding("o", "focus_tab('tab-overview')", "Overview"),
        Binding("d", "focus_tab('tab-diff')", "Diff"),
        Binding("l", "focus_tab('tab-logs')", "Logs"),
        Binding("c", "clear_active", "Clear"),
        Binding("t", "toggle_theme", "Theme"),
    ]

    def __init__(self):
        super().__init__()
        self._poll_task: asyncio.Task | None = None
        self._query_poll_task: asyncio.Task | None = None
        self._stats_poll_task: asyncio.Task | None = None
        self._events_poll_task: asyncio.Task | None = None
        self._index_poll_task: asyncio.Task | None = None
        self._collections_poll_task: asyncio.Task | None = None
        self._plugins_poll_task: asyncio.Task | None = None
        self._overview_poll_task: asyncio.Task | None = None

        self._daemon_warned = False
        self._reconnects = 0
        self._last_daemon_up = True

        self._seen_query_ts: set[str] = set()
        self._seen_event_ts: float = 0.0

        # Search state
        self._last_search_results: list[dict] = []

        # Index state
        self._current_job_id: str | None = None

        # Theme
        self._light_theme = False

    # ------------------------------------------------------------------
    # Compose + mount
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        settings = get_settings()
        yield Dashboard(settings.server.host, settings.server.port)

    async def on_mount(self) -> None:
        ensure_rag_home()
        self.set_timer(0.5, self._update_model_status)
        self.set_timer(1.5, self._update_lsp_status)
        self.set_timer(1.0, self._update_index_stats)
        self.set_timer(2.0, self._initial_help_config)

        self._poll_task = asyncio.create_task(self._poll_status())
        self._query_poll_task = asyncio.create_task(self._poll_query_log())
        self._stats_poll_task = asyncio.create_task(self._poll_stats())
        self._events_poll_task = asyncio.create_task(self._poll_events())
        self._collections_poll_task = asyncio.create_task(self._poll_collections())
        self._plugins_poll_task = asyncio.create_task(self._poll_plugins())
        self._overview_poll_task = asyncio.create_task(self._poll_overview())

    # ------------------------------------------------------------------
    # HTTP plumbing
    # ------------------------------------------------------------------

    def _base_url(self) -> str:
        settings = get_settings()
        return f"http://{settings.server.host}:{settings.server.port}"

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {get_or_create_token()}"}

    async def _http_get(self, path: str, *, auth: bool = True, timeout: float = 3.0) -> Any | None:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                headers = self._auth_headers() if auth else {}
                resp = await client.get(f"{self._base_url()}{path}", headers=headers)
                if resp.status_code == 200:
                    self._mark_daemon_up()
                    return resp.json()
                logger.debug("tui_http_non_200", path=path, status=resp.status_code)
                return None
        except Exception as e:
            logger.debug("tui_http_error", path=path, error=str(e))
            self._mark_daemon_down()
            return None

    async def _http_post(self, path: str, payload: dict, *, timeout: float = 300.0) -> Any | None:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    f"{self._base_url()}{path}", json=payload, headers=self._auth_headers()
                )
                if resp.status_code == 200:
                    self._mark_daemon_up()
                    return resp.json()
                logger.debug("tui_http_post_non_200", path=path, status=resp.status_code, body=resp.text[:200])
                return None
        except Exception as e:
            logger.debug("tui_http_post_error", path=path, error=str(e))
            self._mark_daemon_down()
            return None

    def _mark_daemon_up(self) -> None:
        if not self._last_daemon_up:
            self._reconnects += 1
        self._last_daemon_up = True
        self._daemon_warned = False
        try:
            self.query_one("#conn-bar", ConnectionPanel).set_state(True, self._reconnects)
        except Exception:
            pass

    def _mark_daemon_down(self) -> None:
        self._last_daemon_up = False
        try:
            self.query_one("#conn-bar", ConnectionPanel).set_state(False, self._reconnects)
        except Exception:
            pass
        if not self._daemon_warned:
            self._daemon_warned = True
            try:
                self.notify(
                    "Daemon not reachable. Start with: rag start",
                    severity="warning",
                    timeout=10,
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Home tab polling
    # ------------------------------------------------------------------

    async def _update_model_status(self) -> None:
        settings = get_settings()
        try:
            embedder_card = self.query_one("#embedder-card", ModelCard)
            agent_card = self.query_one("#agent-card", ModelCard)

            health = await self._http_get("/health", auth=False)
            status = await self._http_get("/status")

            if health is None and status is None:
                embedder_card.update_info(settings.embeddings.model, "?", "daemon down")
                agent_card.update_info(settings.llm.agent_model, "ollama", "daemon down")
                return

            components = (health or {}).get("components", {}) if health else {}
            provider = (status or {}).get("embedder_provider") or components.get("embedder", "?")
            embedder_model = (status or {}).get("embedder_model") or settings.embeddings.model

            embedder_card.update_info(
                embedder_model,
                str(provider),
                "running" if provider not in ("?", "not_initialized") else "unknown",
            )
            ollama_status = components.get("ollama", "unknown")
            agent_card.update_info(settings.llm.agent_model, "ollama", ollama_status)
        except Exception as e:
            logger.debug("tui_update_error", error=str(e))

    async def _update_lsp_status(self) -> None:
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
        try:
            data = await self._http_get("/status")
            if not data:
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
        while True:
            await asyncio.sleep(10)
            await self._update_index_stats()
            await self._update_model_status()

    async def _poll_query_log(self) -> None:
        first_pass = True
        while True:
            try:
                data = await self._http_get("/queries/recent?limit=20")
                rows = (data or {}).get("queries", []) if data else []
                for row in reversed(rows):
                    key = f"{row.get('timestamp')}|{row.get('query')}"
                    if key in self._seen_query_ts:
                        continue
                    self._seen_query_ts.add(key)
                    if first_pass:
                        continue
                    try:
                        log = self.query_one("#query-log", QueryLogPanel)
                        log.add_entry(
                            query=str(row.get("query", "")),
                            results=int(row.get("results_count") or 0),
                            latency_ms=float(row.get("latency_ms") or 0.0),
                        )
                    except Exception as e:
                        logger.debug("tui_query_log_render_error", error=str(e))
                first_pass = False
            except Exception as e:
                logger.debug("tui_query_log_poll_error", error=str(e))
            await asyncio.sleep(1.0)

    async def _poll_stats(self) -> None:
        while True:
            try:
                data = await self._http_get("/queries/stats?window=100")
                if data:
                    try:
                        self.query_one("#stats-panel", StatsPanel).update_stats(data)
                    except Exception:
                        pass
            except Exception:
                pass
            await asyncio.sleep(5.0)

    async def _poll_collections(self) -> None:
        while True:
            try:
                data = await self._http_get("/collections")
                if data:
                    cols = data.get("collections", [])
                    try:
                        self.query_one("#collections-panel", CollectionsPanel).update_collections(cols)
                    except Exception:
                        pass
            except Exception:
                pass
            await asyncio.sleep(10.0)

    async def _poll_plugins(self) -> None:
        # Plugins rarely change; poll slowly.
        while True:
            try:
                data = await self._http_get("/plugins")
                if data is not None:
                    try:
                        self.query_one("#plugins-panel", PluginsPanel).update_plugins(
                            data.get("plugins", [])
                        )
                    except Exception:
                        pass
            except Exception:
                pass
            await asyncio.sleep(30.0)

    async def _poll_events(self) -> None:
        while True:
            try:
                data = await self._http_get(f"/events/recent?limit=200&after_ts={self._seen_event_ts}")
                events = (data or {}).get("events", []) if data else []
                if events:
                    self._seen_event_ts = max(float(e.get("ts", 0.0)) for e in events)
                    try:
                        view = self.query_one("#logs-view", RichLog)
                    except Exception:
                        view = None
                    if view is not None:
                        for ev in events:
                            ts = datetime.fromtimestamp(float(ev.get("ts", 0.0))).strftime("%H:%M:%S")
                            name = ev.get("event", "?")
                            payload = {k: v for k, v in ev.items() if k not in ("ts", "event")}
                            line = f"[dim]{ts}[/dim] [bold cyan]{name}[/bold cyan] {payload}"
                            view.write(line)
            except Exception as e:
                logger.debug("tui_events_poll_error", error=str(e))
            await asyncio.sleep(1.5)

    async def _poll_overview(self) -> None:
        # Overview is expensive; poll slowly and only when visible isn't easy
        # to detect from outside the widget, so we poll cheaply.
        while True:
            try:
                data = await self._http_get("/overview/tui", timeout=10.0)
                if data is not None:
                    summaries = data.get("summaries", []) or []
                    communities = data.get("communities", []) or []
                    top_nodes = data.get("top_nodes", []) or []
                    try:
                        self.query_one("#ov-summaries", Static).update(
                            "\n".join(f" - {s}" for s in summaries[:20])
                            or "[dim]no summaries[/dim]"
                        )
                        self.query_one("#ov-communities", Static).update(
                            "\n".join(f" - {c}" for c in communities[:10])
                            or "[dim]no communities[/dim]"
                        )
                        self.query_one("#ov-nodes", Static).update(
                            "\n".join(f" - {n}" for n in top_nodes[:10])
                            or "[dim]no graph nodes[/dim]"
                        )
                    except Exception:
                        pass
            except Exception:
                pass
            await asyncio.sleep(30.0)

    async def _initial_help_config(self) -> None:
        try:
            settings = get_settings()
            cfg = {
                "embedder_model": settings.embeddings.model,
                "agent_model": settings.llm.agent_model,
                "ollama_url": settings.llm.ollama_url,
                "qdrant_path": str(settings.qdrant.path),
                "code_collection": settings.qdrant.code_collection,
                "server": f"{settings.server.host}:{settings.server.port}",
            }
            self.query_one("#help-config", Static).update(
                "\n".join(f"  {k}: {v}" for k, v in cfg.items())
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Search / Ask / Index handlers
    # ------------------------------------------------------------------

    def _collect_filters(self) -> dict:
        """Read filter sidebar state into a Qdrant payload filter dict."""
        filters: dict[str, Any] = {}
        langs = []
        for code in ("kotlin", "java", "python", "dart", "typescript"):
            try:
                if self.query_one(f"#f-lang-{code}", Checkbox).value:
                    langs.append(code)
            except Exception:
                pass
        if langs:
            filters["language"] = langs[0] if len(langs) == 1 else langs

        bool_keys = [
            ("f-is-suspend", "is_suspend"),
            ("f-uses-coroutines", "uses_coroutines"),
            ("f-uses-flow", "uses_flow"),
            ("f-uses-async-java", "uses_async_java"),
        ]
        for widget_id, payload_key in bool_keys:
            try:
                if self.query_one(f"#{widget_id}", Checkbox).value:
                    filters[payload_key] = "true"
            except Exception:
                pass

        cts = []
        for code in ("function", "class", "file"):
            try:
                if self.query_one(f"#f-ct-{code}", Checkbox).value:
                    cts.append(code)
            except Exception:
                pass
        if cts:
            filters["chunk_type"] = cts[0] if len(cts) == 1 else cts
        return filters

    def _selected_strategy(self) -> str | None:
        try:
            rs = self.query_one("#f-strategy", RadioSet)
            pressed = rs.pressed_button
            if pressed is None:
                return None
            sid = pressed.id or ""
            if sid == "strat-auto":
                return None
            return sid.replace("strat-", "")
        except Exception:
            return None

    async def _run_search(self, query: str) -> None:
        if not query.strip():
            return
        filters = self._collect_filters()
        payload = {"query": query, "top_k": _DEFAULT_TOP_K}
        if filters:
            payload["filters"] = filters
        # Strategy override is honored by the planner via prefix keyword nudges;
        # the daemon's SearchRequest model doesn't currently accept a "strategy"
        # field. Surface the override in the plan panel anyway so users see what
        # they picked, and pass it through filters for the planner to read.
        strat = self._selected_strategy()

        try:
            self.query_one("#search-plan", Static).update("[dim]searching...[/dim]")
        except Exception:
            pass

        data = await self._http_post("/search", payload)
        if not data:
            try:
                self.query_one("#search-plan", Static).update("[red]search failed[/red]")
            except Exception:
                pass
            return

        plan = data.get("plan") or {}
        plan_line = (
            f"[bold]Strategy:[/bold] {plan.get('strategy', '?')}"
            f"  [bold]Filters:[/bold] {plan.get('filters', {})}"
            f"  [bold]Queries:[/bold] {plan.get('queries', [])}"
            f"  [dim]({data.get('total', 0)} hits, {data.get('latency_ms', 0)}ms)[/dim]"
        )
        if strat:
            plan_line = f"[yellow]override={strat}[/yellow]  " + plan_line
        try:
            self.query_one("#search-plan", Static).update(plan_line)
        except Exception:
            pass

        results = data.get("results", []) or []
        self._last_search_results = results

        try:
            lv = self.query_one("#search-results", ListView)
            await lv.clear()
            for i, r in enumerate(results, 1):
                label = (
                    f"{i:2d}. [{r.get('language', '?')}] "
                    f"{r.get('file_path', '?')}:{r.get('lines', '?')}  "
                    f"score={r.get('score', 0)}  "
                    f"{r.get('name', '')}"
                )
                await lv.append(ListItem(Static(label)))
            if results:
                # Auto-show first result in detail pane
                await self._show_result_detail(0)
        except Exception as e:
            logger.debug("tui_search_render_error", error=str(e))

    async def _show_result_detail(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._last_search_results):
            return
        r = self._last_search_results[idx]
        try:
            detail = self.query_one("#search-detail", RichLog)
            detail.clear()
            header = (
                f"[bold cyan]{r.get('file_path', '?')}:{r.get('lines', '?')}[/bold cyan]\n"
                f"[dim]{r.get('chunk_type', '?')} {r.get('name', '')}  "
                f"score={r.get('score', 0)}[/dim]\n"
            )
            detail.write(header)
            code = r.get("code", "") or ""
            lang = r.get("language", "") or "text"
            try:
                syntax = Syntax(code, lang, theme="monokai", line_numbers=False, word_wrap=False)
                detail.write(syntax)
            except Exception:
                detail.write(code)
        except Exception as e:
            logger.debug("tui_detail_error", error=str(e))

    async def _run_ask(self, question: str) -> None:
        if not question.strip():
            return
        try:
            ans = self.query_one("#ask-answer", RichLog)
            ans.clear()
            ans.write("[dim]asking...[/dim]")
        except Exception:
            pass

        payload = {"question": question, "top_k": _DEFAULT_TOP_K}
        data = await self._http_post("/ask", payload, timeout=300.0)
        if not data:
            try:
                self.query_one("#ask-answer", RichLog).write("[red]ask failed[/red]")
            except Exception:
                pass
            return
        try:
            ans = self.query_one("#ask-answer", RichLog)
            ans.clear()
            meta = (
                f"[dim]model={data.get('model', '?')}  "
                f"retrieval={data.get('retrieval_ms', 0)}ms  "
                f"gen={data.get('generation_ms', 0)}ms[/dim]\n"
            )
            ans.write(meta)
            ans.write(data.get("answer", ""))
        except Exception:
            pass

        try:
            lv = self.query_one("#ask-citations", ListView)
            await lv.clear()
            for i, c in enumerate(data.get("citations", []), 1):
                label = (
                    f"[{i}] {c.get('file_path', '?')}:{c.get('lines', '?')}  "
                    f"({c.get('name', '')})  score={c.get('score', 0)}"
                )
                await lv.append(ListItem(Static(label)))
        except Exception:
            pass

    async def _start_index_job(self) -> None:
        try:
            path = self.query_one("#index-path", Input).value.strip()
            full = self.query_one("#index-full", Checkbox).value
        except Exception:
            return
        if not path:
            self.notify("Enter a path first", severity="warning")
            return

        try:
            self.query_one("#index-status", Static).update(f"[dim]starting job for {path}...[/dim]")
        except Exception:
            pass

        data = await self._http_post("/index/start", {"repo_path": path, "full": full})
        if not data:
            try:
                self.query_one("#index-status", Static).update("[red]failed to start index job[/red]")
            except Exception:
                pass
            return
        self._current_job_id = data.get("job_id")
        if self._index_poll_task and not self._index_poll_task.done():
            self._index_poll_task.cancel()
        self._index_poll_task = asyncio.create_task(self._poll_index_progress())

    async def _poll_index_progress(self) -> None:
        if not self._current_job_id:
            return
        job_id = self._current_job_id
        last_recent_ts = 0.0
        while True:
            data = await self._http_get(f"/index/progress/{job_id}")
            if not data:
                await asyncio.sleep(1.0)
                continue
            status = data.get("status", "?")
            total = int(data.get("total_files", 0) or 0)
            done = int(data.get("files_processed", 0) or 0)
            cur = data.get("current_file", "")
            chunks = int(data.get("chunks_indexed", 0) or 0)

            try:
                bar = self.query_one("#index-progress", ProgressBar)
                if total > 0:
                    bar.update(total=total, progress=done)
                else:
                    bar.update(total=100, progress=0)
            except Exception:
                pass
            try:
                self.query_one("#index-status", Static).update(
                    f"[bold]{status}[/bold]  files={done}/{total}  chunks={chunks}  cur=[cyan]{cur}[/cyan]"
                )
            except Exception:
                pass

            # Recent files
            try:
                rdata = await self._http_get(f"/files/recent?limit=30")
                files = (rdata or {}).get("files", []) if rdata else []
                lv = self.query_one("#index-recent", ListView)
                # Only append entries newer than last seen
                new_entries = [f for f in files if float(f.get("ts", 0.0)) > last_recent_ts]
                if new_entries:
                    last_recent_ts = max(float(f.get("ts", 0.0)) for f in new_entries)
                    for f in new_entries:
                        ts = datetime.fromtimestamp(float(f.get("ts", 0.0))).strftime("%H:%M:%S")
                        await lv.append(ListItem(Static(f"{ts}  {f.get('path', '?')}")))
            except Exception:
                pass

            if status in ("completed", "failed"):
                break
            await asyncio.sleep(1.0)

    async def _run_diff(self) -> None:
        try:
            q = self.query_one("#diff-q", Input).value.strip()
            since = self.query_one("#diff-since", Input).value.strip() or "HEAD~5"
        except Exception:
            return
        if not q:
            self.notify("Enter a diff query", severity="warning")
            return
        out = self.query_one("#diff-output", RichLog)
        out.clear()
        out.write(f"[dim]running diff query={q!r} since={since!r}...[/dim]")
        # Daemon currently exposes diff only via CLI. Surface a helpful message
        # rather than silently failing.
        out.write(
            "[yellow]Note:[/yellow] /diff endpoint not yet wired.  "
            f"Run from another terminal: [bold]rag diff {q!r} --since {since}[/bold]"
        )

    # ------------------------------------------------------------------
    # Textual event handlers
    # ------------------------------------------------------------------

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-input":
            await self._run_search(event.value)
        elif event.input.id == "ask-input":
            await self._run_ask(event.value)
        elif event.input.id == "diff-q":
            await self._run_diff()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "index-go":
            await self._start_index_job()
        elif bid == "diff-go":
            await self._run_diff()

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        # Only act for the search results list
        try:
            parent_id = event.list_view.id
        except Exception:
            parent_id = None
        if parent_id != "search-results":
            return
        idx = event.list_view.index
        if idx is not None:
            await self._show_result_detail(idx)

    # ------------------------------------------------------------------
    # Actions (key bindings)
    # ------------------------------------------------------------------

    def action_show_help(self) -> None:
        try:
            from textual.widgets import TabbedContent
            self.query_one(TabbedContent).active = "tab-help"
        except Exception:
            pass

    def action_focus_tab(self, tab_id: str) -> None:
        try:
            from textual.widgets import TabbedContent
            self.query_one(TabbedContent).active = tab_id
        except Exception:
            pass

    def action_clear_active(self) -> None:
        # Try clearing query log first, then results, then ask.
        for wid, kind in (
            ("#query-log", "log"),
            ("#search-results", "list"),
            ("#search-detail", "richlog"),
            ("#ask-answer", "richlog"),
            ("#ask-citations", "list"),
            ("#logs-view", "richlog"),
        ):
            try:
                w = self.query_one(wid)
                if kind == "log" and hasattr(w, "clear_log"):
                    w.clear_log()
                elif kind == "list":
                    w.clear()
                elif kind == "richlog":
                    w.clear()
            except Exception:
                pass

    def action_toggle_theme(self) -> None:
        self._light_theme = not self._light_theme
        try:
            self.theme = "textual-light" if self._light_theme else "textual-dark"
        except Exception:
            try:
                self.dark = not self._light_theme
            except Exception:
                pass

    async def action_quit(self) -> None:
        for t in (
            self._poll_task,
            self._query_poll_task,
            self._stats_poll_task,
            self._events_poll_task,
            self._index_poll_task,
            self._collections_poll_task,
            self._plugins_poll_task,
            self._overview_poll_task,
        ):
            if t:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
        try:
            from rag.storage.db import close_connection
            close_connection()
        except Exception:
            pass
        self.exit()
