"""User edits to captions: single-image update and bulk find/replace.

The whole point: after AI captions "man in a red shirt", the user can correct "man" to
"George Clooney" — on one image, on a selection, or across every search match. Edits
update image_analysis AND the FTS index so search immediately reflects them.
"""
from __future__ import annotations

import json
import logging
import re

from ..database import get_db, utcnow

log = logging.getLogger(__name__)


def _reindex_fts(db, file_id: int) -> None:
    row = db.execute(
        "SELECT caption_short, caption_detailed, object_tags_json, ocr_text"
        " FROM image_analysis WHERE file_id=?", (file_id,)).fetchone()
    db.execute("DELETE FROM analysis_fts WHERE rowid=?", (file_id,))
    if row:
        tags = " ".join(json.loads(row["object_tags_json"] or "[]"))
        db.execute(
            "INSERT INTO analysis_fts (rowid, caption_short, caption_detailed,"
            " object_tags, ocr_text) VALUES (?,?,?,?,?)",
            (file_id, row["caption_short"] or "", row["caption_detailed"] or "",
             tags, row["ocr_text"] or ""))


def update_caption(file_id: int, caption_short: str | None = None,
                   caption_detailed: str | None = None,
                   object_tags: list[str] | None = None) -> dict:
    """Set caption fields on one image. Creates the analysis row if missing (manual
    caption on an un-AI'd image is fine)."""
    db = get_db()
    now = utcnow()
    exists = db.execute("SELECT 1 FROM image_analysis WHERE file_id=?",
                        (file_id,)).fetchone()
    if not exists:
        db.execute(
            "INSERT INTO image_analysis (file_id, status, model_name, processed_at)"
            " VALUES (?, 'done', 'manual', ?)", (file_id, now))
    sets, params = [], []
    if caption_short is not None:
        sets.append("caption_short=?")
        params.append(caption_short)
    if caption_detailed is not None:
        sets.append("caption_detailed=?")
        params.append(caption_detailed)
    if object_tags is not None:
        sets.append("object_tags_json=?")
        params.append(json.dumps(object_tags))
    if sets:
        sets.append("processed_at=?")
        params.append(now)
        db.execute(f"UPDATE image_analysis SET {', '.join(sets)} WHERE file_id=?",
                   (*params, file_id))
    _reindex_fts(db, file_id)
    db.execute("UPDATE files SET caption_status='ok', updated_at=? WHERE id=?",
               (now, file_id))
    db.commit()
    return {"ok": True, "file_id": file_id}


def replace_in_captions(find: str, replace: str, file_ids: list[int] | None = None,
                        q: str | None = None, case_sensitive: bool = False,
                        whole_word: bool = True) -> dict:
    """Find/replace across captions (short + detailed) and object tags.

    Scope: explicit file_ids (user selection), OR every file whose caption matches FTS
    query `q` (the "select all results" case), OR all captioned files if neither given.
    whole_word avoids 'man' matching inside 'woman'/'human'.
    """
    if not find:
        raise ValueError("find text required")
    db = get_db()
    if file_ids:
        rows = db.execute(
            f"SELECT * FROM image_analysis WHERE file_id IN"
            f" ({','.join('?' * len(file_ids))})", file_ids).fetchall()
    elif q:
        ids = [r["rowid"] for r in db.execute(
            "SELECT rowid FROM analysis_fts WHERE analysis_fts MATCH ?", (q,))]
        if not ids:
            return {"changed": 0, "scope": 0}
        rows = db.execute(
            f"SELECT * FROM image_analysis WHERE file_id IN"
            f" ({','.join('?' * len(ids))})", ids).fetchall()
    else:
        rows = db.execute("SELECT * FROM image_analysis WHERE status='done'").fetchall()

    flags = 0 if case_sensitive else re.IGNORECASE
    pat = re.escape(find)
    if whole_word:
        pat = r"\b" + pat + r"\b"
    rx = re.compile(pat, flags)

    now = utcnow()
    changed_ids: list[int] = []
    for r in rows:
        new_short = rx.sub(replace, r["caption_short"] or "")
        new_det = rx.sub(replace, r["caption_detailed"] or "")
        tags = json.loads(r["object_tags_json"] or "[]")
        new_tags = [rx.sub(replace, t) for t in tags]
        if (new_short != (r["caption_short"] or "") or new_det != (r["caption_detailed"] or "")
                or new_tags != tags):
            db.execute(
                "UPDATE image_analysis SET caption_short=?, caption_detailed=?,"
                " object_tags_json=?, processed_at=? WHERE file_id=?",
                (new_short, new_det, json.dumps(new_tags), now, r["file_id"]))
            _reindex_fts(db, r["file_id"])
            changed_ids.append(r["file_id"])
    db.commit()
    log.info("caption replace %r -> %r: %s/%s changed", find, replace,
             len(changed_ids), len(rows))
    return {"changed": len(changed_ids), "scope": len(rows),
            "changed_file_ids": changed_ids}


def tag_files_as_person(file_ids: list[int], person_name: str) -> dict:
    """Create/find a person by name and link the given images to them
    (image_people, source='caption'). Used when a caption replace names someone."""
    if not file_ids or not person_name.strip():
        return {"person_id": None, "tagged": 0}
    db = get_db()
    now = utcnow()
    name = person_name.strip()
    row = db.execute("SELECT id FROM people WHERE display_name=? COLLATE NOCASE",
                     (name,)).fetchone()
    if row:
        pid = row["id"]
    else:
        pid = db.execute("INSERT INTO people (display_name, created_at, updated_at)"
                         " VALUES (?,?,?)", (name, now, now)).lastrowid
    tagged = 0
    for fid in file_ids:
        cur = db.execute(
            "INSERT OR IGNORE INTO image_people (file_id, person_id, confidence, source,"
            " confirmed_by_user, created_at) VALUES (?,?,1.0,'caption',1,?)",
            (fid, pid, now))
        tagged += cur.rowcount
    db.commit()
    log.info("tagged %s image(s) as person %r (id %s)", tagged, name, pid)
    return {"person_id": pid, "person_name": name, "tagged": tagged}


def sync_people_from_captions() -> dict:
    """For every known person, find caption FTS matches of their name and link those
    images (image_people, source='caption'). Retroactive version of tag_files_as_person."""
    db = get_db()
    results = []
    for p in db.execute("SELECT id, display_name FROM people").fetchall():
        phrase = '"' + p["display_name"].replace('"', "") + '"'
        try:
            ids = [r["rowid"] for r in db.execute(
                "SELECT rowid FROM analysis_fts WHERE analysis_fts MATCH ?", (phrase,))]
        except Exception:
            continue
        if not ids:
            continue
        res = tag_files_as_person(ids, p["display_name"])
        if res["tagged"]:
            results.append({"person": p["display_name"], "new_links": res["tagged"],
                            "caption_matches": len(ids)})
    return {"people_updated": len(results), "details": results}
