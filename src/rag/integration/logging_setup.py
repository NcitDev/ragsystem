"""Centralized logging configuration with size-based rotation.

launchd (and most simple supervisors) redirect a process's stdout/stderr to a
fixed file and never rotate it — a long-running daemon will fill the disk. We
avoid that by routing structlog through the stdlib ``logging`` module with a
``RotatingFileHandler`` writing to ``~/.rag/logs/daemon.jsonl``. The launchd
plist's StandardErrorPath still captures unexpected crashes/tracebacks (a small,
slow-growing file), but normal request/index logging goes through the rotated
handler.

Call ``configure_logging()`` once, early, in the daemon entrypoint.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import structlog

from rag.config import RAG_HOME

# 10 MB per file, keep 5 -> ~50 MB ceiling for the structured log.
_MAX_BYTES = 10 * 1024 * 1024
_BACKUP_COUNT = 5

_configured = False


def _logs_dir() -> Path:
    d = RAG_HOME / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def configure_logging(to_file: bool = True, level: int = logging.INFO) -> Path | None:
    """Configure structlog + stdlib logging with rotation.

    Args:
        to_file: write rotated JSON logs to ~/.rag/logs/daemon.jsonl. When
            False (e.g. CLI one-shots, tests), logs go to stderr only.
        level: stdlib log level threshold.

    Returns the log file path when file logging is enabled, else None.
    Idempotent — safe to call more than once.
    """
    global _configured

    timestamper = structlog.processors.TimeStamper(fmt="iso")
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    # Route structlog records into stdlib logging so the rotating handler
    # (and any future handlers) own output + rotation.
    structlog.configure(
        processors=shared_processors
        + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )

    root = logging.getLogger()
    # Drop handlers from a prior call so repeated invocations don't stack.
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(level)

    json_formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )

    log_path: Path | None = None
    if to_file:
        log_path = _logs_dir() / "daemon.jsonl"
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(json_formatter)
        root.addHandler(file_handler)

    # Always keep a stderr handler too (captured by launchd for crashes, and
    # the only sink when to_file is False).
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(json_formatter)
    root.addHandler(stderr_handler)

    # uvicorn/fastapi use stdlib logging — let their records flow through the
    # same handlers instead of uvicorn's own config.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True

    _configured = True
    return log_path
