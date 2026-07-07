from __future__ import annotations

from fastapi import APIRouter

from .. import config
from ..database import get_db
from ..services import duplicates, sidecars

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])


@router.get("/duplicates")
def get_duplicates(kind: str = "exact", max_distance: int = 6):
    groups = (duplicates.exact_duplicate_groups() if kind == "exact"
              else duplicates.near_duplicate_groups(max_distance))
    # attach a preview file id per group + relative paths
    db = get_db()
    for g in groups:
        rows = db.execute(
            f"SELECT id, relative_path FROM files WHERE id IN "
            f"({','.join('?'*len(g['file_ids']))})", g["file_ids"]).fetchall()
        g["files"] = [dict(r) for r in rows]
    return {"kind": kind, "groups": groups, "group_count": len(groups)}


@router.post("/flag-screenshots")
def flag_screenshots():
    return duplicates.flag_screenshots()


@router.post("/write-sidecars")
def write_sidecars(force: bool = False):
    return sidecars.write_all(force=force)


@router.get("/config")
def maintenance_config():
    return {"write_xmp_sidecars": config.WRITE_XMP_SIDECARS}
