"""Textual TUI app — interactive HTTP client to the RAG daemon.

Redesigned layout (see ragsystem.pen):

  - Always-visible top status bar (daemon dot, screen, repo, models, qpm, mem, clock)
  - Left sidebar (8 nav items)
  - Bottom :cmd line (REPL-style)
  - Center: one of 8 swappable screens (Home/Search/Ask/Index/Filters/Overview/Logs/Help)
  - ⌘K / ctrl+k command palette modal

All daemon state is fetched over HTTP — TUI process holds no model or vectorstore.
"""

from __future__ import annotations

import asyncio
import shlex
from datetime import datetime
from typing import Any

import httpx
import structlog
from rich.syntax import Syntax
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.theme import Theme

RAG_THEME = Theme(
    name="rag-mono",
    primary="#5EE6D0",
    secondary="#B084EB",
    accent="#5EE6D0",
    foreground="#C8D6E5",
    background="#0A0E14",
    surface="#12161E",
    panel="#1A1F2A",
    boost="#10161D",
    warning="#E0B466",
    error="#E5687A",
    success="#7FD18B",
    dark=True,
    variables={
        "block-cursor-text-style": "bold",
        "footer-key-foreground": "#5EE6D0",
        "footer-key-background": "#10161D",
    },
)
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
    CommandPalette,
    Dashboard,
    Sidebar,
    StatusBar,
)

logger = structlog.get_logger()

_DEFAULT_TOP_K = 8
_SPARK_CHARS = " ▁▂▃▄▅▆▇█"


def _resize(values: list[float], width: int) -> list[float]:
    """Pad-left or bin-average so values has exactly `width` entries."""
    if not values:
        return [0.0] * width
    if len(values) > width:
        step = len(values) / width
        binned = []
        for i in range(width):
            lo = int(i * step)
            hi = int((i + 1) * step) or lo + 1
            chunk = values[lo:hi] or [0.0]
            binned.append(sum(chunk) / len(chunk))
        return binned
    if len(values) < width:
        return [0.0] * (width - len(values)) + values
    return values


def _sparkline(values: list[float], width: int = 24) -> str:
    """Render single-row unicode block sparkline."""
    if not values:
        return "─" * width
    values = _resize(values, width)
    vmax = max(values) or 1.0
    out = []
    for v in values:
        idx = min(len(_SPARK_CHARS) - 1, max(0, int(v / vmax * (len(_SPARK_CHARS) - 1))))
        out.append(_SPARK_CHARS[idx])
    return "".join(out)


def _bars(values: list[float], width: int, height: int) -> str:
    """Render a multi-row bar chart using unicode block chars.

    Each column shows a bar from the bottom up; columns above the bar are
    blank. Returns a newline-joined string of `height` rows × `width` chars.
    """
    if height <= 0 or width <= 0:
        return ""
    values = _resize(values, width)
    vmax = max(values) or 1.0
    # Each row contributes 8 sub-levels via the partial-block chars.
    levels = height * 8
    col_levels = [
        min(levels, max(0, int(v / vmax * levels))) for v in values
    ]
    rows: list[str] = []
    for row_idx in range(height):
        # Row 0 is the top; row height-1 is the bottom.
        from_bottom = height - 1 - row_idx
        row_chars: list[str] = []
        for col in col_levels:
            # How much of this row is filled?
            row_start = from_bottom * 8
            row_end = row_start + 8
            if col >= row_end:
                row_chars.append("█")
            elif col <= row_start:
                row_chars.append(" ")
            else:
                row_chars.append(_SPARK_CHARS[col - row_start])
        rows.append("".join(row_chars))
    return "\n".join(rows)


