from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .. import config
from ..database import get_db
from ..services import thumbnails

router = APIRouter(prefix="/api", tags=["files"])


@router.get("/files")
def list_files(source_id: int | None = None, status: str = "active",
               q: str | None = None, page: int = 1, per_page: int = 100):
    db = get_db()
    where, params = ["1=1"], []
    if status and status != "all":
        where.append("f.status=?")
        params.append(status)
    if source_id:
        where.append("f.source_id=?")
        params.append(source_id)
    else:
        # hide inactive sources by default
        if not config.SHOW_INACTIVE_SOURCES:
            where.append("s.status != 'inactive'")
    if q:
        where.append("f.relative_path LIKE ?")
        params.append(f"%{q}%")
    per_page = min(max(per_page, 1), 500)
    offset = (max(page, 1) - 1) * per_page
    sql_where = " AND ".join(where)
    total = db.execute(
        f"SELECT COUNT(*) c FROM files f JOIN sources s ON s.id=f.source_id WHERE {sql_where}",
        params).fetchone()["c"]
    rows = db.execute(
        f"""SELECT f.id, f.source_id, f.relative_path, f.file_size, f.width, f.height,
                   f.date_taken, f.status, f.thumb_status, f.sha256_hash, f.updated_at,
                   ia.caption_short
            FROM files f JOIN sources s ON s.id=f.source_id
            LEFT JOIN image_analysis ia ON ia.file_id=f.id AND ia.status='done'
            WHERE {sql_where}
            ORDER BY f.date_taken DESC NULLS LAST, f.id DESC
            LIMIT ? OFFSET ?""", (*params, per_page, offset)).fetchall()
    return {"total": total, "page": page, "per_page": per_page,
            "items": [dict(r) for r in rows]}


@router.get("/files/{file_id}")
def get_file(file_id: int):
    db = get_db()
    row = db.execute(
        """SELECT f.*, s.name AS source_name, s.root_path AS source_root
           FROM files f JOIN sources s ON s.id=f.source_id WHERE f.id=?""",
        (file_id,)).fetchone()
    if not row:
        raise HTTPException(404, "file not found")
    return dict(row)


@router.get("/thumb/{file_id}")
def get_thumb(file_id: int):
    db = get_db()
    row = db.execute("SELECT sha256_hash, full_path, thumb_status FROM files WHERE id=?",
                     (file_id,)).fetchone()
    if not row or not row["sha256_hash"]:
        raise HTTPException(404, "no thumbnail")
    p = thumbnails.thumb_path(row["sha256_hash"])
    if not p.exists():
        # on-demand rebuild (thumbnails rebuild if missing — Phase 2 rule)
        if not thumbnails.generate_from_file(row["full_path"], row["sha256_hash"]):
            raise HTTPException(404, "thumbnail unavailable")
    # no-cache = browser revalidates via ETag (FileResponse provides it) and gets a
    # cheap 304 unless the thumbnail file actually changed (e.g. regenerated after a fix)
    return FileResponse(p, media_type="image/jpeg",
                        headers={"Cache-Control": "no-cache"})


@router.get("/original/{file_id}")
def get_original(file_id: int):
    """Serve the full-res original (read-only) for the image detail page."""
    db = get_db()
    row = db.execute("SELECT full_path, mime_type FROM files WHERE id=?",
                     (file_id,)).fetchone()
    if not row or not os.path.isfile(row["full_path"]):
        raise HTTPException(404, "original not reachable")
    return FileResponse(row["full_path"], media_type=row["mime_type"] or "image/jpeg")
