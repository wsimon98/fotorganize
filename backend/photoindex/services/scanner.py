"""Source scanner.

Design rules honored here (see spec / DECISIONS.md):
- Upsert by (source_id, relative_path): rescans never duplicate rows.
- Unchanged files (same size + mtime) are skipped without re-hashing.
- Files that disappear are marked status='missing', never deleted.
- A file that reappears is flipped back to 'active'.
- If the source root is unreachable, the source is marked 'missing' and
  NOTHING about its files is touched.
- Failures on individual files are logged and skipped; the scan continues.
"""
from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
from datetime import datetime, timezone

from PIL import Image, ImageOps, ExifTags

from .. import config
from ..database import get_db, utcnow
from ..utils.paths import to_relative
from . import thumbnails

log = logging.getLogger(__name__)

Image.MAX_IMAGE_PIXELS = None  # trust our own photo library, avoid DecompressionBomb errors


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb", buffering=1024 * 1024) as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _exif_data(img: Image.Image) -> dict:
    """Extract date_taken, camera_model, gps from EXIF. Best-effort."""
    out: dict = {}
    try:
        exif = img.getexif()
        if not exif:
            return out
        # 306=DateTime, 272=Model; DateTimeOriginal lives in the Exif IFD (36867)
        dt = None
        try:
            ifd = exif.get_ifd(ExifTags.IFD.Exif)
            dt = ifd.get(36867) or ifd.get(36868)
        except Exception:
            pass
        dt = dt or exif.get(306)
        if dt and isinstance(dt, str):
            try:
                out["date_taken"] = datetime.strptime(
                    dt.strip()[:19], "%Y:%m:%d %H:%M:%S"
                ).strftime("%Y-%m-%dT%H:%M:%S")
            except ValueError:
                pass
        model = exif.get(272)
        if model and isinstance(model, str):
            out["camera_model"] = model.strip()
        try:
            gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
            if gps and 2 in gps and 4 in gps:
                def to_deg(vals, ref, neg_refs):
                    d = float(vals[0]) + float(vals[1]) / 60 + float(vals[2]) / 3600
                    return -d if ref in neg_refs else d

                out["gps_lat"] = to_deg(gps[2], gps.get(1, "N"), ("S",))
                out["gps_lon"] = to_deg(gps[4], gps.get(3, "E"), ("W",))
        except Exception:
            pass
    except Exception:
        pass
    return out


def _analyze_image(full_path: str) -> dict:
    """Open once: dimensions, EXIF, perceptual hash, thumbnail. Never raises."""
    info: dict = {}
    try:
        import imagehash

        with Image.open(full_path) as img:
            info.update(_exif_data(img))
            # apply EXIF orientation so phone photos aren't sideways/upside-down
            img = ImageOps.exif_transpose(img)
            info["width"], info["height"] = img.size
            rgb = img.convert("RGB")
            info["perceptual_hash"] = str(imagehash.phash(rgb))
            info["_pil_rgb"] = rgb  # handed to thumbnail generator
    except Exception as e:
        info["_error"] = f"{type(e).__name__}: {e}"
    return info


