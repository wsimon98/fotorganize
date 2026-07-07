from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..database import get_db
from ..services import lora_export

router = APIRouter(prefix="/api", tags=["exports"])


class ExportIn(BaseModel):
    trigger: str | None = None
    zip_output: bool = False
    export_mode: str | None = None       # full | face_crop | smart_crop
    confirmed_only: bool | None = None
    include_group: bool | None = None
    min_face_quality: float | None = None
    min_image_size: int | None = None
    max_images: int | None = None
    dedupe: bool | None = None
    exclude_screenshots: bool | None = None
    caption_style: str | None = None     # natural | tag


@router.post("/people/{person_id}/export")
def export_person(person_id: int, body: ExportIn):
    db = get_db()
    if not db.execute("SELECT 1 FROM people WHERE id=?", (person_id,)).fetchone():
        raise HTTPException(404, "person not found")
    opts = body.model_dump(exclude={"trigger", "zip_output"}, exclude_none=True)
    try:
        return lora_export.export_person(
            person_id, trigger=body.trigger, zip_output=body.zip_output, **opts)
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


class SearchExportIn(BaseModel):
    name: str                          # dataset name, e.g. "river" or "motorcycles"
    q: str | None = None               # export every FTS caption match
    file_ids: list[int] | None = None  # or an explicit selection
    trigger: str | None = None
    max_images: int = 0
    dedupe: bool = True
    zip_output: bool = False


@router.post("/search/export")
def export_search_results(body: SearchExportIn):
    if not (body.q or body.file_ids):
        raise HTTPException(400, "q or file_ids required")
    try:
        return lora_export.export_search(
            body.name, file_ids=body.file_ids, q=body.q, trigger=body.trigger,
            max_images=body.max_images, dedupe=body.dedupe, zip_output=body.zip_output)
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@router.get("/exports")
def list_exports():
    db = get_db()
    rows = db.execute(
        """SELECT e.*, p.display_name FROM exports e LEFT JOIN people p ON p.id=e.person_id
           ORDER BY e.id DESC LIMIT 100""").fetchall()
    return [dict(r) for r in rows]
