"""Job runner: jobs table + one background worker thread inside the server process.

Phase 1 keeps this deliberately simple (see DECISIONS.md): jobs run one at a time
in a daemon thread. Phase 3+ will move AI jobs to a separate worker process that
claims rows from the same table.
"""
from __future__ import annotations

import json
import logging
import threading
import traceback

from ..database import get_db, utcnow
from ..utils.logging_setup import scan_logger
from . import scanner, thumbnails

log = logging.getLogger(__name__)
_run_lock = threading.Lock()

# job types the in-process web thread will run itself (cheap, no GPU model loading)
INPROC_TYPES = {"scan_source", "thumbnails"}
# job types that require the separate GPU worker process (python -m photoindex worker)
WORKER_TYPES = {"caption_batch", "face_batch", "cluster_faces"}


def create_job(job_type: str, payload: dict | None = None) -> int:
    db = get_db()
    cur = db.execute(
        "INSERT INTO jobs (job_type, status, payload_json, created_at) VALUES (?,?,?,?)",
        (job_type, "pending", json.dumps(payload or {}), utcnow()))
    db.commit()
    return cur.lastrowid


def _set(job_id: int, **fields) -> None:
    """Update job row; retry on transient lock (two processes share the DB)."""
    import sqlite3
    import time
    db = get_db()
    cols = ", ".join(f"{k}=?" for k in fields)
    for attempt in range(5):
        try:
            db.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))
            db.commit()
            return
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower() or attempt == 4:
                raise
            time.sleep(1 + attempt)


def _execute(job_id: int) -> None:
    db = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    payload = json.loads(job["payload_json"] or "{}")
    _set(job_id, status="running", started_at=utcnow())
    progress = lambda msg: _set(job_id, progress=msg)
    try:
        jt = job["job_type"]
        if jt == "scan_source":
            slog = scan_logger(job_id)
            result = scanner.scan_source(payload["source_id"], log_to=slog,
                                         progress_cb=progress)
        elif jt == "thumbnails":
            result = thumbnails.generate_missing(
                retry_failed=payload.get("retry_failed", False), progress_cb=progress)
        elif jt == "caption_batch":
            from . import analysis
            result = analysis.process_captions(
                limit=payload.get("limit"), retry_failed=payload.get("retry_failed", False),
                progress_cb=progress)
        elif jt == "face_batch":
            from . import analysis
            result = analysis.process_faces(
                limit=payload.get("limit"), retry_failed=payload.get("retry_failed", False),
                progress_cb=progress)
        elif jt == "cluster_faces":
            from ..ai import clustering
            result = clustering.cluster_all()
        else:
            raise ValueError(f"unknown job_type {jt}")
        _set(job_id, status="done", finished_at=utcnow(),
             progress=json.dumps(result))
    except Exception as e:
        log.error("job %s failed: %s\n%s", job_id, e, traceback.format_exc())
        _set(job_id, status="failed", finished_at=utcnow(),
             error_message=f"{type(e).__name__}: {e}")


def run_job_async(job_id: int) -> None:
    """Run in background thread; jobs serialize on _run_lock."""
    def target():
        with _run_lock:
            _execute(job_id)
    threading.Thread(target=target, daemon=True, name=f"job-{job_id}").start()


def run_job_sync(job_id: int) -> None:
    with _run_lock:
        _execute(job_id)


def enqueue(job_type: str, payload: dict | None = None, dedupe: bool = True) -> int:
    """Create a pending job. If dedupe, reuse an existing pending job of the same type."""
    db = get_db()
    if dedupe:
        row = db.execute(
            "SELECT id FROM jobs WHERE job_type=? AND status IN ('pending','running')",
            (job_type,)).fetchone()
        if row:
            return row["id"]
    return create_job(job_type, payload)


def claim_next_worker_job() -> int | None:
    """Atomically claim the oldest pending worker-type job. Returns job id or None."""
    db = get_db()
    placeholders = ",".join("?" * len(WORKER_TYPES))
    row = db.execute(
        f"SELECT id FROM jobs WHERE status='pending' AND job_type IN ({placeholders})"
        " ORDER BY id LIMIT 1", tuple(WORKER_TYPES)).fetchone()
    if not row:
        return None
    cur = db.execute(
        "UPDATE jobs SET status='running', started_at=? WHERE id=? AND status='pending'",
        (utcnow(), row["id"]))
    db.commit()
    if cur.rowcount == 0:
        return None  # another worker grabbed it
    return row["id"]


def execute_claimed(job_id: int) -> None:
    """Run a job already marked running (used by the worker process)."""
    _execute(job_id)
