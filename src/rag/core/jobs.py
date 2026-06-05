"""Persistent local job ledger for daemon-managed background work."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import structlog

from rag.config import RAG_HOME

logger = structlog.get_logger()

JOBS_DIR = RAG_HOME / "jobs"
ACTIVE_STATUSES = {"queued", "scanning", "running"}


def _job_path(job_id: str) -> Path:
    safe = "".join(ch for ch in job_id if ch.isalnum() or ch in {"-", "_"})
    return JOBS_DIR / f"{safe}.json"


def save_job(job_id: str, job: dict[str, Any]) -> None:
    """Persist a job atomically as JSON."""
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    data = dict(job)
    data["job_id"] = job_id
    data["updated_at"] = time.time()
    path = _job_path(job_id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def load_jobs(mark_active_interrupted: bool = True) -> dict[str, dict[str, Any]]:
    """Load persisted jobs, marking old active runs interrupted after restart."""
    if not JOBS_DIR.exists():
        return {}

    jobs: dict[str, dict[str, Any]] = {}
    for path in sorted(JOBS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            job_id = str(data.get("job_id") or path.stem)
            if mark_active_interrupted and data.get("status") in ACTIVE_STATUSES:
                data["status"] = "interrupted"
                data["finished_at"] = data.get("finished_at") or time.time()
                data["error"] = "Daemon restarted while this job was active."
                save_job(job_id, data)
            jobs[job_id] = data
        except Exception as e:
            logger.warning("job_load_failed", path=str(path), error=str(e))
    return jobs


def prune_jobs(max_jobs: int = 200) -> None:
    """Keep the newest job files and remove older completed history."""
    if not JOBS_DIR.exists():
        return
    paths = sorted(JOBS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
    for path in paths[:-max_jobs]:
        try:
            path.unlink()
        except Exception as e:
            logger.debug("job_prune_failed", path=str(path), error=str(e))
