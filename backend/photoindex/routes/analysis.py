from __future__ import annotations

import json
import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..database import get_db
from ..services import captions_edit, runner

router = APIRouter(prefix="/api", tags=["analysis"])


class CaptionEditIn(BaseModel):
    caption_short: str | None = None
    caption_detailed: str | None = None
    object_tags: list[str] | None = None


@router.post("/files/{file_id}/caption")
def edit_caption(file_id: int, body: CaptionEditIn):
    db = get_db()
    if not db.execute("SELECT 1 FROM files WHERE id=?", (file_id,)).fetchone():
        raise HTTPException(404, "file not found")
    return captions_edit.update_caption(
        file_id, caption_short=body.caption_short,
        caption_detailed=body.caption_detailed, object_tags=body.object_tags)


class ReplaceIn(BaseModel):
    find: str
    replace: str
    file_ids: list[int] | None = None   # explicit selection
    q: str | None = None                # or: every FTS match ("select all results")
    case_sensitive: bool = False
    whole_word: bool = True
    tag_person: bool = False            # also create/link the person named by `replace`


@router.post("/captions/replace")
def replace_captions(body: ReplaceIn):
    if not body.find.strip():
        raise HTTPException(400, "find text required")
    result = captions_edit.replace_in_captions(
        body.find, body.replace, file_ids=body.file_ids, q=body.q,
        case_sensitive=body.case_sensitive, whole_word=body.whole_word)
    if body.tag_person and result["changed_file_ids"]:
        result["person"] = captions_edit.tag_files_as_person(
            result["changed_file_ids"], body.replace)
    return result


@router.post("/captions/sync-people")
def sync_people_from_captions():
    """Link images to existing people wherever a caption mentions their name."""
    return captions_edit.sync_people_from_captions()


@router.post("/analysis/captions")
def enqueue_captions(retry_failed: bool = False):
    jid = runner.enqueue("caption_batch", {"retry_failed": retry_failed})
    return {"job_id": jid, "note": "run `python -m photoindex worker` to process"}


@router.post("/analysis/faces")
def enqueue_faces(retry_failed: bool = False):
    jid = runner.enqueue("face_batch", {"retry_failed": retry_failed})
    return {"job_id": jid, "note": "run `python -m photoindex worker` to process"}


@router.post("/analysis/cluster")
def enqueue_cluster():
    jid = runner.enqueue("cluster_faces", {})
    return {"job_id": jid, "note": "run `python -m photoindex worker` to process"}


@router.get("/files/{file_id}/analysis")
def file_analysis(file_id: int):
    db = get_db()
    row = db.execute("SELECT * FROM image_analysis WHERE file_id=?", (file_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["object_tags"] = json.loads(d.get("object_tags_json") or "[]")
    return d


@router.get("/files/{file_id}/faces")
def file_faces(file_id: int):
    db = get_db()
    rows = db.execute(
        """SELECT fa.id, fa.bounding_box_json, fa.quality_score, fa.status, fa.person_id,
                  fa.cluster_id, fa.gender, fa.age, p.display_name AS person_name
           FROM faces fa LEFT JOIN people p ON p.id=fa.person_id
           WHERE fa.file_id=? ORDER BY fa.id""", (file_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["bbox"] = json.loads(d.pop("bounding_box_json") or "{}")
        out.append(d)
    return out


@router.get("/facecrop/{face_id}")
def facecrop(face_id: int):
    db = get_db()
    row = db.execute("SELECT face_crop_path FROM faces WHERE id=?", (face_id,)).fetchone()
    if not row or not row["face_crop_path"] or not os.path.isfile(row["face_crop_path"]):
        raise HTTPException(404, "face crop not found")
    return FileResponse(row["face_crop_path"], media_type="image/jpeg",
                        headers={"Cache-Control": "no-cache"})
