from __future__ import annotations

from fastapi import APIRouter

from ..database import get_db
from ..services import runner

router = APIRouter(prefix="/api", tags=["jobs"])


@router.get("/jobs")
def list_jobs(limit: int = 50):
    db = get_db()
    rows = db.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?",
                      (min(limit, 500),)).fetchall()
    return [dict(r) for r in rows]


@router.post("/thumbnails/retry")
def retry_thumbnails():
    job_id = runner.create_job("thumbnails", {"retry_failed": True})
    runner.run_job_async(job_id)
    return {"job_id": job_id}


@router.get("/stats")
def stats():
    db = get_db()
    def one(sql, *p):
        return db.execute(sql, p).fetchone()[0]
    return {
        "sources": one("SELECT COUNT(*) FROM sources"),
        "files_active": one("SELECT COUNT(*) FROM files WHERE status='active'"),
        "files_missing": one("SELECT COUNT(*) FROM files WHERE status='missing'"),
        "thumbs_ok": one("SELECT COUNT(*) FROM files WHERE thumb_status='ok'"),
        "thumbs_failed": one("SELECT COUNT(*) FROM files WHERE thumb_status='failed'"),
        "jobs_running": one("SELECT COUNT(*) FROM jobs WHERE status='running'"),
        "jobs_pending": one("SELECT COUNT(*) FROM jobs WHERE status='pending'"),
        "jobs_failed": one("SELECT COUNT(*) FROM jobs WHERE status='failed'"),
        "total_bytes": one("SELECT COALESCE(SUM(file_size),0) FROM files WHERE status='active'"),
        "captions_pending": one("SELECT COUNT(*) FROM files WHERE status='active' AND caption_status='pending'"),
        "captions_ok": one("SELECT COUNT(*) FROM files WHERE caption_status='ok'"),
        "faces_pending": one("SELECT COUNT(*) FROM files WHERE status='active' AND face_status='pending'"),
        "faces_total": one("SELECT COUNT(*) FROM faces WHERE status='active'"),
        "people": one("SELECT COUNT(*) FROM people"),
        "clusters_review": one("SELECT COUNT(*) FROM face_clusters WHERE status='needs_review'"),
    }
