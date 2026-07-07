"""fotorganize FastAPI app. Run from backend/:

    uvicorn photoindex.main:app --host 127.0.0.1 --port 8420
or  python -m photoindex serve
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import config
from .database import init_db
from .routes import (analysis, exports, files, jobs, maintenance, people,
                     search, sources, worker)
from .utils.logging_setup import setup_logging

setup_logging()
log = logging.getLogger("photoindex")

app = FastAPI(title="fotorganize", version="0.1.0")


@app.on_event("startup")
def startup():
    config.ensure_dirs()
    init_db()
    # self-heal: in-process jobs (scan/thumbnails) that died with a previous server
    # would sit 'running' forever — reset them so they can be re-run
    from .database import get_db
    from .services.runner import INPROC_TYPES
    db = get_db()
    ph = ",".join("?" * len(INPROC_TYPES))
    n = db.execute(f"UPDATE jobs SET status='pending', started_at=NULL"
                   f" WHERE status='running' AND job_type IN ({ph})",
                   tuple(INPROC_TYPES)).rowcount
    db.commit()
    if n:
        log.info("reset %s orphaned in-process job(s) to pending", n)
    # resume any pending in-process jobs (batches skip already-finished files)
    from .services.runner import run_job_async
    pending = db.execute(
        f"SELECT id FROM jobs WHERE status='pending' AND job_type IN ({ph})"
        " ORDER BY id", tuple(INPROC_TYPES)).fetchall()
    for row in pending:
        log.info("resuming in-process job %s", row["id"])
        run_job_async(row["id"])
    if config.ALLOW_LAN:
        log.warning("ALLOW_LAN is enabled — the app is reachable from your whole "
                    "network. Private family photos are exposed to any LAN device.")
    log.info("fotorganize started; db=%s", config.DB_PATH)


@app.get("/api/health")
def health():
    return {"ok": True, "version": "0.1.0"}


app.include_router(sources.router)
app.include_router(files.router)
app.include_router(jobs.router)
app.include_router(analysis.router)
app.include_router(people.router)
app.include_router(search.router)
app.include_router(exports.router)
app.include_router(maintenance.router)
app.include_router(worker.router)

# frontend last so /api/* wins
app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
