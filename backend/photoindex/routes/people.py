from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..database import get_db, utcnow

router = APIRouter(prefix="/api", tags=["people"])


# ---------- helpers ----------

def _sync_image_people_for_file(db, file_id: int, now: str):
    """Rebuild face_match image_people rows for a file from its active faces.
    Manual rows (source='manual') are preserved."""
    present = {r["person_id"] for r in db.execute(
        "SELECT DISTINCT person_id FROM faces WHERE file_id=? AND status='active'"
        " AND person_id IS NOT NULL", (file_id,))}
    existing = {r["person_id"] for r in db.execute(
        "SELECT person_id FROM image_people WHERE file_id=? AND source='face_match'",
        (file_id,))}
    for pid in present - existing:
        db.execute("INSERT OR IGNORE INTO image_people (file_id, person_id, source,"
                   " confirmed_by_user, created_at) VALUES (?,?, 'face_match', 1, ?)",
                   (file_id, pid, now))
    for pid in existing - present:
        db.execute("DELETE FROM image_people WHERE file_id=? AND person_id=?"
                   " AND source='face_match'", (file_id, pid))


def _get_or_create_person(db, name: str, now: str) -> int:
    row = db.execute("SELECT id FROM people WHERE display_name=? COLLATE NOCASE",
                     (name,)).fetchone()
    if row:
        return row["id"]
    cur = db.execute("INSERT INTO people (display_name, created_at, updated_at)"
                     " VALUES (?,?,?)", (name, now, now))
    return cur.lastrowid


def _assign_faces(db, face_ids: list[int], person_id: int, now: str):
    files = set()
    for fid in face_ids:
        row = db.execute("SELECT file_id FROM faces WHERE id=?", (fid,)).fetchone()
        if not row:
            continue
        db.execute("UPDATE faces SET person_id=?, cluster_id=NULL, confirmed_by_user=1,"
                   " status='active' WHERE id=?", (person_id, fid))
        files.add(row["file_id"])
    for f in files:
        _sync_image_people_for_file(db, f, now)
    cover = db.execute("SELECT cover_face_id FROM people WHERE id=?", (person_id,)).fetchone()
    if cover and cover["cover_face_id"] is None and face_ids:
        db.execute("UPDATE people SET cover_face_id=?, updated_at=? WHERE id=?",
                   (face_ids[0], now, person_id))


# ---------- clusters ----------

@router.get("/clusters")
def list_clusters():
    db = get_db()
    rows = db.execute(
        """SELECT * FROM (
             SELECT c.id, c.status, c.confidence,
                  (SELECT COUNT(*) FROM faces f WHERE f.cluster_id=c.id AND f.status='active') AS n,
                  (SELECT f.id FROM faces f WHERE f.cluster_id=c.id AND f.status='active'
                     ORDER BY f.quality_score DESC LIMIT 1) AS cover_face_id
             FROM face_clusters c WHERE c.status='needs_review'
           ) WHERE n > 0 ORDER BY n DESC""").fetchall()
    return [dict(r) for r in rows]


@router.get("/clusters/{cluster_id}/faces")
def cluster_faces(cluster_id: int):
    db = get_db()
    rows = db.execute(
        """SELECT f.id, f.file_id, f.quality_score, f.status
           FROM faces f WHERE f.cluster_id=? AND f.status='active'
           ORDER BY f.quality_score DESC""", (cluster_id,)).fetchall()
    return [dict(r) for r in rows]


class NameIn(BaseModel):
    name: str


@router.post("/clusters/{cluster_id}/name")
def name_cluster(cluster_id: int, body: NameIn):
    db = get_db()
    now = utcnow()
    pid = _get_or_create_person(db, body.name.strip(), now)
    face_ids = [r["id"] for r in db.execute(
        "SELECT id FROM faces WHERE cluster_id=? AND status='active'", (cluster_id,))]
    _assign_faces(db, face_ids, pid, now)
    db.execute("UPDATE face_clusters SET status='named', updated_at=? WHERE id=?",
               (now, cluster_id))
    db.commit()
    return {"person_id": pid, "faces_assigned": len(face_ids)}


@router.post("/clusters/{cluster_id}/reject")
def reject_cluster(cluster_id: int):
    db = get_db()
    now = utcnow()
    db.execute("UPDATE faces SET status='not_person', cluster_id=NULL WHERE cluster_id=?",
               (cluster_id,))
    db.execute("UPDATE face_clusters SET status='rejected', updated_at=? WHERE id=?",
               (now, cluster_id))
    db.commit()
    return {"ok": True}


# ---------- face actions ----------

class FaceIdsIn(BaseModel):
    face_ids: list[int]


class AssignIn(BaseModel):
    face_ids: list[int]
    person_id: int | None = None
    name: str | None = None


