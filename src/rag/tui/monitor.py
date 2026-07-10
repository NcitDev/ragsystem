"""Stack monitor — collects the health of every RAG dependency into one snapshot.

The TUI renders exclusively from :class:`StackSnapshot`; no widget talks to the
network itself. Each check is independently timeboxed and failure-isolated so
the dashboard stays useful when parts of the stack (daemon, Ollama, Docker,
Qdrant) are down — that is precisely when you need it most.

Daemon state comes over HTTP (same as the CLI). Ollama, Docker and Qdrant are
probed directly, mirroring how ``rag diagnose`` works, because the daemon
being down must not blind the dashboard.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import structlog

from rag.config import RAG_HOME, get_or_create_token, get_settings

logger = structlog.get_logger()

# Service states
OK = "ok"          # fully working
WARN = "warn"      # reachable but degraded / something missing
DOWN = "down"      # expected but not reachable
OFF = "off"        # not applicable / not installed

QDRANT_CONTAINER = "rag-qdrant"


@dataclass
class ServiceHealth:
    """One service card on the dashboard."""

    name: str
    state: str = DOWN
    headline: str = ""            # short status line, e.g. "running · up 3h 12m"
    lines: list[str] = field(default_factory=list)   # detail lines
    hint: str = ""                # how to fix, shown when state != OK


@dataclass
class RepoIndex:
    """One indexed project (or default collection)."""

    name: str
    path: str = ""
    collection: str = ""
    points: int = 0
    files: int = 0
    last_indexed: str = ""        # humanized, e.g. "2d ago"
    status: str = ""              # qdrant collection status or "not_found"
    kind: str = "repo"            # "repo" | "default"


@dataclass
class StackSnapshot:
    """Everything the dashboard renders, gathered in one pass."""

    ts: float = 0.0
    daemon_up: bool = False
    daemon: ServiceHealth = field(default_factory=lambda: ServiceHealth("DAEMON"))
    ollama: ServiceHealth = field(default_factory=lambda: ServiceHealth("OLLAMA"))
    docker: ServiceHealth = field(default_factory=lambda: ServiceHealth("DOCKER"))
    qdrant: ServiceHealth = field(default_factory=lambda: ServiceHealth("QDRANT"))
    repos: list[RepoIndex] = field(default_factory=list)
    repos_source: str = "daemon"  # "daemon" | "local"
    lsp: list[Any] = field(default_factory=list)       # LSPServerStatus
    stats: dict[str, Any] = field(default_factory=dict)
    queries: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    jobs: dict[str, Any] = field(default_factory=dict)
    service: dict[str, Any] = field(default_factory=dict)  # launchd agent info


def humanize_seconds(seconds: float) -> str:
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def humanize_ago(iso_or_epoch: Any) -> str:
    """'2d ago' from an ISO string or epoch float; '' when unparseable."""
    if iso_or_epoch in (None, ""):
        return ""
    try:
        if isinstance(iso_or_epoch, (int, float)):
            then = float(iso_or_epoch)
        else:
            dt = datetime.fromisoformat(str(iso_or_epoch).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            then = dt.timestamp()
        delta = time.time() - then
        if delta < 0:
            return "just now"
        if delta < 90:
            return "just now"
        if delta < 3600:
            return f"{int(delta // 60)}m ago"
        if delta < 86400:
            return f"{int(delta // 3600)}h ago"
        return f"{int(delta // 86400)}d ago"
    except Exception:
        return ""


def humanize_bytes(n: Any) -> str:
    try:
        size = float(n)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f}{unit}" if unit in ("B", "KB") else f"{size:.1f}{unit}"
        size /= 1024
    return ""


def _last_daemon_error(max_scan: int = 200) -> str:
    """Last error event from ~/.rag/logs/daemon.jsonl — why the daemon died.

    Only reported when the log was written within the last day, so a
    months-old crash doesn't haunt the dashboard.
    """
    log_path = RAG_HOME / "logs" / "daemon.jsonl"
    try:
        if not log_path.exists() or time.time() - log_path.stat().st_mtime > 86400:
            return ""
        lines = log_path.read_text(errors="replace").splitlines()[-max_scan:]
        errors: list[dict] = []
        for line in reversed(lines):
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if entry.get("level") == "error":
                errors.append(entry)
        if not errors:
            return ""
        # The newest error is often a generic "startup failed"; prefer the
        # nearest entry that carries the actual reason in its "error" field.
        entry = next((e for e in errors[:6] if e.get("error")), errors[0])
        msg = " ".join(str(entry.get("error") or entry.get("event") or "").split())
        if msg:
            when = humanize_ago(entry.get("timestamp"))
            suffix = f" ({when})" if when else ""
            return f"crash: {msg[:110]}{suffix}"
    except Exception:
        pass
    return ""


def _repo_state_files(path: str) -> int:
    """Count of indexed files from ~/.rag/repos/<sha>/state.json for a repo path."""
    try:
        abs_str = str(Path(path).expanduser().resolve())
        digest = hashlib.sha256(abs_str.encode("utf-8")).hexdigest()[:16]
        state = RAG_HOME / "repos" / digest / "state.json"
        if state.exists():
            data = json.loads(state.read_text())
            return len(data.get("file_hashes", {}) or {})
    except Exception:
        pass
    return 0


class StackMonitor:
    """Gathers stack health; also carries the daemon HTTP client for actions."""

    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = f"http://{settings.server.host}:{settings.server.port}"
        self.ollama_url = settings.llm.ollama_url
        self.qdrant_url = settings.qdrant.url
        self.qdrant_mode = settings.qdrant.mode
        self._settings = settings
        self._headers = {"Authorization": f"Bearer {get_or_create_token()}"}
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(3.0, connect=2.0))

    async def close(self) -> None:
        try:
            await self._client.aclose()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Daemon HTTP (shared by checks and by Search/Ask/Index screens)
    # ------------------------------------------------------------------

    async def daemon_get(self, path: str, *, timeout: float = 3.0) -> Any | None:
        try:
            resp = await self._client.get(
                f"{self.base_url}{path}", headers=self._headers, timeout=timeout
            )
            if resp.status_code == 200:
                return resp.json()
            logger.debug("tui_daemon_get_non_200", path=path, status=resp.status_code)
        except Exception as e:
            logger.debug("tui_daemon_get_error", path=path, error=str(e))
        return None

    async def daemon_post(
        self, path: str, payload: dict, *, timeout: float = 300.0
    ) -> tuple[bool, Any]:
        """Returns (ok, json_or_error_message)."""
        try:
            resp = await self._client.post(
                f"{self.base_url}{path}",
                json=payload,
                headers=self._headers,
                timeout=timeout,
            )
            if resp.status_code == 200:
                return True, resp.json()
            detail = ""
            try:
                detail = (resp.json() or {}).get("detail") or (resp.json() or {}).get("error") or ""
            except Exception:
                detail = resp.text[:200]
            return False, f"HTTP {resp.status_code}: {detail}"
        except httpx.ConnectError:
            return False, "daemon not reachable — start it with: rag start"
        except Exception as e:
            return False, str(e)

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    async def snapshot(self, *, fast_only: bool = False) -> StackSnapshot:
        """Collect a full stack snapshot. Never raises.

        ``fast_only`` limits the pass to daemon-side data (health, activity,
        jobs) for the high-frequency poll; the expensive external probes
        (Docker CLI, Ollama tags, LSP which-scan) run on the slow cadence.
        """
        snap = StackSnapshot(ts=time.time())

        daemon_task = asyncio.create_task(self._check_daemon(snap))
        activity_task = asyncio.create_task(self._collect_activity(snap))
        tasks = [daemon_task, activity_task]
        if not fast_only:
            tasks.append(asyncio.create_task(self.external_checks(snap)))
        await asyncio.gather(*tasks, return_exceptions=True)
        # Repos need to know whether the daemon answered, so run after.
        try:
            await self._collect_repos(snap)
        except Exception as e:
            logger.debug("tui_repos_collect_error", error=str(e))
        return snap

    async def external_checks(self, snap: StackSnapshot | None = None) -> StackSnapshot:
        """The probes that don't need daemon HTTP: Ollama, Docker, Qdrant,
        LSP which-scan, launchd. Also serves the daemon's ``/stack`` route,
        where the daemon is by definition up and self-probing over HTTP
        would be wasteful."""
        if snap is None:
            snap = StackSnapshot(ts=time.time())
        await asyncio.gather(
            self._check_ollama(snap),
            self._check_docker(snap),
            self._check_qdrant(snap),
            self._collect_lsp(snap),
            self._collect_service(snap),
            return_exceptions=True,
        )
        return snap

    # ------------------------------------------------------------------
    # Individual checks — each fully failure-isolated
    # ------------------------------------------------------------------

    async def _check_daemon(self, snap: StackSnapshot) -> None:
        svc = snap.daemon
        svc.hint = "press D to start · or: rag start"
        try:
            resp = await self._client.get(f"{self.base_url}/health")
            health = resp.json() if resp.status_code == 200 else {}
        except Exception:
            svc.state = DOWN
            svc.headline = "not running"
            svc.lines = [self.base_url]
            crash = await asyncio.to_thread(_last_daemon_error)
            if crash:
                svc.lines.append(crash)
            return

        snap.daemon_up = True
        components = health.get("components", {}) or {}
        degraded = health.get("status") != "ok"
        svc.state = WARN if degraded else OK
        svc.lines = [self.base_url]

        status = await self.daemon_get("/status")
        if status:
            up = humanize_seconds(status.get("uptime_seconds", 0) or 0)
            restarts = int(status.get("restart_count", 0) or 0)
            svc.headline = f"running · up {up}"
            svc.lines.append(
                "no restarts" if restarts == 0 else f"{restarts} restart{'s' if restarts > 1 else ''}"
            )
            files = int(status.get("files_indexed", 0) or 0)
            if files:
                svc.lines.append(f"{files:,} files indexed")
            snap.stats["_status"] = status  # raw, for repos + models panel
        else:
            svc.headline = "running (auth failed on /status)" if not degraded else "degraded"

        comp_bits = []
        for comp in ("qdrant", "embedder", "ollama"):
            val = str(components.get(comp, "?"))
            comp_bits.append(f"{comp}:{val}")
            if comp == "qdrant" and val != "ok":
                svc.state = WARN
                svc.hint = "qdrant component failing — press U to start Qdrant"
        svc.lines.append("  ".join(comp_bits))
        if svc.state == OK:
            svc.hint = ""

    async def _check_ollama(self, snap: StackSnapshot) -> None:
        svc = snap.ollama
        svc.hint = "run: ollama serve"
        try:
            v = await self._client.get(f"{self.ollama_url}/api/version")
            version = v.json().get("version", "?") if v.status_code == 200 else "?"
        except Exception:
            svc.state = DOWN
            svc.headline = "not running"
            svc.lines = [self.ollama_url]
            return

        svc.state = OK
        svc.headline = f"running · v{version}"
        models: list[str] = []
        try:
            tags = await self._client.get(f"{self.ollama_url}/api/tags")
            if tags.status_code == 200:
                models = [m.get("name", "") for m in tags.json().get("models", [])]
        except Exception:
            pass

        embed_model = self._settings.embeddings.model.split("/")[-1].lower()
        agent_model = self._settings.llm.agent_model
        has_embed = any(embed_model in m.lower() for m in models)
        has_agent = any(agent_model in m for m in models)
        svc.lines = [f"{len(models)} models installed"]
        svc.lines.append(f"embedder {'✓' if has_embed else '✗ missing'}")
        svc.lines.append(f"agent {agent_model} {'✓' if has_agent else '✗ missing'}")
        if not has_embed:
            svc.state = WARN
            svc.hint = (
                f"ollama pull {self._settings.embeddings.model} — or point "
                "[embeddings].model in ~/.rag/config.toml at an installed tag"
            )
        elif svc.state == OK:
            svc.hint = ""

        # Loaded (resident) models with VRAM
        try:
            ps = await self._client.get(f"{self.ollama_url}/api/ps")
            if ps.status_code == 200:
                loaded = ps.json().get("models", []) or []
                if loaded:
                    for m in loaded[:3]:
                        vram = humanize_bytes(m.get("size_vram") or m.get("size"))
                        svc.lines.append(f"loaded: {m.get('name', '?')} {vram}")
                else:
                    svc.lines.append("loaded: none (cold)")
        except Exception:
            pass

    async def _check_docker(self, snap: StackSnapshot) -> None:
        svc = snap.docker
        if shutil.which("docker") is None:
            svc.state = OFF
            svc.headline = "docker CLI not installed"
            svc.hint = "install Docker Desktop (needed for Qdrant server mode)"
            return
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "ps", "-a", "--format", "{{.Names}}\t{{.State}}\t{{.Status}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        except Exception:
            svc.state = DOWN
            svc.headline = "docker not responding"
            svc.hint = "start Docker Desktop"
            return
        if proc.returncode != 0:
            svc.state = DOWN
            svc.headline = "docker daemon not running"
            svc.lines = [err.decode(errors="replace").strip().splitlines()[0][:60]] if err else []
            svc.hint = "start Docker Desktop"
            return

        svc.state = OK
        running = 0
        container_line = ""
        container_running = False
        for line in out.decode(errors="replace").splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            name, state, status = parts[0], parts[1], parts[2]
            if state == "running":
                running += 1
            if name == QDRANT_CONTAINER:
                container_running = state == "running"
                container_line = f"{QDRANT_CONTAINER}: {status}"
        svc.headline = f"running · {running} container{'s' if running != 1 else ''} up"
        if container_line:
            svc.lines = [container_line]
            if not container_running and self.qdrant_mode == "server":
                svc.state = WARN
                svc.hint = "press U to start the Qdrant container"
        elif self.qdrant_mode == "server":
            svc.lines = [f"{QDRANT_CONTAINER}: not created"]
            svc.state = WARN
            svc.hint = "press U (runs docker compose up for Qdrant)"

    async def _check_qdrant(self, snap: StackSnapshot) -> None:
        svc = snap.qdrant
        if self.qdrant_mode != "server":
            svc.state = OK
            svc.headline = "embedded mode"
            svc.lines = [str(self._settings.qdrant.resolved_path)]
            svc.hint = ""
            return
        try:
            root = await self._client.get(f"{self.qdrant_url}/")
            version = (root.json() or {}).get("version", "?") if root.status_code == 200 else "?"
        except Exception:
            svc.state = DOWN
            svc.headline = "not reachable"
            svc.lines = [self.qdrant_url]
            svc.hint = "press U to start · or: rag qdrant-up"
            return

        svc.state = OK
        svc.headline = f"running · v{version}"
        svc.lines = [self.qdrant_url]
        try:
            cols = await self._client.get(f"{self.qdrant_url}/collections")
            if cols.status_code == 200:
                names = [
                    c.get("name", "")
                    for c in (cols.json().get("result", {}) or {}).get("collections", [])
                ]
                svc.lines.append(f"{len(names)} collections")
        except Exception:
            pass

    async def _collect_activity(self, snap: StackSnapshot) -> None:
        results = await asyncio.gather(
            self.daemon_get("/queries/stats?window=100"),
            self.daemon_get("/queries/recent?limit=100"),
            self.daemon_get("/events/recent?limit=300"),
            self.daemon_get("/index/jobs"),
            return_exceptions=True,
        )
        stats, recent, events, jobs = (
            r if not isinstance(r, BaseException) else None for r in results
        )
        if stats:
            snap.stats.update(stats)
        if recent:
            snap.queries = recent.get("queries", []) or []
        if events:
            snap.events = events.get("events", []) or []
        if jobs:
            snap.jobs = jobs.get("jobs", {}) or {}

    async def _collect_repos(self, snap: StackSnapshot) -> None:
        """Project indexes: daemon /status when up, local registry otherwise."""
        collections: list[dict] = []
        status = snap.stats.get("_status")
        if snap.daemon_up and status:
            collections = status.get("collections", []) or []
        elif snap.daemon_up:
            data = await self.daemon_get("/collections")
            collections = (data or {}).get("collections", []) or []

        if collections:
            snap.repos_source = "daemon"
            # /status doesn't carry last_indexed — enrich from the local registry.
            last_indexed = await asyncio.to_thread(self._local_last_indexed)
            for c in collections:
                name = c.get("repo") or c.get("name", "?")
                path = c.get("path", "")
                repo = RepoIndex(
                    name=name,
                    path=path,
                    collection=c.get("name", ""),
                    points=int(c.get("points_count", 0) or 0),
                    status=str(c.get("status", "")),
                    kind=c.get("kind", "repo"),
                    last_indexed=humanize_ago(last_indexed.get(c.get("repo", ""))),
                )
                if path:
                    repo.files = await asyncio.to_thread(_repo_state_files, path)
                snap.repos.append(repo)
            return

        # Daemon down (or gave nothing): read the local registry read-only.
        snap.repos_source = "local"

        def _local() -> list[RepoIndex]:
            out: list[RepoIndex] = []
            try:
                from rag.core.repos import RepoManager

                for r in RepoManager().list_repos():
                    out.append(
                        RepoIndex(
                            name=r.name,
                            path=r.path,
                            collection=r.collection,
                            points=int(r.chunks_count or 0),
                            files=_repo_state_files(r.path),
                            last_indexed=humanize_ago(r.last_indexed),
                            kind="repo",
                        )
                    )
            except Exception as e:
                logger.debug("tui_local_repos_error", error=str(e))
            return out

        snap.repos = await asyncio.to_thread(_local)

    @staticmethod
    def _local_last_indexed() -> dict[str, Any]:
        try:
            from rag.core.repos import RepoManager

            return {r.name: r.last_indexed for r in RepoManager().list_repos()}
        except Exception:
            return {}

    async def _collect_lsp(self, snap: StackSnapshot) -> None:
        def _detect() -> list[Any]:
            try:
                from rag.core.lsp import detect_lsp_servers

                return detect_lsp_servers()
            except Exception:
                return []

        snap.lsp = await asyncio.to_thread(_detect)

    async def _collect_service(self, snap: StackSnapshot) -> None:
        if platform.system() != "Darwin":
            return

        def _status() -> dict:
            try:
                from rag.integration.supervisor import service_status

                return service_status()
            except Exception:
                return {}

        snap.service = await asyncio.to_thread(_status)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def spawn_daemon(self) -> str:
        """Start the daemon in the background (same as ``rag start --tui`` does)."""
        try:
            subprocess.Popen(
                [sys.executable, "-m", "rag", "start"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return "daemon starting — watch the DAEMON card"
        except Exception as e:
            return f"failed to spawn daemon: {e}"

    async def start_qdrant(self) -> str:
        """Start the Qdrant container: docker start if it exists, compose up otherwise."""
        if shutil.which("docker") is None:
            return "docker CLI not found — install Docker Desktop"
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "start", QDRANT_CONTAINER,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=20.0)
            if proc.returncode == 0:
                return f"{QDRANT_CONTAINER} starting"
        except asyncio.TimeoutError:
            return "docker start timed out"
        except Exception as e:
            return f"docker start failed: {e}"

        # Container doesn't exist yet — try compose (editable checkout only).
        compose = Path(__file__).resolve().parents[3] / "compose.qdrant.yml"
        if not compose.exists():
            return f"container missing and {compose.name} not found — run: rag qdrant-up"
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "compose", "-f", str(compose), "up", "-d",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, err = await asyncio.wait_for(proc.communicate(), timeout=60.0)
            if proc.returncode == 0:
                return "qdrant compose up — container starting"
            return f"compose failed: {err.decode(errors='replace').strip()[:120]}"
        except Exception as e:
            return f"compose failed: {e}"
