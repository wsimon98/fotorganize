"""Phase 8: LoRA dataset export (ai-toolkit format). See docs/lora_export.md.

Output:
  data/exports/<Person>_aitoolkit_<YYYY-MM-DD>/
    person_0001.jpg  person_0001.txt   (matching basenames — ai-toolkit convention)
    manifest.json  contact_sheet.jpg  rejected/
"""
from __future__ import annotations

import json
import logging
import shutil
import zipfile
from datetime import datetime, timezone

from PIL import Image, ImageOps

from .. import config
from ..database import get_db, utcnow

log = logging.getLogger(__name__)

DEFAULTS = {
    "export_mode": "full",        # full | face_crop | smart_crop
    "confirmed_only": False,
    "include_group": True,
    "min_face_quality": 0.0,
    "min_image_size": 0,          # min(width,height) px
    "max_images": 0,              # 0 = no cap
    "dedupe": True,
    "dedupe_distance": 6,         # phash hamming threshold
    "exclude_screenshots": True,  # skip files flagged is_screenshot=1
    "caption_style": "natural",   # natural | tag
}


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name).strip("_") or "person"


def _caption(trigger, style, caption_short, tags):
    parts = []
    if trigger:
        parts.append(trigger)
    if style == "tag":
        parts.extend(tags or [])
        if not tags and caption_short:
            parts.append(caption_short)
    else:  # natural
        if caption_short:
            parts.append(caption_short.rstrip("."))
    return ", ".join(p for p in parts if p) or (trigger or "")


def _phash_dupe(existing, phash_hex, distance):
    if not phash_hex:
        return False
    try:
        import imagehash
        h = imagehash.hex_to_hash(phash_hex)
        for e in existing:
            if h - e <= distance:
                return True
        existing.append(h)
    except Exception:
        pass
    return False


def export_person(person_id: int, trigger: str | None = None, zip_output: bool = False,
                  **opts) -> dict:
    o = {**DEFAULTS, **{k: v for k, v in opts.items() if v is not None}}
    db = get_db()
    person = db.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
    if not person:
        raise ValueError(f"person {person_id} not found")
    if trigger is None:
        trigger = f"{_slug(person['display_name']).lower()}_person"

    # candidate images: one best face per file for this person
    rows = db.execute(
        """SELECT f.id AS file_id, f.full_path, f.width, f.height, f.perceptual_hash,
                  f.source_id, fa.id AS face_id, fa.bounding_box_json,
                  fa.quality_score, fa.confirmed_by_user,
                  ia.caption_short, ia.object_tags_json, f.is_screenshot,
                  (SELECT COUNT(*) FROM faces x WHERE x.file_id=f.id AND x.status='active')
                    AS face_count
           FROM faces fa
           JOIN files f ON f.id = fa.file_id
           LEFT JOIN image_analysis ia ON ia.file_id = f.id
           WHERE fa.person_id=? AND fa.status='active' AND f.status='active'
           ORDER BY fa.quality_score DESC""", (person_id,)).fetchall()

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    outdir = config.EXPORT_DIR / f"{_slug(person['display_name'])}_aitoolkit_{stamp}"
    rejected = outdir / "rejected"
    outdir.mkdir(parents=True, exist_ok=True)
    rejected.mkdir(exist_ok=True)

    manifest = {"person": person["display_name"], "trigger": trigger,
                "created_at": utcnow(), "settings": o, "images": []}
    seen_files = set()
    dup_hashes: list = []
    n = 0
    contact_imgs = []

    for r in rows:
        if r["file_id"] in seen_files:
            continue
        seen_files.add(r["file_id"])
        reason = None
        if o["confirmed_only"] and not r["confirmed_by_user"]:
            reason = "not_confirmed"
        elif o["exclude_screenshots"] and r["is_screenshot"] == 1:
            reason = "screenshot"
        elif not o["include_group"] and (r["face_count"] or 0) > 1:
            reason = "group_photo"
        elif r["quality_score"] is not None and r["quality_score"] < o["min_face_quality"]:
            reason = "low_face_quality"
        elif o["min_image_size"] and min(r["width"] or 0, r["height"] or 0) < o["min_image_size"]:
            reason = "too_small"
        elif o["dedupe"] and _phash_dupe(dup_hashes, r["perceptual_hash"], o["dedupe_distance"]):
            reason = "near_duplicate"

        try:
            with Image.open(r["full_path"]) as im:
                img = ImageOps.exif_transpose(im).convert("RGB")
                if not reason and o["export_mode"] in ("face_crop", "smart_crop"):
                    bb = json.loads(r["bounding_box_json"] or "{}")
                    if bb:
                        pad = 1.6 if o["export_mode"] == "smart_crop" else 0.35
                        bw, bh = bb["x2"] - bb["x1"], bb["y2"] - bb["y1"]
                        px, py = int(bw * pad), int(bh * pad)
                        img = img.crop((max(0, bb["x1"] - px), max(0, bb["y1"] - py),
                                        min(img.width, bb["x2"] + px),
                                        min(img.height, bb["y2"] + py)))
                if reason:
                    img.thumbnail((512, 512))
                    img.save(rejected / f"{reason}_{r['file_id']}.jpg", "JPEG", quality=80)
                    continue
                n += 1
                base = f"person_{n:04d}"
                img.save(outdir / f"{base}.jpg", "JPEG", quality=95)
                caption = _caption(trigger, o["caption_style"], r["caption_short"],
                                   json.loads(r["object_tags_json"] or "[]"))
                (outdir / f"{base}.txt").write_text(caption, encoding="utf-8")
                manifest["images"].append({
                    "filename": f"{base}.jpg", "original_path": r["full_path"],
                    "source_id": r["source_id"], "face_id": r["face_id"],
                    "quality_score": r["quality_score"], "caption": caption})
                if len(contact_imgs) < 42:
                    t = img.copy(); t.thumbnail((160, 160)); contact_imgs.append(t)
        except Exception as e:
            log.warning("export skip %s: %s", r["full_path"], e)
        if o["max_images"] and n >= o["max_images"]:
            break

    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _contact_sheet(contact_imgs, outdir / "contact_sheet.jpg")

    zip_path = None
    if zip_output:
        zip_path = str(outdir) + ".zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for p in outdir.rglob("*"):
                if p.is_file() and "rejected" not in p.parts:
                    z.write(p, p.relative_to(outdir))

    db.execute(
        "INSERT INTO exports (person_id, export_type, settings_json, output_path, zip_path,"
        " created_at) VALUES (?,?,?,?,?,?)",
        (person_id, "aitoolkit", json.dumps(o), str(outdir), zip_path, utcnow()))
    db.commit()
    result = {"person": person["display_name"], "exported": n,
              "output_path": str(outdir), "zip_path": zip_path}
    log.info("lora export: %s", result)
    return result