@router.post("/faces/assign")
def assign_faces(body: AssignIn):
    db = get_db()
    now = utcnow()
    if body.person_id:
        pid = body.person_id
    elif body.name:
        pid = _get_or_create_person(db, body.name.strip(), now)
    else:
        raise HTTPException(400, "person_id or name required")
    _assign_faces(db, body.face_ids, pid, now)
    db.commit()
    return {"person_id": pid, "faces_assigned": len(body.face_ids)}


class FaceStatusIn(BaseModel):
    face_ids: list[int]
    status: str  # not_person | bad_crop | rejected | active


@router.post("/faces/status")
def set_face_status(body: FaceStatusIn):
    if body.status not in ("not_person", "bad_crop", "rejected", "active"):
        raise HTTPException(400, "bad status")
    db = get_db()
    now = utcnow()
    files = set()
    for fid in body.face_ids:
        row = db.execute("SELECT file_id FROM faces WHERE id=?", (fid,)).fetchone()
        if row:
            files.add(row["file_id"])
        db.execute("UPDATE faces SET status=?, cluster_id=NULL, person_id=NULL WHERE id=?",
                   (body.status, fid))
    for f in files:
        _sync_image_people_for_file(db, f, now)
    db.commit()
    return {"ok": True, "updated": len(body.face_ids)}


# ---------- people ----------

@router.get("/people")
def list_people():
    db = get_db()
    rows = db.execute(
        """SELECT p.*,
                  (SELECT COUNT(*) FROM faces f WHERE f.person_id=p.id AND f.status='active') AS face_count,
                  (SELECT COUNT(DISTINCT file_id) FROM image_people ip WHERE ip.person_id=p.id) AS image_count,
                  (SELECT ip.file_id FROM image_people ip JOIN files fl ON fl.id=ip.file_id
                   WHERE ip.person_id=p.id AND fl.status='active' LIMIT 1) AS cover_file_id
           FROM people p ORDER BY p.display_name COLLATE NOCASE""").fetchall()
    return [dict(r) for r in rows]


@router.get("/people/{person_id}")
def person_detail(person_id: int):
    db = get_db()
    p = db.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
    if not p:
        raise HTTPException(404, "person not found")
    d = dict(p)
    d["face_count"] = db.execute(
        "SELECT COUNT(*) c FROM faces WHERE person_id=? AND status='active'",
        (person_id,)).fetchone()["c"]
    d["image_count"] = db.execute(
        "SELECT COUNT(DISTINCT file_id) c FROM image_people WHERE person_id=?",
        (person_id,)).fetchone()["c"]
    return d


@router.get("/people/{person_id}/images")
def person_images(person_id: int, page: int = 1, per_page: int = 100):
    db = get_db()
    per_page = min(max(per_page, 1), 500)
    off = (max(page, 1) - 1) * per_page
    total = db.execute("SELECT COUNT(DISTINCT file_id) c FROM image_people WHERE person_id=?",
                       (person_id,)).fetchone()["c"]
    rows = db.execute(
        """SELECT f.id, f.relative_path, f.date_taken, f.thumb_status, f.updated_at
           FROM image_people ip JOIN files f ON f.id=ip.file_id
           WHERE ip.person_id=? AND f.status='active'
           GROUP BY f.id ORDER BY f.date_taken DESC NULLS LAST, f.id DESC
           LIMIT ? OFFSET ?""", (person_id, per_page, off)).fetchall()
    return {"total": total, "page": page, "per_page": per_page,
            "items": [dict(r) for r in rows]}


class RenameIn(BaseModel):
    display_name: str | None = None
    relationship: str | None = None


@router.post("/people/{person_id}")
def update_person(person_id: int, body: RenameIn):
    db = get_db()
    now = utcnow()
    if body.display_name:
        db.execute("UPDATE people SET display_name=?, updated_at=? WHERE id=?",
                   (body.display_name.strip(), now, person_id))
    if body.relationship is not None:
        db.execute("UPDATE people SET relationship=?, updated_at=? WHERE id=?",
                   (body.relationship, now, person_id))
    db.commit()
    return {"ok": True}


class MergeIn(BaseModel):
    into_person_id: int


@router.post("/people/{person_id}/merge")
def merge_person(person_id: int, body: MergeIn):
    """Merge person_id INTO into_person_id, then delete the emptied person."""
    db = get_db()
    now = utcnow()
    dst = body.into_person_id
    if dst == person_id:
        raise HTTPException(400, "cannot merge a person into itself")
    if not db.execute("SELECT 1 FROM people WHERE id=?", (dst,)).fetchone():
        raise HTTPException(404, "target person not found")
    files = {r["file_id"] for r in db.execute(
        "SELECT DISTINCT file_id FROM faces WHERE person_id=?", (person_id,))}
    db.execute("UPDATE faces SET person_id=? WHERE person_id=?", (dst, person_id))
    db.execute("DELETE FROM image_people WHERE person_id=?", (person_id,))
    for f in files:
        _sync_image_people_for_file(db, f, now)
    db.execute("DELETE FROM people WHERE id=?", (person_id,))
    db.commit()
    return {"ok": True, "merged_into": dst}
