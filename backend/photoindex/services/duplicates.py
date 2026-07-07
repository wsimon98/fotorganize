"""Phase 9: duplicate detection + screenshot/meme flagging.

- Exact duplicates: identical sha256_hash.
- Near-duplicates: perceptual_hash (phash) within a hamming distance threshold.
- Screenshot heuristic: filename hints, OR (has OCR text AND no faces). Stored in
  files.is_screenshot so search can filter and LoRA export can exclude them.

No models needed. Near-dup grouping is O(n^2) over active files — fine for a personal
library (tens of thousands). If it ever gets huge, switch to BK-tree / phash prefix buckets.
"""
from __future__ import annotations

import logging
import os
import re

from ..database import get_db, utcnow

log = logging.getLogger(__name__)

SCREENSHOT_NAME_RE = re.compile(r"screen[\s_-]?shot|screenshot|capture|snip", re.I)


def exact_duplicate_groups() -> list[dict]:
    db = get_db()
    rows = db.execute(
        """SELECT sha256_hash, COUNT(*) n, GROUP_CONCAT(id) ids
           FROM files WHERE status='active' AND sha256_hash IS NOT NULL
           GROUP BY sha256_hash HAVING n > 1 ORDER BY n DESC""").fetchall()
    return [{"hash": r["sha256_hash"], "count": r["n"],
             "file_ids": [int(x) for x in r["ids"].split(",")]} for r in rows]


def near_duplicate_groups(max_distance: int = 6) -> list[dict]:
    import imagehash
    db = get_db()
    rows = db.execute(
        "SELECT id, perceptual_hash FROM files WHERE status='active'"
        " AND perceptual_hash IS NOT NULL ORDER BY id").fetchall()
    items = []
    for r in rows:
        try:
            items.append((r["id"], imagehash.hex_to_hash(r["perceptual_hash"])))
        except Exception:
            pass
    n = len(items)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if items[i][1] - items[j][1] <= max_distance:
                parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(items[i][0])
    out = [{"file_ids": ids, "count": len(ids)}
           for ids in groups.values() if len(ids) > 1]
    out.sort(key=lambda g: g["count"], reverse=True)
    return out


def flag_screenshots() -> dict:
    """Evaluate every active file's is_screenshot flag. Returns counts."""
    db = get_db()
    rows = db.execute(
        """SELECT f.id, f.relative_path,
                  (SELECT ocr_text FROM image_analysis ia WHERE ia.file_id=f.id) AS ocr,
                  (SELECT COUNT(*) FROM faces x WHERE x.file_id=f.id AND x.status='active') AS faces
           FROM files f WHERE f.status='active'""").fetchall()
    now = utcnow()
    stats = {"screenshots": 0, "not": 0}
    for r in rows:
        name = os.path.basename(r["relative_path"] or "")
        is_ss = bool(SCREENSHOT_NAME_RE.search(name)) or \
            (bool((r["ocr"] or "").strip()) and (r["faces"] or 0) == 0
             and len((r["ocr"] or "").strip()) > 15)
        db.execute("UPDATE files SET is_screenshot=?, updated_at=? WHERE id=?",
                   (1 if is_ss else 0, now, r["id"]))
        stats["screenshots" if is_ss else "not"] += 1
    db.commit()
    log.info("flag_screenshots: %s", stats)
    return stats
