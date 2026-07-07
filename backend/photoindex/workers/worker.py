"""GPU worker process: python -m photoindex worker

Polls the jobs table for AI jobs (caption_batch, face_batch, cluster_faces), runs them
one at a time, and loops. Runs in its OWN process so heavy models never load into the web
server. Safe to Ctrl+C; a killed job is left 'running' and can be reset (see --reset-stuck).

Writes data/worker.pid while alive (touched every poll) so the web UI can show worker
status and start/stop it — see services/worker_control.py.
"""
from __future__ import annotations

import logging
import os
import time

from .. import config
from ..database import init_db
from ..services import runner

log = logging.getLogger("photoindex.worker")

PID_FILE = config.PROJECT_ROOT / "data" / "worker.pid"


def run(poll_seconds: float = 3.0, once: bool = False) -> None:
    init_db()
    # Self-heal: a previous worker that was killed mid-job leaves that job stuck in
    # 'running' forever. Only one worker runs at a time by design, so any 'running'
    # worker-type job at OUR startup is orphaned — reset it to pending. (Batches are
    # resumable: per-file *_status columns mean finished files aren't redone.)
    from ..database import get_db
    db = get_db()
    placeholders = ",".join("?" * len(runner.WORKER_TYPES))
    orphans = db.execute(
        f"UPDATE jobs SET status='pending', started_at=NULL WHERE status='running'"
        f" AND job_type IN ({placeholders})", tuple(runner.WORKER_TYPES)).rowcount
    db.commit()
    if orphans:
        log.info("reset %s orphaned running job(s) to pending", orphans)
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    log.info("worker started (pid %s); polling every %.1fs (types=%s)", os.getpid(),
             poll_seconds, sorted(runner.WORKER_TYPES))
    idle_logged = False
    try:
        while True:
            PID_FILE.touch()
            job_id = runner.claim_next_worker_job()
            if job_id is None:
                if once:
                    log.info("no pending jobs; --once so exiting")
                    return
                if not idle_logged:
                    log.info("idle; waiting for jobs")
                    idle_logged = True
                time.sleep(poll_seconds)
                continue
            idle_logged = False
            log.info("running job %s", job_id)
            runner.execute_claimed(job_id)
            if once:
                return
    finally:
        try:
            PID_FILE.unlink(missing_ok=True)
        except OSError:
            pass
