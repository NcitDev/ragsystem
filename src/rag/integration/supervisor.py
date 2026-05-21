"""OS-level service supervisor integration.

Generates a launchd plist on macOS that runs `python -m rag start` (the headless
daemon) under launchd's KeepAlive supervision. The TUI is no longer in-process,
so a TUI crash cannot take the daemon down.

systemd is intentionally not implemented here — Linux distros vary too much to
emit a one-size-fits-all unit file. We surface a clear message and a hint.
"""

from __future__ import annotations

import os
import platform
import plistlib
import subprocess
from pathlib import Path

LAUNCHD_LABEL = "com.rag.daemon"


def _is_macos() -> bool:
    return platform.system() == "Darwin"


def _require_macos() -> None:
    if not _is_macos():
        raise NotImplementedError(
            "Service mode currently macOS-only. "
            "On Linux, run `rag start` under systemd manually "
            "(see docs/ADR/001-full-stack-decision.md or your distro's "
            "systemd unit-file conventions)."
        )


def _plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def _logs_dir() -> Path:
    d = Path.home() / ".rag" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def build_plist(python_executable: str) -> dict:
    """Return the plist dict that will be written for launchd."""
    logs = _logs_dir()
    # Pull PATH from the current environment so launchd can find ollama, git, etc.
    # (launchd otherwise has a very minimal PATH.)
    env = {
        "PATH": os.environ.get(
            "PATH",
            "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        ),
        "HOME": str(Path.home()),
    }
    # Forward a couple of well-known knobs that affect Ollama / Python.
    for key in ("OLLAMA_HOST", "OLLAMA_MODELS", "PYTHONUNBUFFERED", "LANG", "LC_ALL"):
        if key in os.environ:
            env[key] = os.environ[key]

    return {
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": [python_executable, "-m", "rag", "start"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(logs / "daemon.log"),
        "StandardErrorPath": str(logs / "daemon.err"),
        "EnvironmentVariables": env,
        "ProcessType": "Background",
    }


def install_service(python_executable: str) -> dict:
    """Write the plist and load it via launchctl. Returns paths used."""
    _require_macos()

    plist_path = _plist_path()
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    logs = _logs_dir()

    data = build_plist(python_executable)

    # If a previous version is loaded, unload it first so launchctl picks up the new one.
    if plist_path.exists():
        subprocess.run(
            ["launchctl", "unload", "-w", str(plist_path)],
            check=False,
            capture_output=True,
        )

    with plist_path.open("wb") as fh:
        plistlib.dump(data, fh)

    result = subprocess.run(
        ["launchctl", "load", "-w", str(plist_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"launchctl load failed: {result.stderr.strip() or result.stdout.strip()}"
        )

    return {
        "plist_path": str(plist_path),
        "stdout_log": str(logs / "daemon.log"),
        "stderr_log": str(logs / "daemon.err"),
    }


def uninstall_service() -> str:
    """Unload the launchd agent and remove the plist. Returns the plist path."""
    _require_macos()

    plist_path = _plist_path()
    if plist_path.exists():
        subprocess.run(
            ["launchctl", "unload", "-w", str(plist_path)],
            check=False,
            capture_output=True,
        )
        plist_path.unlink()
    return str(plist_path)


def service_status() -> dict:
    """Return whether the launchd agent is installed and currently loaded."""
    _require_macos()

    plist_path = _plist_path()
    installed = plist_path.exists()

    loaded = False
    try:
        result = subprocess.run(
            ["launchctl", "list", LAUNCHD_LABEL],
            check=False,
            capture_output=True,
            text=True,
        )
        loaded = result.returncode == 0
    except FileNotFoundError:
        loaded = False

    return {
        "plist_path": str(plist_path),
        "installed": installed,
        "loaded": loaded,
    }
