"""Start/stop/status for the AI worker process, used by the web UI.

The worker writes data/worker.pid while alive (see workers/worker.py). Status = that PID
is a live process. Start spawns `<venv python> -m photoindex worker` detached, logging to
data/logs/worker.log. Stop kills the PID (tree-kill on Windows).
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from .. import config
from ..database import get_db

log = logging.getLogger(__name__)

PID_FILE = config.PROJECT_ROOT / "data" / "worker.pid"
BACKEND_DIR = Path(__file__).resolve().parents[2]  # .../backend


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        h = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return bool(ok) and code.value == STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_pid() -> int | None:
    try:
        return int(PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return None


def status() -> dict:
    pid = _read_pid()
    running = pid is not None and _pid_alive(pid)
    if not running and pid is not None:
        # stale pid file from a crashed worker — clean it up
        PID_FILE.unlink(missing_ok=True)
        pid = None
    db = get_db()
    current = db.execute(
        "SELECT id, job_type, progress FROM jobs WHERE status='running' ORDER BY id DESC"
        " LIMIT 1").fetchone()
    pending = db.execute(
        "SELECT COUNT(*) c FROM jobs WHERE status='pending'").fetchone()["c"]
    return {
        "running": running,
        "pid": pid if running else None,
        "current_job": dict(current) if current else None,
        "pending_jobs": pending,
    }


def start() -> dict:
    st = status()
    if st["running"]:
        return {"started": False, "already_running": True, "pid": st["pid"]}
    config.ensure_dirs()
    logf = open(config.LOG_DIR / "worker.log", "a", encoding="utf-8", errors="replace")
    kwargs: dict = {"cwd": str(BACKEND_DIR), "stdout": logf, "stderr": logf,
                    "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = (subprocess.CREATE_NO_WINDOW
                                   | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen([sys.executable, "-m", "photoindex", "worker"], **kwargs)
    log.info("spawned worker pid %s", proc.pid)
    return {"started": True, "pid": proc.pid,
            "note": "worker logs to data/logs/worker.log"}


def stop() -> dict:
    pid = _read_pid()
    if pid is None or not _pid_alive(pid):
        PID_FILE.unlink(missing_ok=True)
        return {"stopped": False, "was_running": False}
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True)
    else:
        import signal
        os.kill(pid, signal.SIGTERM)
    PID_FILE.unlink(missing_ok=True)
    # a job left 'running' by the kill stays resumable: reset it to pending
    db = get_db()
    db.execute("UPDATE jobs SET status='pending', started_at=NULL WHERE status='running'")
    db.commit()
    log.info("stopped worker pid %s", pid)
    return {"stopped": True, "pid": pid}
