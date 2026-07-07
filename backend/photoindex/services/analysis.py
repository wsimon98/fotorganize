"""Caption + face processing over pending files. Imports ai.* lazily (heavy GPU deps).

Per-file failures are logged and marked; the batch continues (spec rule: AI failures do
not stop the whole scan). Resumable: state lives in files.caption_status / files.face_status.
"""
from __future__ import annotations

import json
import logging

from ..database import get_db, utcnow

log = logging.getLogger(__name__)


def process_captions(limit: int | None = None, retry_failed: bool = False,
                     progress_cb=None) -> dict:
    from ..ai import captioner
    db = get_db()
    statuses = ("pending", "failed") if retry_failed else ("pending",)
    q = (f"SELECT id, full_path FROM files WHERE status='active' AND caption_status IN "
         f"({','.join('?' * len(statuses))}) ORDER BY id")
    if limit:
        q += f" LIMIT {int(limit)}"
    rows = db.execute(q, statuses).fetchall()
    stats = {"done": 0, "failed": 0, "total": len(rows)}
    for i, r in enumerate(rows):
        try:
            res = captioner.analyze(r["full_path"])
            tags = res.get("object_tags", [])
            db.execute(
                """INSERT INTO image_analysis (file_id, caption_short, caption_detailed,
                   object_tags_json, ocr_text, model_name, model_version, analysis_version,
                   status, processed_at) VALUES (?,?,?,?,?,?,?,1,'done',?)
                   ON CONFLICT(file_id) DO UPDATE SET caption_short=excluded.caption_short,
                   caption_detailed=excluded.caption_detailed,
                   object_tags_json=excluded.object_tags_json, ocr_text=excluded.ocr_text,
                   model_name=excluded.model_name, model_version=excluded.model_version,
                   status='done', error_message=NULL, processed_at=excluded.processed_at""",
                (r["id"], res["caption_short"], res["caption_detailed"],
                 json.dumps(tags), res["ocr_text"], res["model_name"],
                 res["model_version"], utcnow()))
            _index_fts(db, r["id"], res["caption_short"], res["caption_detailed"],
                       tags, res["ocr_text"])
            db.execute("UPDATE files SET caption_status='ok' WHERE id=?", (r["id"],))
            stats["done"] += 1
        except Exception as e:
            log.error("caption failed for %s: %s", r["full_path"], e)
            db.execute(
                """INSERT INTO image_analysis (file_id, status, error_message, processed_at)
                   VALUES (?,'failed',?,?)
                   ON CONFLICT(file_id) DO UPDATE SET status='failed',
                   error_message=excluded.error_message, processed_at=excluded.processed_at""",
                (r["id"], f"{type(e).__name__}: {e}", utcnow()))
            db.execute("UPDATE files SET caption_status='failed' WHERE id=?", (r["id"],))
            stats["failed"] += 1
        if i % 10 == 0:
            db.commit()
            if progress_cb:
                progress_cb(f"{i+1}/{len(rows)} captioned")
    db.commit()
    return stats


def _index_fts(db, file_id, short, detailed, tags, ocr):
    db.execute("DELETE FROM analysis_fts WHERE rowid=?", (file_id,))
    db.execute(
        "INSERT INTO analysis_fts (rowid, caption_short, caption_detailed, object_tags,"
        " ocr_text) VALUES (?,?,?,?,?)",
        (file_id, short or "", detailed or "", " ".join(tags or []), ocr or ""))


def process_faces(limit: int | None = None, retry_failed: bool = False,
                  progress_cb=None) -> dict:
    from ..ai import faces as facemod
    db = get_db()
    statuses = ("pending", "failed") if retry_failed else ("pending",)
    q = (f"SELECT id, full_path, sha256_hash FROM files WHERE status='active' AND "
         f"face_status IN ({','.join('?' * len(statuses))}) ORDER BY id")
    if limit:
        q += f" LIMIT {int(limit)}"
    rows = db.execute(q, statuses).fetchall()
    stats = {"done": 0, "failed": 0, "faces": 0, "total": len(rows)}
    now = utcnow()
    for i, r in enumerate(rows):
        try:
            # clear any prior faces for this file (re-detect cleanly), keep user-confirmed
            db.execute("DELETE FROM faces WHERE file_id=? AND confirmed_by_user=0",
                       (r["id"],))
            found = facemod.detect(r["full_path"], r["sha256_hash"])
            for f in found:
                db.execute(
                    """INSERT INTO faces (file_id, face_crop_path, bounding_box_json,
                       landmarks_json, embedding_vector, quality_score, blur_score,
                       pose_score, gender, age, status, model_name, model_version,
                       created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?, 'active', ?, ?, ?)""",
                    (r["id"], f["crop_path"], json.dumps(f["bbox"]),
                     json.dumps(f["landmarks"]), f["embedding"], f["quality_score"],
                     f["blur_score"], f["pose_score"], f.get("gender"), f.get("age"),
                     f["model_name"], f["model_version"], now))
                stats["faces"] += 1
            db.execute("UPDATE files SET face_status='ok' WHERE id=?", (r["id"],))
            stats["done"] += 1
        except Exception as e:
            log.error("face detect failed for %s: %s", r["full_path"], e)
            db.execute("UPDATE files SET face_status='failed' WHERE id=?", (r["id"],))
            stats["failed"] += 1
        if i % 10 == 0:
            db.commit()
            if progress_cb:
                progress_cb(f"{i+1}/{len(rows)} face-scanned, {stats['faces']} faces")
    db.commit()
    return stats
