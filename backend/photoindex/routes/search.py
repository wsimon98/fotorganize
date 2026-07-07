from __future__ import annotations

from fastapi import APIRouter

from ..database import get_db

router = APIRouter(prefix="/api", tags=["search"])


@router.get("/search")
def search(q: str | None = None, person: str | None = None,
           person_id: int | None = None, source_id: int | None = None,
           date_from: str | None = None, date_to: str | None = None,
           has_people: int | None = None, min_width: int | None = None,
           screenshots: int | None = None,
           confirmed_only: int = 0, page: int = 1, per_page: int = 100):
    """Combined search over captions/tags/OCR (FTS), person, date, source, dimensions."""
    db = get_db()
    joins = ["JOIN sources s ON s.id=f.source_id"]
    where = ["f.status='active'", "s.status != 'inactive'"]
    params: list = []

    if q:
        joins.append("JOIN analysis_fts ON analysis_fts.rowid = f.id")
        where.append("analysis_fts MATCH ?")
        params.append(q)
    if person_id or person:
        joins.append("JOIN image_people ip ON ip.file_id=f.id")
        if person_id:
            where.append("ip.person_id=?")
            params.append(person_id)
        else:
            joins.append("JOIN people p ON p.id=ip.person_id")
            where.append("p.display_name=? COLLATE NOCASE")
            params.append(person)
        if confirmed_only:
            where.append("ip.confirmed_by_user=1")
    if source_id:
        where.append("f.source_id=?")
        params.append(source_id)
    if date_from:
        where.append("f.date_taken >= ?")
        params.append(date_from)
    if date_to:
        where.append("f.date_taken <= ?")
        params.append(date_to)
    if min_width:
        where.append("f.width >= ?")
        params.append(min_width)
    if has_people is not None:
        op = ">" if has_people else "="
        where.append(f"(SELECT COUNT(*) FROM faces fx WHERE fx.file_id=f.id "
                     f"AND fx.status='active') {op} 0")
    if screenshots is not None:
        where.append("f.is_screenshot=?")
        params.append(1 if screenshots else 0)

    per_page = min(max(per_page, 1), 500)
    off = (max(page, 1) - 1) * per_page
    sql_from = "FROM files f " + " ".join(joins) + " WHERE " + " AND ".join(where)
    total = db.execute(f"SELECT COUNT(DISTINCT f.id) c {sql_from}", params).fetchone()["c"]
    rows = db.execute(
        f"""SELECT DISTINCT f.id, f.relative_path, f.date_taken, f.thumb_status,
            f.updated_at,
            (SELECT ia.caption_short FROM image_analysis ia
             WHERE ia.file_id=f.id AND ia.status='done') AS caption_short
            {sql_from} ORDER BY f.date_taken DESC NULLS LAST, f.id DESC
            LIMIT ? OFFSET ?""", (*params, per_page, off)).fetchall()
    return {"total": total, "page": page, "per_page": per_page,
            "items": [dict(r) for r in rows]}