def export_search(name: str, file_ids: list[int] | None = None, q: str | None = None,
                  trigger: str | None = None, max_images: int = 0,
                  dedupe: bool = True, zip_output: bool = False) -> dict:
    """Export a SET OF SEARCH RESULTS (a place/thing like 'river' or 'motorcycle') as an
    ai-toolkit dataset: image + matching .txt caption. Scope = explicit file_ids or every
    FTS caption match of q."""
    db = get_db()
    if file_ids:
        ids = file_ids
    elif q:
        ids = [r["rowid"] for r in db.execute(
            "SELECT rowid FROM analysis_fts WHERE analysis_fts MATCH ?", (q,))]
    else:
        raise ValueError("file_ids or q required")
    rows = db.execute(
        f"""SELECT f.id, f.full_path, f.perceptual_hash, f.source_id, ia.caption_short
            FROM files f LEFT JOIN image_analysis ia ON ia.file_id=f.id
            WHERE f.status='active' AND f.id IN ({','.join('?' * len(ids))})""",
        ids).fetchall() if ids else []

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    slug = _slug(name)[:40] or "search"
    outdir = config.EXPORT_DIR / f"{slug}_search_{stamp}"
    outdir.mkdir(parents=True, exist_ok=True)
    manifest = {"search": name, "query": q, "trigger": trigger, "created_at": utcnow(),
                "images": []}
    dup_hashes: list = []
    n = 0
    contact_imgs = []
    for r in rows:
        if dedupe and _phash_dupe(dup_hashes, r["perceptual_hash"], 6):
            continue
        try:
            with Image.open(r["full_path"]) as im:
                img = ImageOps.exif_transpose(im).convert("RGB")
                n += 1
                base = f"img_{n:04d}"
                img.save(outdir / f"{base}.jpg", "JPEG", quality=95)
                caption = ", ".join(x for x in (trigger, (r["caption_short"] or "").rstrip("."))
                                    if x)
                (outdir / f"{base}.txt").write_text(caption, encoding="utf-8")
                manifest["images"].append({"filename": f"{base}.jpg",
                                           "original_path": r["full_path"],
                                           "source_id": r["source_id"],
                                           "caption": caption})
                if len(contact_imgs) < 42:
                    t = img.copy(); t.thumbnail((160, 160)); contact_imgs.append(t)
        except Exception as e:
            log.warning("search export skip %s: %s", r["full_path"], e)
        if max_images and n >= max_images:
            break
    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _contact_sheet(contact_imgs, outdir / "contact_sheet.jpg")
    zip_path = None
    if zip_output:
        zip_path = str(outdir) + ".zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for p in outdir.rglob("*"):
                if p.is_file():
                    z.write(p, p.relative_to(outdir))
    db.execute(
        "INSERT INTO exports (person_id, export_type, settings_json, output_path, zip_path,"
        " created_at) VALUES (NULL, 'search', ?, ?, ?, ?)",
        (json.dumps({"name": name, "q": q, "trigger": trigger, "dedupe": dedupe}),
         str(outdir), zip_path, utcnow()))
    db.commit()
    result = {"name": name, "exported": n, "output_path": str(outdir), "zip_path": zip_path}
    log.info("search export: %s", result)
    return result


def _contact_sheet(imgs, path, cols=6):
    if not imgs:
        return
    cell = 160
    rows = (len(imgs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * cell), (20, 22, 26))
    for i, im in enumerate(imgs):
        x, y = (i % cols) * cell, (i // cols) * cell
        ox, oy = (cell - im.width) // 2, (cell - im.height) // 2
        sheet.paste(im, (x + ox, y + oy))
    sheet.save(path, "JPEG", quality=85)
