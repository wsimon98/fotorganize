from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..database import get_db, utcnow
from ..services import runner
from ..utils.paths import classify_path, normalize_root

router = APIRouter(prefix="/api/sources", tags=["sources"])

VALID_STATUSES = {"active", "paused", "inactive", "missing"}


class SourceIn(BaseModel):
    name: str
    root_path: str


class StatusIn(BaseModel):
    status: str


@router.get("")
def list_sources():
    db = get_db()
    rows = db.execute(
        """SELECT s.*,
                  (SELECT COUNT(*) FROM files f WHERE f.source_id=s.id AND f.status='active') AS active_files,
                  (SELECT COUNT(*) FROM files f WHERE f.source_id=s.id AND f.status='missing') AS missing_files
           FROM sources s ORDER BY s.id""").fetchall()
    return [dict(r) for r in rows]


@router.post("")
def add_source(body: SourceIn):
    root = normalize_root(body.root_path)
    if not root:
        raise HTTPException(400, "empty path")
    db = get_db()
    # Reconnect rule: same normalized path (any status) reuses the existing row
    # so prior files/tags survive a remove-and-re-add. See DECISIONS.md.
    existing = db.execute("SELECT * FROM sources WHERE root_path=?", (root,)).fetchone()
    now = utcnow()
    if existing:
        db.execute("UPDATE sources SET name=?, status='active', updated_at=? WHERE id=?",
                   (body.name, now, existing["id"]))
        db.commit()
        return {"id": existing["id"], "reconnected": True}
    if not os.path.isdir(root):
        raise HTTPException(400, f"path not reachable right now: {root}")
    cur = db.execute(
        "INSERT INTO sources (name, root_path, path_type, status, created_at, updated_at)"
        " VALUES (?,?,?,'active',?,?)",
        (body.name, root, classify_path(root), now, now))
    db.commit()
    return {"id": cur.lastrowid, "reconnected": False}


@router.post("/{source_id}/status")
def set_status(source_id: int, body: StatusIn):
    if body.status not in VALID_STATUSES:
        raise HTTPException(400, f"status must be one of {sorted(VALID_STATUSES)}")
    db = get_db()
    if not db.execute("SELECT 1 FROM sources WHERE id=?", (source_id,)).fetchone():
        raise HTTPException(404, "source not found")
    db.execute("UPDATE sources SET status=?, updated_at=? WHERE id=?",
               (body.status, utcnow(), source_id))
    db.commit()
    return {"ok": True}


class DeleteIn(BaseModel):
    confirm: bool = False


@router.post("/{source_id}/delete")
def hard_delete(source_id: int, body: DeleteIn):
    """Permanently remove a source and ALL its DB records (files, faces, captions, links).
    Original photos on disk are NEVER touched. Requires confirm=true.
    Prefer setting status to 'inactive' instead — that keeps labels for later re-add."""
    if not body.confirm:
        raise HTTPException(400, "hard delete requires confirm=true; this cannot be undone")
    db = get_db()
    src = db.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
    if not src:
        raise HTTPException(404, "source not found")
    file_ids = [r["id"] for r in db.execute(
        "SELECT id FROM files WHERE source_id=?", (source_id,))]
    # FK-safe order; analysis_fts is contentless so delete by rowid
    for fid in file_ids:
        db.execute("DELETE FROM analysis_fts WHERE rowid=?", (fid,))
    db.execute("DELETE FROM image_people WHERE file_id IN (SELECT id FROM files WHERE source_id=?)",
               (source_id,))
    db.execute("DELETE FROM image_analysis WHERE file_id IN (SELECT id FROM files WHERE source_id=?)",
               (source_id,))
    db.execute("DELETE FROM faces WHERE file_id IN (SELECT id FROM files WHERE source_id=?)",
               (source_id,))
    db.execute("DELETE FROM files WHERE source_id=?", (source_id,))
    db.execute("DELETE FROM sources WHERE id=?", (source_id,))
    db.commit()
    return {"ok": True, "deleted_files": len(file_ids),
            "note": "original photos on disk were not touched"}


@router.post("/{source_id}/scan")
def scan_now(source_id: int):
    db = get_db()
    src = db.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
    if not src:
        raise HTTPException(404, "source not found")
    if src["status"] == "paused":
        raise HTTPException(400, "source is paused; unpause to scan")
    if src["status"] == "inactive":
        raise HTTPException(400, "source is inactive; restore to scan")
    running = db.execute(
        "SELECT id FROM jobs WHERE job_type='scan_source' AND status IN ('pending','running')"
        " AND payload_json LIKE ?", (f'%"source_id": {source_id}%',)).fetchone()
    if running:
        return {"job_id": running["id"], "already_running": True}
    job_id = runner.create_job("scan_source", {"source_id": source_id})
    runner.run_job_async(job_id)
    return {"job_id": job_id, "already_running": False}
