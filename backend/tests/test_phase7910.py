"""Phase 7/9/10 tests: hard-delete, duplicates, screenshot flagging, XMP sidecars.

Offline (no models). Reuses helpers style from test_phase38.
"""
import importlib
import os
import sys

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("THUMBNAIL_DIR", str(tmp_path / "thumbs"))
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("FACE_CROP_DIR", str(tmp_path / "faces"))
    monkeypatch.setenv("EXPORT_DIR", str(tmp_path / "exports"))
    from photoindex import config, database
    importlib.reload(config)
    if hasattr(database._local, "conn"):
        database._local.conn.close()
        del database._local.conn
    database.init_db()
    yield tmp_path
    if hasattr(database._local, "conn"):
        database._local.conn.close()
        del database._local.conn


def _src(db, root, now):
    db.execute("INSERT INTO sources (name, root_path, path_type, status, created_at,"
               " updated_at) VALUES ('t', ?, 'local', 'active', ?, ?)", (str(root), now, now))
    return db.execute("SELECT id FROM sources").fetchone()["id"]


def _file(db, sid, root, name, now, sha=None, phash=None, ocr=None):
    p = root / name
    Image.new("RGB", (300, 300), (100, 110, 120)).save(p)
    cur = db.execute(
        "INSERT INTO files (source_id, relative_path, full_path, sha256_hash,"
        " perceptual_hash, width, height, status, thumb_status, caption_status, face_status,"
        " created_at, updated_at) VALUES (?,?,?,?,?,300,300,'active','ok','ok','ok',?,?)",
        (sid, name, str(p), sha or name, phash, now, now))
    fid = cur.lastrowid
    if ocr is not None:
        db.execute("INSERT INTO image_analysis (file_id, ocr_text, object_tags_json, status,"
                   " processed_at) VALUES (?,?,?, 'done', ?)", (fid, ocr, "[]", now))
    return fid


def test_hard_delete_removes_records_keeps_originals(env):
    from photoindex.database import get_db, utcnow
    from photoindex.routes.sources import hard_delete, DeleteIn
    db = get_db(); now = utcnow()
    sid = _src(db, env, now)
    f1 = _file(db, sid, env, "a.jpg", now)
    db.execute("INSERT INTO people (display_name, created_at, updated_at) VALUES ('P',?,?)",
               (now, now))
    pid = db.execute("SELECT id FROM people").fetchone()["id"]
    db.execute("INSERT INTO faces (file_id, status, created_at) VALUES (?, 'active', ?)",
               (f1, now))
    db.execute("INSERT INTO image_people (file_id, person_id, source, created_at)"
               " VALUES (?,?, 'manual', ?)", (f1, pid, now))
    db.commit()
    original = env / "a.jpg"
    assert original.exists()

    with pytest.raises(Exception):
        hard_delete(sid, DeleteIn(confirm=False))  # must refuse without confirm

    res = hard_delete(sid, DeleteIn(confirm=True))
    assert res["deleted_files"] == 1
    assert db.execute("SELECT COUNT(*) c FROM files").fetchone()["c"] == 0
    assert db.execute("SELECT COUNT(*) c FROM faces").fetchone()["c"] == 0
    assert db.execute("SELECT COUNT(*) c FROM image_people").fetchone()["c"] == 0
    assert original.exists()  # ORIGINAL PHOTO NOT TOUCHED


def test_exact_and_near_duplicates(env):
    from photoindex.database import get_db, utcnow
    from photoindex.services import duplicates
    db = get_db(); now = utcnow()
    sid = _src(db, env, now)
    # two files with identical sha256 -> exact dup group
    _file(db, sid, env, "x1.jpg", now, sha="SAME", phash="0000000000000000")
    _file(db, sid, env, "x2.jpg", now, sha="SAME", phash="0000000000000001")
    _file(db, sid, env, "y.jpg", now, sha="OTHER", phash="ffffffffffffffff")
    db.commit()
    exact = duplicates.exact_duplicate_groups()
    assert len(exact) == 1 and exact[0]["count"] == 2
    near = duplicates.near_duplicate_groups(max_distance=6)
    # x1/x2 phashes differ by 1 bit -> same near group; y is far
    assert any(g["count"] == 2 for g in near)


def test_flag_screenshots(env):
    from photoindex.database import get_db, utcnow
    from photoindex.services import duplicates
    db = get_db(); now = utcnow()
    sid = _src(db, env, now)
    _file(db, sid, env, "Screenshot_2024.png", now)            # name heuristic
    _file(db, sid, env, "doc.png", now, ocr="Some long text with numbers 12345 here")  # OCR + no faces
    _file(db, sid, env, "photo.jpg", now)                      # plain
    db.commit()
    stats = duplicates.flag_screenshots()
    assert stats["screenshots"] == 2 and stats["not"] == 1


def test_xmp_sidecar_write_and_read(env):
    from photoindex.database import get_db, utcnow
    from photoindex.services import sidecars
    db = get_db(); now = utcnow()
    sid = _src(db, env, now)
    fid = _file(db, sid, env, "fam.jpg", now)
    db.execute("INSERT INTO people (display_name, created_at, updated_at) VALUES ('George Clooney',?,?)",
               (now, now))
    pid = db.execute("SELECT id FROM people").fetchone()["id"]
    db.execute("INSERT INTO image_people (file_id, person_id, source, created_at)"
               " VALUES (?,?, 'manual', ?)", (fid, pid, now))
    db.execute("UPDATE image_analysis SET object_tags_json='[\"tree\"]' WHERE file_id=?", (fid,))
    db.execute("INSERT OR IGNORE INTO image_analysis (file_id, object_tags_json, status,"
               " processed_at) VALUES (?, '[\"tree\"]', 'done', ?)", (fid, now))
    db.commit()
    # disabled by default -> skipped
    assert "skipped" in sidecars.write_sidecar(fid, force=False)
    # forced write
    res = sidecars.write_sidecar(fid, force=True)
    assert res.get("ok") and os.path.isfile(res["path"])
    assert "George Clooney" in res["keywords"]
    # original not modified, sidecar is separate
    assert res["path"].endswith(".jpg.xmp")
    back = sidecars.read_sidecar(str(env / "fam.jpg"))
    assert "George Clooney" in back["keywords"]