def scan_source(source_id: int, log_to: logging.Logger | None = None,
                progress_cb=None) -> dict:
    """Scan one source. Returns summary dict. Safe to re-run any time."""
    slog = log_to or log
    db = get_db()
    src = db.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
    if not src:
        raise ValueError(f"source {source_id} not found")

    root = src["root_path"]
    if not os.path.isdir(root):
        slog.warning("source %s root unreachable: %s — marking missing, files untouched",
                     source_id, root)
        db.execute("UPDATE sources SET status='missing', updated_at=? WHERE id=?",
                   (utcnow(), source_id))
        db.commit()
        return {"status": "missing", "root": root}

    # source reachable again — if it was 'missing', restore to active
    if src["status"] == "missing":
        db.execute("UPDATE sources SET status='active', updated_at=? WHERE id=?",
                   (utcnow(), source_id))
        db.commit()

    existing = {
        r["relative_path"]: r
        for r in db.execute(
            "SELECT id, relative_path, file_size, modified_time, status, sha256_hash,"
            " thumb_status FROM files WHERE source_id=?", (source_id,))
    }
    seen: set[str] = set()
    stats = {"new": 0, "updated": 0, "unchanged": 0, "reactivated": 0,
             "errors": 0, "marked_missing": 0}
    now = utcnow()

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ("$RECYCLE.BIN", "System Volume Information", "@eaDir", "#recycle")]
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in config.IMAGE_EXTENSIONS:
                continue
            full = os.path.join(dirpath, fname)
            rel = to_relative(full, root)
            seen.add(rel)
            try:
                st = os.stat(full)
                mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc
                                               ).strftime("%Y-%m-%dT%H:%M:%SZ")
                row = existing.get(rel)
                if row and row["file_size"] == st.st_size and row["modified_time"] == mtime:
                    # unchanged — just make sure it's not marked missing
                    if row["status"] == "missing":
                        db.execute("UPDATE files SET status='active', full_path=?, updated_at=?"
                                   " WHERE id=?", (full, now, row["id"]))
                        stats["reactivated"] += 1
                    else:
                        stats["unchanged"] += 1
                    # backfill thumbnail if it vanished
                    if row["thumb_status"] == "ok" and row["sha256_hash"] and \
                            not thumbnails.thumb_path(row["sha256_hash"]).exists():
                        db.execute("UPDATE files SET thumb_status='pending' WHERE id=?",
                                   (row["id"],))
                    continue

                sha = sha256_of(full)
                info = _analyze_image(full)
                pil = info.pop("_pil_rgb", None)
                err = info.pop("_error", None)
                if err:
                    slog.warning("analyze failed %s: %s", full, err)

                thumb_status = "failed"
                if pil is not None:
                    thumb_status = "ok" if thumbnails.generate_from_pil(pil, sha) else "failed"

                vals = dict(
                    source_id=source_id, relative_path=rel, full_path=full,
                    file_size=st.st_size, modified_time=mtime, sha256_hash=sha,
                    perceptual_hash=info.get("perceptual_hash"),
                    mime_type=mimetypes.guess_type(fname)[0],
                    width=info.get("width"), height=info.get("height"),
                    date_taken=info.get("date_taken"),
                    camera_model=info.get("camera_model"),
                    gps_lat=info.get("gps_lat"), gps_lon=info.get("gps_lon"),
                    thumb_status=thumb_status, updated_at=now,
                )
                if row:
                    db.execute(
                        """UPDATE files SET full_path=:full_path, file_size=:file_size,
                           modified_time=:modified_time, sha256_hash=:sha256_hash,
                           perceptual_hash=:perceptual_hash, mime_type=:mime_type,
                           width=:width, height=:height, date_taken=:date_taken,
                           camera_model=:camera_model, gps_lat=:gps_lat, gps_lon=:gps_lon,
                           status='active', thumb_status=:thumb_status, updated_at=:updated_at
                           WHERE id=:id""", {**vals, "id": row["id"]})
                    stats["updated"] += 1
                else:
                    db.execute(
                        """INSERT INTO files (source_id, relative_path, full_path, file_size,
                           modified_time, sha256_hash, perceptual_hash, mime_type, width,
                           height, date_taken, camera_model, gps_lat, gps_lon, status,
                           thumb_status, created_at, updated_at)
                           VALUES (:source_id, :relative_path, :full_path, :file_size,
                           :modified_time, :sha256_hash, :perceptual_hash, :mime_type,
                           :width, :height, :date_taken, :camera_model, :gps_lat, :gps_lon,
                           'active', :thumb_status, :updated_at, :updated_at)""", vals)
                    stats["new"] += 1
            except Exception as e:
                stats["errors"] += 1
                slog.error("scan error on %s: %s", full, e)

            total = stats["new"] + stats["updated"] + stats["unchanged"]
            if total % config.SCAN_BATCH_SIZE == 0:
                db.commit()
                if progress_cb:
                    progress_cb(f"{total} files processed")

    # mark files that are gone as missing (never delete)
    for rel, row in existing.items():
        if rel not in seen and row["status"] == "active":
            db.execute("UPDATE files SET status='missing', updated_at=? WHERE id=?",
                       (now, row["id"]))
            stats["marked_missing"] += 1

    db.execute("UPDATE sources SET last_scan_at=?, updated_at=? WHERE id=?",
               (now, now, source_id))
    db.commit()
    slog.info("scan source %s done: %s", source_id, stats)
    return stats
