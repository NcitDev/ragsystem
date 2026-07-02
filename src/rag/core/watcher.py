"""File watcher that polls for changes and triggers incremental re-indexing."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import structlog

from rag.config import get_settings
from rag.core.chunker import supported_extensions

logger = structlog.get_logger()


class FileWatcher:
    """Polls a repository directory for file changes and invokes a callback.

    Uses mtime comparison instead of OS-level file watchers to avoid
    external dependencies.  The callback receives a list of changed file
    paths (relative to *repo_path*).
    """

    def __init__(
        self,
        repo_path: str,
        on_change: Callable[[list[str]], Any] | Callable[[list[str]], Coroutine[Any, Any, Any]],
        poll_interval: float = 30,
    ) -> None:
        self._repo_path = Path(repo_path).resolve()
        self._on_change = on_change
        self._poll_interval = poll_interval
        self._mtimes: dict[str, float] = {}
        self._task: asyncio.Task[None] | None = None
        self._running = False
        # Single-flight callback dispatch: changes accumulate into a dirty set
        # and are drained by at most one in-flight callback. A slow callback
        # (e.g. a long re-index) never blocks the poll loop, and changes that
        # arrive while it runs are coalesced into the next drain instead of
        # spawning a second concurrent callback.
        self._dirty: set[str] = set()
        self._dispatch_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the polling loop."""
        if self._running:
            logger.warning("watcher_already_running", repo=str(self._repo_path))
            return

        self._running = True
        # Capture the initial state so the first tick only reports *new*
        # changes, not every file in the repo. The scan walks the whole tree —
        # keep it off the event loop.
        self._mtimes = await asyncio.to_thread(self._scan)
        logger.info(
            "watcher_started",
            repo=str(self._repo_path),
            poll_interval=self._poll_interval,
            tracked_files=len(self._mtimes),
        )
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        """Stop the polling loop."""
        if not self._running:
            return

        self._running = False
        for attr in ("_task", "_dispatch_task"):
            task = getattr(self, attr)
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                setattr(self, attr, None)
        logger.info("watcher_stopped", repo=str(self._repo_path))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _scan(self) -> dict[str, float]:
        """Scan the repository for file mtimes, respecting skip_dirs and extensions."""
        settings = get_settings()
        skip_dirs = set(settings.index.skip_dirs)
        extensions = set(supported_extensions())
        mtimes: dict[str, float] = {}

        for ext in extensions:
            for file_path in self._repo_path.rglob(f"*{ext}"):
                # Skip files under directories that should be ignored.
                if any(part in skip_dirs for part in file_path.relative_to(self._repo_path).parts):
                    continue
                rel = str(file_path.relative_to(self._repo_path))
                try:
                    mtimes[rel] = file_path.stat().st_mtime
                except OSError:
                    # File may have been deleted between rglob and stat.
                    continue

        return mtimes

    async def _poll_loop(self) -> None:
        """Run until stopped, sleeping *poll_interval* seconds between scans."""
        while self._running:
            try:
                await asyncio.sleep(self._poll_interval)
                if not self._running:
                    break
                await self._check_changes()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("watcher_poll_error", repo=str(self._repo_path))

    async def _check_changes(self) -> None:
        """Compare current mtimes against the cached state and fire callback."""
        current = await asyncio.to_thread(self._scan)
        changed: list[str] = []

        # Detect new or modified files.
        for rel_path, mtime in current.items():
            prev = self._mtimes.get(rel_path)
            if prev is None or mtime != prev:
                changed.append(rel_path)

        # Detect deleted files.
        for rel_path in self._mtimes:
            if rel_path not in current:
                changed.append(rel_path)

        self._mtimes = current

        if not changed:
            return

        logger.info(
            "watcher_changes_detected",
            repo=str(self._repo_path),
            changed_files=len(changed),
            sample=changed[:5],
        )

        # Accumulate into the dirty set and ensure a dispatcher is running.
        # Never block the poll loop on the callback.
        self._dirty.update(changed)
        self._ensure_dispatch()

    def _ensure_dispatch(self) -> None:
        """Start the single-flight dispatch worker if it isn't already running."""
        if self._dispatch_task is not None and not self._dispatch_task.done():
            return
        self._dispatch_task = asyncio.create_task(self._dispatch_loop())

    async def _dispatch_loop(self) -> None:
        """Drain the dirty set, one callback at a time, until it's empty.

        Changes that arrive mid-callback are picked up on the next drain, so
        rapid bursts collapse into a small number of callbacks rather than one
        per poll tick — and two callbacks never run concurrently.
        """
        while self._running and self._dirty:
            batch = sorted(self._dirty)
            self._dirty.clear()
            try:
                result = self._on_change(batch)
                if asyncio.iscoroutine(result) or asyncio.isfuture(result):
                    await result
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "watcher_callback_error",
                    repo=str(self._repo_path),
                    changed_files=len(batch),
                )
                # Failed changes must not be silently dropped (e.g. the callback
                # hit an IndexLockError because a manual run holds the lock).
                # Re-queue the batch and retry after a poll interval.
                self._dirty.update(batch)
                await asyncio.sleep(self._poll_interval)
