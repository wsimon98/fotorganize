"""Thumbnail cache. Content-addressed: data/thumbnails/<sha[0:2]>/<sha>.jpg.

Path is DERIVED from sha256, never stored in the DB (see DECISIONS.md).
"""
from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageOps

from .. import config
from ..database import get_db, utcnow

log = logging.getLogger(__name__)


def thumb_path(sha256: str) -> Path:
    return config.THUMBNAIL_DIR / sha256[:2] / f"{sha256}.jpg"


def generate_from_pil(rgb_img: Image.Image, sha256: str) -> bool:
    try:
        p = thumb_path(sha256)
        p.parent.mkdir(parents=True, exist_ok=True)
        img = rgb_img.copy()
        img.thumbnail((config.THUMBNAIL_SIZE, config.THUMBNAIL_SIZE))
        img.save(p, "JPEG", quality=85)
        return True
    except Exception as e:
        log.warning("thumbnail failed for %s: %s", sha256, e)
        return False


def generate_from_file(full_path: str, sha256: str) -> bool:
    try:
        with Image.open(full_path) as img:
            img = ImageOps.exif_transpose(img)  # respect phone rotation metadata
            return generate_from_pil(img.convert("RGB"), sha256)
    except Exception as e:
        log.warning("thumbnail failed for %s: %s", full_path, e)
        return False


def generate_missing(retry_failed: bool = False, progress_cb=None) -> dict:
    """(Re)build thumbnails for files whose thumb is pending/failed or vanished on disk."""
    db = get_db()
    statuses = ("pending", "failed") if retry_failed else ("pending",)
    rows = db.execute(
        f"""SELECT id, full_path, sha256_hash FROM files
            WHERE status='active' AND sha256_hash IS NOT NULL
              AND thumb_status IN ({','.join('?' * len(statuses))})""",
        statuses).fetchall()
    stats = {"ok": 0, "failed": 0}
    for i, r in enumerate(rows):
        ok = generate_from_file(r["full_path"], r["sha256_hash"])
        db.execute("UPDATE files SET thumb_status=?, updated_at=? WHERE id=?",
                   ("ok" if ok else "failed", utcnow(), r["id"]))
        stats["ok" if ok else "failed"] += 1
        if i % 100 == 0:
            db.commit()
            if progress_cb:
                progress_cb(f"{i}/{len(rows)} thumbnails")
    db.commit()
    return stats
