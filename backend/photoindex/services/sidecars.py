"""Phase 10: XMP sidecar read/write. OPT-IN, never modifies original photos.

A sidecar is a separate `<original>.xmp` file next to the photo (or, if
config.WRITE_XMP_SIDECARS is disabled, we never write). We write a minimal, widely-read
XMP packet:
  - dc:subject           bag of keywords = person names + object tags
  - MicrosoftPhoto:LastKeywordXMP  (Windows Explorer / Photos reads this)
Person names are also emitted as digiKam-style TagsList entries "People/<Name>" so digiKam
picks them up.

We deliberately do NOT write MWG face-region rectangles (complex, tool-specific); names go
in as keywords, which every major tool reads. Reading parses dc:subject back into tags.
"""
from __future__ import annotations

import logging
import os
import re
import xml.sax.saxutils as sx

from .. import config
from ..database import get_db, utcnow

log = logging.getLogger(__name__)


def sidecar_path(full_path: str) -> str:
    return full_path + ".xmp"


def read_sidecar(full_path: str) -> dict:
    """Return {'keywords': [...]} parsed from an existing .xmp, or {} if none/unreadable."""
    p = sidecar_path(full_path)
    if not os.path.isfile(p):
        return {}
    try:
        text = open(p, "r", encoding="utf-8", errors="ignore").read()
        kws = re.findall(r"<rdf:li[^>]*>(.*?)</rdf:li>", text, re.S)
        cleaned = sorted({sx.unescape(k.strip()) for k in kws if k.strip()})
        return {"keywords": cleaned}
    except Exception as e:
        log.warning("read sidecar failed %s: %s", p, e)
        return {}


def _xmp_document(keywords: list[str], people: list[str]) -> str:
    def li(items):
        return "".join(f"<rdf:li>{sx.escape(k)}</rdf:li>" for k in items)
    taglist = li([f"People/{p}" for p in people])
    return f"""<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:MicrosoftPhoto="http://ns.microsoft.com/photo/1.0/"
    xmlns:digiKam="http://www.digikam.org/ns/1.0/">
   <dc:subject><rdf:Bag>{li(keywords)}</rdf:Bag></dc:subject>
   <MicrosoftPhoto:LastKeywordXMP><rdf:Bag>{li(keywords)}</rdf:Bag></MicrosoftPhoto:LastKeywordXMP>
   <digiKam:TagsList><rdf:Seq>{taglist}</rdf:Seq></digiKam:TagsList>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>"""


def write_sidecar(file_id: int, force: bool = False) -> dict:
    """Write an .xmp next to the original for one file. Blocked unless
    config.WRITE_XMP_SIDECARS is true (or force=True for an explicit single call)."""
    if not (config.WRITE_XMP_SIDECARS or force):
        return {"skipped": "WRITE_XMP_SIDECARS is disabled"}
    db = get_db()
    f = db.execute("SELECT full_path FROM files WHERE id=?", (file_id,)).fetchone()
    if not f or not os.path.isfile(f["full_path"]):
        return {"error": "file not reachable"}
    people = [r["display_name"] for r in db.execute(
        """SELECT DISTINCT p.display_name FROM image_people ip
           JOIN people p ON p.id=ip.person_id WHERE ip.file_id=?
           ORDER BY p.display_name""", (file_id,))]
    tags = []
    ia = db.execute("SELECT object_tags_json FROM image_analysis WHERE file_id=?",
                    (file_id,)).fetchone()
    if ia and ia["object_tags_json"]:
        import json
        tags = json.loads(ia["object_tags_json"])
    keywords = sorted(set(people + tags))
    if not keywords:
        return {"skipped": "no tags/people to write"}
    p = sidecar_path(f["full_path"])
    try:
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(_xmp_document(keywords, people))
        db.execute("UPDATE files SET sidecar_written_at=? WHERE id=?", (utcnow(), file_id))
        db.commit()
        return {"ok": True, "path": p, "keywords": keywords}
    except Exception as e:
        log.warning("write sidecar failed %s: %s", p, e)
        return {"error": str(e)}


def write_all(force: bool = False) -> dict:
    """Write sidecars for every active file that has any person or tags."""
    if not (config.WRITE_XMP_SIDECARS or force):
        return {"skipped": "WRITE_XMP_SIDECARS is disabled; set it in .env or pass force"}
    db = get_db()
    ids = [r["id"] for r in db.execute("SELECT id FROM files WHERE status='active'")]
    stats = {"written": 0, "skipped": 0, "errors": 0}
    for fid in ids:
        res = write_sidecar(fid, force=force)
        if res.get("ok"):
            stats["written"] += 1
        elif res.get("error"):
            stats["errors"] += 1
        else:
            stats["skipped"] += 1
    log.info("write_all sidecars: %s", stats)
    return stats