def _bin_timestamps(timestamps: list[float], window_sec: int, bin_sec: int) -> list[int]:
    """Count how many timestamps fall into each bin over the trailing window.
    Returns list of counts, oldest-first."""
    import time as _t

    now = _t.time()
    n_bins = max(1, window_sec // bin_sec)
    counts = [0] * n_bins
    cutoff = now - window_sec
    for ts in timestamps:
        if ts < cutoff:
            continue
        offset = now - ts
        idx = n_bins - 1 - int(offset // bin_sec)
        if 0 <= idx < n_bins:
            counts[idx] += 1
    return counts


class RAGApp(App):
    """RAG System TUI — redesigned dashboard for the running daemon."""

    TITLE = "RAG System"
    SUB_TITLE = "Code Search Engine"

    CSS = """
    Screen {
        background: #0a0e14;
        color: #c8d6e5;
    }
    Sidebar {
        background: #10161d;
    }
    StatusBar {
        background: #12161e;
        color: #5a6a7a;
    }
    CmdLine {
        background: #141b23;
    }
    CmdLine Input {
        background: #141b23;
    }
    CmdLine Input:focus {
        background: #1a2330;
        border: none;
    }
    .screen-title {
        color: #5ee6d0;
        text-style: bold;
        padding: 0 2;
        height: 1;
    }
    .kpi {
        background: #10161d;
    }
    .panel {
        background: #10161d;
    }
    .filter-group {
        background: #10161d;
    }
    Input {
        background: #10161d;
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
    RichLog {
        background: #060a10;
        padding: 1 2;
    }
    ProgressBar {
        background: transparent;
    }
    ProgressBar > Bar {
        color: #5ee6d0;
    }
    Checkbox {
        background: transparent;
    }
    Checkbox:focus > .toggle--label {
        text-style: bold;
    }
    RadioSet {
        background: transparent;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "goto('help')", "Help", show=False),
        Binding("ctrl+k", "palette", "⌘K Palette"),
        Binding("colon", "focus_cmd", ":cmd", show=False),
        Binding("h", "goto('home')", "Home"),
        Binding("s", "goto('search')", "Search"),
        Binding("a", "goto('ask')", "Ask"),
        Binding("i", "goto('index')", "Index"),
        Binding("f", "goto('filters')", "Filters"),
        Binding("o", "goto('overview')", "Overview"),
        Binding("l", "goto('logs')", "Logs"),
        Binding("c", "clear_active", "Clear"),
    ]

    def __init__(self, initial_screen: str = "home"):
        super().__init__()
        self._initial_screen = initial_screen
        self._poll_tasks: list[asyncio.Task] = []
        self._daemon_warned = False
        self._reconnects = 0
        self._last_daemon_up = True

        self._seen_query_ts: set[str] = set()
        self._seen_event_ts: float = 0.0
        self._last_search_results: list[dict] = []
        self._current_job_id: str | None = None
        self._index_poll_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Compose + mount
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        settings = get_settings()
        yield Dashboard(settings.server.host, settings.server.port, initial_screen=self._initial_screen, id="dashboard")

    async def on_mount(self) -> None:
        ensure_rag_home()
        try:
            self.register_theme(RAG_THEME)
            self.theme = "rag-mono"
        except Exception as e:
            logger.debug("theme_register_failed", error=str(e))
        self._poll_tasks.append(asyncio.create_task(self._poll_status()))
        self._poll_tasks.append(asyncio.create_task(self._poll_query_log()))
        self._poll_tasks.append(asyncio.create_task(self._poll_stats()))
        self._poll_tasks.append(asyncio.create_task(self._poll_events()))
        self._poll_tasks.append(asyncio.create_task(self._poll_collections()))
        self._poll_tasks.append(asyncio.create_task(self._poll_plugins()))
        self._poll_tasks.append(asyncio.create_task(self._poll_overview()))
        self._poll_tasks.append(asyncio.create_task(self._poll_health_detail()))

    # ------------------------------------------------------------------
    # HTTP helpers
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
            self.query_one("#status-bar", StatusBar).daemon_ok = True
        except Exception:
            pass

    def _mark_daemon_down(self) -> None:
        self._last_daemon_up = False
        try:
            self.query_one("#status-bar", StatusBar).daemon_ok = False
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
    # Polling loops
    # ------------------------------------------------------------------

    async def _poll_status(self) -> None:
        settings = get_settings()
        while True:
            try:
                status = await self._http_get("/status")
                sb = self.query_one("#status-bar", StatusBar)
                if status:
                    sb.embedder = status.get("embedder_model", "?")
                    cols = status.get("collections", []) or []
                    if cols:
                        sb.repo_name = cols[0].get("name", "?")
                    # KPI cards — uppercase dim label, large coloured value, dim caption.
                    try:
                        kpi = self.query_one("#kpi-index", Static)
                        n_chunks = cols[0].get("points_count", 0) if cols else 0
                        # files_indexed comes from /status when available
                        n_files = status.get("files_indexed") or status.get("file_count") or 0
                        files_line = f"{n_files:,} files" if n_files else "indexed"
                        kpi.update(
                            f"[#5a6a7a]INDEX SIZE[/]\n"
                            f"[bold #5ee6d0]{n_chunks:,}[/]\n"
                            f"[#5a6a7a]chunks · {files_line}[/]"
                        )
                    except Exception:
                        pass
                    try:
                        kpi = self.query_one("#kpi-embedder", Static)
                        emb = (status.get("embedder_model") or "?").split(":")[0]
                        emb_short = emb.replace("qwen3-embedding", "qwen3-emb")
                        warm = status.get("embedder_warm_ms")
                        if isinstance(warm, (int, float)) and warm < 500:
                            warm_line = f"Ollama · {warm:.0f}ms warm"
                        else:
                            warm_line = "Ollama"
                        kpi.update(
                            f"[#5a6a7a]EMBEDDER[/]\n"
                            f"[bold #5ee6d0]{emb_short}[/]\n"
                            f"[#5a6a7a]{warm_line}[/]"
                        )
                    except Exception:
                        pass
                    try:
                        kpi = self.query_one("#kpi-gen", Static)
                        gen = settings.llm.gen_model or settings.llm.agent_model or "?"
                        ctx = settings.llm.ctx_size if hasattr(settings.llm, "ctx_size") else None
                        ctx_line = f"ctx {ctx} · streaming" if ctx else "Ollama · streaming"
                        kpi.update(
                            f"[#5a6a7a]GENERATOR[/]\n"
                            f"[bold #b084eb]{gen}[/]\n"
                            f"[#5a6a7a]{ctx_line}[/]"
                        )
                    except Exception:
                        pass
                    try:
                        kpi = self.query_one("#kpi-uptime", Static)
                        up = status.get("uptime_seconds", 0) or 0
                        days = int(up // 86400)
                        hours = int((up % 86400) // 3600)
                        minutes = int((up % 3600) // 60)
                        if days:
                            up_str = f"{days}d {hours}h"
                        elif hours:
                            up_str = f"{hours}h {minutes}m"
                        else:
                            up_str = f"{minutes}m"
                        restarts = status.get("restart_count", 0) or 0
                        if restarts == 0:
                            caption = "no restarts"
                        elif restarts == 1:
                            caption = "1 restart"
                        else:
                            caption = f"{restarts} restarts"
                        kpi.update(
                            f"[#5a6a7a]UPTIME[/]\n"
                            f"[bold #7fd18b]{up_str}[/]\n"
                            f"[#5a6a7a]{caption}[/]"
                        )
                    except Exception:
                        pass
                # Help-screen config
                try:
                    cfg = self.query_one("#help-config", Static)
                    cfg.update(
                        f"  [cyan]embedder[/cyan] : {settings.embeddings.model}\n"
                        f"  [cyan]agent   [/cyan] : {settings.llm.agent_model}\n"
                        f"  [cyan]gen     [/cyan] : {settings.llm.gen_model or settings.llm.agent_model}\n"
                        f"  [cyan]ollama  [/cyan] : {settings.llm.ollama_url}\n"
                        f"  [cyan]server  [/cyan] : {settings.server.host}:{settings.server.port}\n"
                    )
                except Exception:
                    pass
            except Exception as e:
                logger.debug("tui_status_poll_error", error=str(e))
            await asyncio.sleep(5.0)

    async def _poll_query_log(self) -> None:
        first_pass = True
        while True:
            try:
                # Pull more for sparkline binning; only render new entries to list.
                data = await self._http_get("/queries/recent?limit=200")
                rows = (data or {}).get("queries", []) if data else []
                # Build sparkline: 48 bins over 24h (one bar = 30 min)
                if rows:
                    try:
                        ts_list: list[float] = []
                        for r in rows:
                            ts = r.get("timestamp")
                            if isinstance(ts, (int, float)):
                                ts_list.append(float(ts))
                            elif isinstance(ts, str):
                                try:
                                    ts_list.append(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())
                                except Exception:
                                    pass
                        spark_bins = _bin_timestamps(ts_list, window_sec=24 * 3600, bin_sec=30 * 60)
                        peak = max(spark_bins) if spark_bins else 0
                        avg = (sum(spark_bins) / len(spark_bins)) if spark_bins else 0
                        # Single-row tall sparkbar like the mockup.
                        bar = _sparkline([float(x) for x in spark_bins], width=48)
                        try:
                            self.query_one("#qpm-spark", Static).update(f"[#5ee6d0]{bar}[/]")
                        except Exception:
                            pass
                        try:
                            from rag.tui.dashboard import PanelHeader
                            hdr = self.query_one("#qpm-header", PanelHeader)
                            hdr.update_meta(f"avg {avg:.0f} · peak {peak}")
                        except Exception:
                            pass
                    except Exception as e:
                        logger.debug("tui_sparkline_error", error=str(e))
                if rows and not first_pass:
                    try:
                        lv = self.query_one("#home-recent-queries", ListView)
                        for row in reversed(rows):
                            key = f"{row.get('timestamp')}|{row.get('query')}"
                            if key in self._seen_query_ts:
                                continue
                            self._seen_query_ts.add(key)
                            ts = str(row.get("timestamp", ""))[11:16]
                            strategy = row.get("strategy") or "hybrid"
                            score = row.get("score") or row.get("top_score")
                            score_txt = f"{float(score):.2f}" if isinstance(score, (int, float, str)) and str(score).replace(".","",1).isdigit() else "—"
                            query_text = str(row.get("query", ""))[:34]
                            await lv.append(
                                ListItem(
                                    Static(
                                        f"[#5a6a7a]{ts}[/]  [#c8d6e5]{query_text:<34}[/]  "
                                        f"[#b084eb]{strategy:<10}[/] [#5ee6d0]{score_txt}[/]"
                                    )
                                )
                            )
                    except Exception:
                        pass
                # Seed seen set on first pass
                if first_pass:
                    for row in rows:
                        self._seen_query_ts.add(f"{row.get('timestamp')}|{row.get('query')}")
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
                        self.query_one("#status-bar", StatusBar).qpm = data.get("qpm", 0.0)
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
                    lines = []
                    # 28-col right panel: name left, count right-aligned.
                    for c in cols:
                        name = c.get("name", "?")
                        pts = c.get("points_count", 0)
                        pts_str = f"{pts:,}"
                        # Pad name so the count hugs the right edge of the 26-col body.
                        pad_width = max(1, 26 - len(name) - len(pts_str) - 2)
                        spacer = " " * pad_width
                        lines.append(
                            f"[#7fb6f0]▸[/] [#c8d6e5]{name}[/]{spacer}[#5a6a7a]{pts_str}[/]"
                        )
                    try:
                        self.query_one("#home-collections", Static).update(
                            "\n".join(lines) or "[dim]no collections[/dim]"
                        )
                    except Exception:
                        pass
            except Exception:
                pass
            await asyncio.sleep(10.0)

    async def _poll_plugins(self) -> None:
        while True:
            try:
                data = await self._http_get("/plugins")
                if data is not None:
                    plugins = data.get("plugins", [])
                    lines: list[str] = []
                    for p in plugins:
                        name = p.get("name", "?")
                        enabled = p.get("enabled", True)
                        if enabled:
                            lines.append(f"[#7fd18b]●[/] [#c8d6e5]{name}[/]")
                        else:
                            lines.append(f"[#5a6a7a]○ {name}[/]")
                    try:
                        self.query_one("#home-plugins", Static).update(
                            "\n".join(lines) or "[dim]no plugins[/dim]"
                        )
                    except Exception:
                        pass
            except Exception:
                pass
            await asyncio.sleep(30.0)

    async def _poll_events(self) -> None:
        while True:
            try:
                # Always pull a fresh window for the heatmap (after_ts not used here);
                # delta-only updates also for the live tail.
                full = await self._http_get("/events/recent?limit=500")
                events_full = (full or {}).get("events", []) if full else []
                # Heatmap: 80 bins over last 24h (~18-min each)
                if events_full:
                    try:
                        ts_all = [float(e.get("ts", 0.0)) for e in events_full if e.get("ts")]
                        bins = _bin_timestamps(ts_all, window_sec=24 * 3600, bin_sec=18 * 60)
                        heat = _sparkline([float(x) for x in bins], width=80)
                        try:
                            self.query_one("#logs-heatmap", Static).update(
                                "[bold]24h event volume (≈18-min bins)[/bold]\n"
                                f"[#5ee6d0]{heat}[/]\n"
                                "[dim]00:00                                       12:00                                       23:59[/]"
                            )
                        except Exception:
                            pass
                    except Exception as e:
                        logger.debug("tui_heatmap_error", error=str(e))
                # Delta tail for the RichLog
                delta_events = [e for e in events_full if float(e.get("ts", 0.0)) > self._seen_event_ts]
                if delta_events:
                    self._seen_event_ts = max(float(e.get("ts", 0.0)) for e in delta_events)
                    try:
                        view = self.query_one("#logs-view", RichLog)
                        for ev in delta_events:
                            ts = datetime.fromtimestamp(float(ev.get("ts", 0.0))).strftime("%H:%M:%S")
                            name = ev.get("event", "?")
                            payload = {k: v for k, v in ev.items() if k not in ("ts", "event")}
                            line = f"[#5a6a7a]{ts}[/] [#5ee6d0 b]{name}[/] [#c8d6e5]{payload}[/]"
                            view.write(line)
                    except Exception:
                        pass
            except Exception as e:
                logger.debug("tui_events_poll_error", error=str(e))
            await asyncio.sleep(1.5)

    async def _poll_overview(self) -> None:
        while True:
            try:
                data = await self._http_get("/overview/tui", timeout=10.0)
                if data is not None:
                    s = data.get("summaries", []) or []
                    c = data.get("communities", []) or []
                    n = data.get("top_nodes", []) or []
                    try:
                        self.query_one("#ov-summaries", Static).update(
                            "\n".join(f" - {x}" for x in s[:20]) or "[dim]no summaries[/dim]"
                        )
                    except Exception:
                        pass
                    try:
                        self.query_one("#ov-communities", Static).update(
                            "\n".join(f" - {x}" for x in c[:10]) or "[dim]no communities[/dim]"
                        )
                    except Exception:
                        pass
                    try:
                        self.query_one("#ov-nodes", Static).update(
                            "\n".join(f" - {x}" for x in n[:10]) or "[dim]no graph nodes[/dim]"
                        )
                    except Exception:
                        pass
            except Exception:
                pass
            await asyncio.sleep(30.0)

    async def _poll_health_detail(self) -> None:
        # Once per minute is plenty for memory metric.
        import os
        while True:
            try:
                # Pull RSS of the current TUI process — cheapest "mem" indicator.
                # We don't have psutil; read mach_vm size via /proc/self/status would
                # be Linux-only. Fall back to garbage value 0 if unavailable.
                try:
                    import resource
                    rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                    # On macOS getrusage returns bytes; on Linux returns kilobytes.
                    if os.uname().sysname == "Darwin":
                        rss_mb = int(rss_kb / (1024 * 1024))
                    else:
                        rss_mb = int(rss_kb / 1024)
                    self.query_one("#status-bar", StatusBar).mem_mb = rss_mb
                except Exception:
                    pass
            except Exception:
                pass
            await asyncio.sleep(15.0)

    # ------------------------------------------------------------------
    # Filter / strategy collection
    # ------------------------------------------------------------------

    def _collect_filters(self) -> dict:
        filters: dict[str, Any] = {}
        for code in ("kotlin", "java", "python", "dart", "typescript"):
            try:
                if self.query_one(f"#f-lang-{code}", Checkbox).value:
                    filters["language"] = code  # last wins; multi-select unsupported here
            except Exception:
                pass
        bool_keys = [
            ("f-is-suspend", "is_suspend"),
            ("f-uses-coroutines", "uses_coroutines"),
            ("f-uses-flow", "uses_flow"),
            ("f-uses-async-java", "uses_async_java"),
            ("f-is-singleton", "is_singleton"),
            ("f-is-data-class", "is_data_class"),
            ("f-is-sealed", "is_sealed"),
            ("f-is-interface", "is_interface"),
            ("f-is-composable", "is_composable"),
            ("f-is-di-component", "is_di_component"),
        ]
        for wid, key in bool_keys:
            try:
                if self.query_one(f"#{wid}", Checkbox).value:
                    filters[key] = "true"
            except Exception:
                pass
        return filters

    # ------------------------------------------------------------------
    # Search / Ask / Index runners
    # ------------------------------------------------------------------

    async def _run_search(self, query: str) -> None:
        if not query.strip():
            return
        await self.action_goto("search")
        filters = self._collect_filters()
        payload: dict = {"query": query, "top_k": _DEFAULT_TOP_K}
        if filters:
            payload["filters"] = filters

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
            f"  [bold]Filters:[/bold] {plan.get('filters', {})}\n"
            f"[bold]Queries:[/bold] {plan.get('queries', [])}\n"
            f"[dim]({data.get('total', 0)} hits · {data.get('latency_ms', 0):.0f}ms)[/dim]"
        )
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
                    f"{i:2d}. [cyan]{r.get('language', '?')}[/cyan] "
                    f"{r.get('file_path', '?')}:{r.get('lines', '?')}\n"
                    f"     [dim]{r.get('name', '')}  score={r.get('score', 0)}[/dim]"
                )
                await lv.append(ListItem(Static(label)))
            if results:
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
                f"[dim]{r.get('chunk_type', '?')}  {r.get('name', '')}  score={r.get('score', 0)}[/dim]\n"
            )
            detail.write(header)
            code = r.get("code", "") or ""
            lang = r.get("language", "") or "text"
            try:
                detail.write(Syntax(code, lang, theme="monokai", line_numbers=False, word_wrap=False))
            except Exception:
                detail.write(code)
        except Exception as e:
            logger.debug("tui_detail_error", error=str(e))

    async def _run_ask(self, question: str) -> None:
        if not question.strip():
            return
        await self.action_goto("ask")
        try:
            ans = self.query_one("#ask-answer", RichLog)
            ans.clear()
            ans.write("[dim]asking...[/dim]")
        except Exception:
            pass

        data = await self._http_post(
            "/ask", {"question": question, "top_k": _DEFAULT_TOP_K}, timeout=300.0
        )
        if not data:
            try:
                self.query_one("#ask-answer", RichLog).write("[red]ask failed[/red]")
            except Exception:
                pass
            return

        try:
            ans = self.query_one("#ask-answer", RichLog)
            ans.clear()
            ans.write(data.get("answer", ""))
        except Exception:
            pass
        try:
            lv = self.query_one("#ask-citations", ListView)
            await lv.clear()
            for i, c in enumerate(data.get("citations", []), 1):
                label = (
                    f"[cyan][{i}][/cyan] {c.get('file_path', '?')}:{c.get('lines', '?')}\n"
                    f"     [dim]{c.get('name', '')}  score={c.get('score', 0)}[/dim]"
                )
                await lv.append(ListItem(Static(label)))
        except Exception:
            pass
        try:
            meta = self.query_one("#ask-meta", Static)
            meta.update(
                f"[dim]model=[/dim]{data.get('model', '?')}  "
                f"[dim]retrieval=[/dim]{data.get('retrieval_ms', 0):.0f}ms  "
                f"[dim]gen=[/dim]{data.get('generation_ms', 0):.0f}ms  "
                f"[dim]total=[/dim]{data.get('latency_ms', 0):.0f}ms"
            )
        except Exception:
            pass

    async def _start_index_job(self, path: str | None = None, full: bool = False) -> None:
        if path is None:
            try:
                path = self.query_one("#index-path", Input).value.strip()
            except Exception:
                path = ""
        if not path:
            self.notify("Enter a path first", severity="warning")
            return
        await self.action_goto("index")
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
            except Exception:
                pass
            try:
                self.query_one("#index-status", Static).update(
                    f"[bold]{status}[/bold]  files={done}/{total}  chunks={chunks}  cur=[cyan]{cur}[/cyan]"
                )
            except Exception:
                pass
            try:
                rdata = await self._http_get("/files/recent?limit=30")
                files = (rdata or {}).get("files", []) if rdata else []
                lv = self.query_one("#index-recent", ListView)
                new_entries = [f for f in files if float(f.get("ts", 0.0)) > last_recent_ts]
                if new_entries:
                    last_recent_ts = max(float(f.get("ts", 0.0)) for f in new_entries)
                    for f in new_entries:
                        ts = datetime.fromtimestamp(float(f.get("ts", 0.0))).strftime("%H:%M:%S")
                        await lv.append(ListItem(Static(f"  {ts}  {f.get('path', '?')}")))
            except Exception:
                pass
            if status in ("completed", "failed"):
                break
            await asyncio.sleep(1.0)

    # ------------------------------------------------------------------
    # :cmd line parser
    # ------------------------------------------------------------------

    async def _exec_cmd(self, line: str) -> None:
        """Parse a :cmd line and dispatch."""
        s = line.strip()
        if not s:
            return
        if s.startswith(":"):
            s = s[1:]
        try:
            parts = shlex.split(s)
        except ValueError:
            parts = s.split()
        if not parts:
            return
        verb = parts[0].lower()
        rest = parts[1:]
        args = " ".join(rest)

        if verb in ("goto", "go"):
            target = rest[0].lower() if rest else ""
            await self.action_goto(target)
        elif verb in ("search", "s"):
            await self._run_search(args)
        elif verb in ("ask", "a"):
            await self._run_ask(args)
        elif verb in ("list", "ls", "enum"):
            await self._run_list(rest)
        elif verb in ("index",):
            full = "--full" in rest
            rest_no_full = [r for r in rest if r != "--full"]
            path = rest_no_full[0] if rest_no_full else None
            await self._start_index_job(path, full=full)
        elif verb in ("filter", "filters"):
            await self.action_goto("filters")
        elif verb in ("strategy",):
            self.notify(f"strategy override: {args} (use Filters tab radio)", severity="information")
        elif verb in ("status",):
            data = await self._http_get("/status")
            self.notify(f"chunks={(data or {}).get('collections',[{}])[0].get('points_count','?')}", severity="information")
        elif verb in ("health",):
            await self._show_health_modal()
        elif verb in ("events",):
            await self.action_goto("logs")
        elif verb in ("collections", "plugins"):
            await self.action_goto("home")
        elif verb in ("clear",):
            self.action_clear_active()
        elif verb in ("reload",):
            await self._http_post("/admin/reload", {})
            self.notify("config reloaded", severity="information")
        else:
            self.notify(f"unknown cmd: {verb}", severity="warning")

    async def _run_list(self, args: list[str]) -> None:
        """':list is_singleton --lang kotlin' → /enumerate."""
        if not args:
            self.notify("usage: list <flag> [--lang X]", severity="warning")
            return
        flag = args[0]
        filters: dict[str, Any] = {flag: "true"}
        if "--lang" in args:
            try:
                idx = args.index("--lang")
                filters["language"] = args[idx + 1]
            except (ValueError, IndexError):
                pass
        data = await self._http_post(
            "/enumerate",
            {"filters": filters, "limit": 500, "fields": ["file_path", "name", "start_line", "end_line", "language"]},
        )
        if not data:
            self.notify("enumerate failed", severity="error")
            return
        # Surface as a search-like list in the Search screen
        await self.action_goto("search")
        try:
            self.query_one("#search-plan", Static).update(
                f"[bold]/enumerate[/bold]  filters={filters}  [dim]({data.get('count', 0)} matches)[/dim]"
            )
        except Exception:
            pass
        try:
            lv = self.query_one("#search-results", ListView)
            await lv.clear()
            seen_paths: set[str] = set()
            for r in data.get("results", []):
                fp = r.get("file_path", "")
                if fp in seen_paths:
                    continue
                seen_paths.add(fp)
                label = (
                    f"[cyan]{r.get('language', '?')}[/cyan]  {fp}:{r.get('start_line','?')}-{r.get('end_line','?')}\n"
                    f"     [dim]{r.get('name', '')}[/dim]"
                )
                await lv.append(ListItem(Static(label)))
            self._last_search_results = []  # detail pane is N/A for enumerations
            self.query_one("#search-detail", RichLog).clear()
        except Exception as e:
            logger.debug("tui_list_render_error", error=str(e))

    async def _show_health_modal(self) -> None:
        data = await self._http_get("/health/detail", timeout=5.0)
        if not data:
            self.notify("health detail unavailable", severity="warning")
            return
        models = ", ".join(m.get("name", "?") for m in (data.get("ollama_models") or [])[:6])
        msg = (
            f"ollama={data.get('ollama_version','?')}  embed={data.get('embedder_model','?')}  "
            f"agent={data.get('agent_model','?')}\nmodels: {models}"
        )
        self.notify(msg, severity="information", timeout=15)

    # ------------------------------------------------------------------
    # Textual event handlers
    # ------------------------------------------------------------------

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        wid = event.input.id
        if wid == "search-input":
            await self._run_search(event.value)
        elif wid == "ask-input":
            await self._run_ask(event.value)
        elif wid == "cmd-input":
            line = event.value
            event.input.value = ""
            await self._exec_cmd(line)
        elif wid == "index-path":
            await self._start_index_job(event.value.strip())

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "index-go":
            await self._start_index_job()

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        try:
            parent_id = event.list_view.id
        except Exception:
            parent_id = None
        if parent_id == "search-results":
            idx = event.list_view.index
            if idx is not None:
                await self._show_result_detail(idx)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def action_goto(self, screen: str) -> None:
        try:
            dash = self.query_one("#dashboard", Dashboard)
            await dash.switch_screen(screen)
        except Exception as e:
            logger.debug("tui_switch_screen_error", error=str(e))

    def action_clear_active(self) -> None:
        for wid in ("#search-results", "#search-detail", "#ask-answer", "#ask-citations", "#logs-view"):
            try:
                w = self.query_one(wid)
                if hasattr(w, "clear"):
                    w.clear()
            except Exception:
                pass

    def action_focus_cmd(self) -> None:
        try:
            self.query_one("#cmd-input", Input).focus()
        except Exception:
            pass

    async def action_palette(self) -> None:
        result = await self.push_screen_wait(CommandPalette())
        if result:
            await self._exec_cmd(str(result))

    async def action_quit(self) -> None:
        for t in self._poll_tasks + [self._index_poll_task]:
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
