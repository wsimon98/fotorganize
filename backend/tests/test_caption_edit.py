"""Tests for user caption editing: single update + bulk find/replace (the
"man" -> "George Clooney" feature), including FTS staying in sync."""
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


def _file_with_caption(db, root, name, caption, now, tags='["man"]'):
    src = db.execute("SELECT id FROM sources LIMIT 1").fetchone()
    if not src:
        db.execute("INSERT INTO sources (name, root_path, path_type, status, created_at,"
                   " updated_at) VALUES ('t', ?, 'local', 'active', ?, ?)",
                   (str(root), now, now))
    sid = db.execute("SELECT id FROM sources LIMIT 1").fetchone()["id"]
    p = root / name
    Image.new("RGB", (64, 64), (1, 2, 3)).save(p)
    cur = db.execute(
        "INSERT INTO files (source_id, relative_path, full_path, sha256_hash, status,"
        " thumb_status, caption_status, face_status, created_at, updated_at)"
        " VALUES (?,?,?,?, 'active','ok','ok','ok', ?, ?)",
        (sid, name, str(p), name, now, now))
    fid = cur.lastrowid
    db.execute("INSERT INTO image_analysis (file_id, caption_short, caption_detailed,"
               " object_tags_json, status, processed_at) VALUES (?,?,?,?, 'done', ?)",
               (fid, caption, caption + " outdoors", tags, now))
    db.execute("INSERT INTO analysis_fts (rowid, caption_short, caption_detailed,"
               " object_tags, ocr_text) VALUES (?,?,?,?, '')",
               (fid, caption, caption + " outdoors", "man", ))
    return fid


def _fts_match(db, q):
    return [r["rowid"] for r in db.execute(
        "SELECT rowid FROM analysis_fts WHERE analysis_fts MATCH ?", (q,))]


def test_update_caption_and_fts(env):
    from photoindex.database import get_db, utcnow
    from photoindex.services import captions_edit
    db = get_db(); now = utcnow()
    fid = _file_with_caption(db, env, "a.jpg", "a man in a red shirt", now)
    db.commit()
    captions_edit.update_caption(fid, caption_short="George Clooney in a red shirt")
    row = db.execute("SELECT caption_short FROM image_analysis WHERE file_id=?",
                     (fid,)).fetchone()
    assert row["caption_short"] == "George Clooney in a red shirt"
    assert fid in _fts_match(db, "Clooney")
    # short caption no longer says "man" (detailed caption was not edited, so check the column)
    assert fid not in _fts_match(db, 'caption_short: man')


def test_replace_whole_word_and_scope(env):
    from photoindex.database import get_db, utcnow
    from photoindex.services import captions_edit
    db = get_db(); now = utcnow()
    f1 = _file_with_caption(db, env, "a.jpg", "a man in a red shirt", now)
    f2 = _file_with_caption(db, env, "b.jpg", "a man walking a dog", now)
    f3 = _file_with_caption(db, env, "c.jpg", "a woman by a lake", now, tags='["woman"]')
    db.commit()

    # whole-word: 'man' must NOT hit inside 'woman'
    res = captions_edit.replace_in_captions("man", "George Clooney")
    assert res["changed"] == 2
    caps = {r["file_id"]: r["caption_short"] for r in
            db.execute("SELECT file_id, caption_short FROM image_analysis")}
    assert caps[f1] == "a George Clooney in a red shirt"
    assert caps[f2] == "a George Clooney walking a dog"
    assert caps[f3] == "a woman by a lake"  # untouched
    # FTS reflects the edit
    assert set(_fts_match(db, "Clooney")) == {f1, f2}
    # tags updated too
    import json
    tags1 = json.loads(db.execute("SELECT object_tags_json FROM image_analysis WHERE"
                                  " file_id=?", (f1,)).fetchone()["object_tags_json"])
    assert "George Clooney" in tags1


def test_replace_limited_to_file_ids(env):
    from photoindex.database import get_db, utcnow
    from photoindex.services import captions_edit
    db = get_db(); now = utcnow()
    f1 = _file_with_caption(db, env, "a.jpg", "a man on a boat", now)
    f2 = _file_with_caption(db, env, "b.jpg", "a man on a bike", now)
    db.commit()
    res = captions_edit.replace_in_captions("man", "George Clooney", file_ids=[f1])
    assert res["changed"] == 1
    caps = {r["file_id"]: r["caption_short"] for r in
            db.execute("SELECT file_id, caption_short FROM image_analysis")}
    assert caps[f1] == "a George Clooney on a boat"
    assert caps[f2] == "a man on a bike"


def test_replace_with_person_tagging(env):
    """The user-friendly flow: rename 'man' -> 'George Clooney' AND tag those images
    as that person so they show on the People page."""
    from photoindex.database import get_db, utcnow
    from photoindex.services import captions_edit
    db = get_db(); now = utcnow()
    f1 = _file_with_caption(db, env, "a.jpg", "a man in a red shirt", now)
    f2 = _file_with_caption(db, env, "b.jpg", "a man on a boat", now)
    db.commit()
    res = captions_edit.replace_in_captions("man", "George Clooney")
    tagged = captions_edit.tag_files_as_person(res["changed_file_ids"], "George Clooney")
    assert tagged["tagged"] == 2
    pid = tagged["person_id"]
    assert db.execute("SELECT display_name FROM people WHERE id=?",
                      (pid,)).fetchone()["display_name"] == "George Clooney"
    links = db.execute("SELECT file_id, source, confirmed_by_user FROM image_people"
                       " WHERE person_id=?", (pid,)).fetchall()
    assert {r["file_id"] for r in links} == {f1, f2}
    assert all(r["source"] == "caption" and r["confirmed_by_user"] == 1 for r in links)
    # idempotent: tagging again adds nothing
    assert captions_edit.tag_files_as_person([f1, f2], "george clooney")["tagged"] == 0


def test_sync_people_from_captions(env):
    """Retroactive: new captions mentioning an existing person get linked by the
    People page 'Re-scan captions' button."""
    from photoindex.database import get_db, utcnow
    from photoindex.services import captions_edit
    db = get_db(); now = utcnow()
    db.execute("INSERT INTO people (display_name, created_at, updated_at)"
               " VALUES ('George Clooney', ?, ?)", (now, now))
    f1 = _file_with_caption(db, env, "a.jpg", "George Clooney standing by a river", now)
    _file_with_caption(db, env, "b.jpg", "a dog in the grass", now)
    db.commit()
    res = captions_edit.sync_people_from_captions()
    assert res["people_updated"] == 1
    assert res["details"][0]["person"] == "George Clooney"
    assert res["details"][0]["new_links"] == 1
    pid = db.execute("SELECT id FROM people").fetchone()["id"]
    assert db.execute("SELECT file_id FROM image_people WHERE person_id=?",
                      (pid,)).fetchone()["file_id"] == f1


def test_search_export_place_or_thing(env):
    """Export images matching a caption search (e.g. 'river') as a LoRA dataset —
    the place/thing counterpart to person export."""
    from photoindex.database import get_db, utcnow
    from photoindex.services import lora_export
    import json
    db = get_db(); now = utcnow()
    _file_with_caption(db, env, "r1.jpg", "a river flowing through a forest", now)
    _file_with_caption(db, env, "r2.jpg", "a rocky river at sunset", now)
    _file_with_caption(db, env, "c1.jpg", "a red car in a driveway", now)
    db.commit()
    res = lora_export.export_search("river", q="river", trigger="rvr_style",
                                    dedupe=False)
    assert res["exported"] == 2
    outdir = env / "exports" / os.path.basename(res["output_path"])
    jpgs = sorted(outdir.glob("img_*.jpg"))
    assert len(jpgs) == 2
    for j in jpgs:
        assert j.with_suffix(".txt").exists()
    txt = jpgs[0].with_suffix(".txt").read_text()
    assert txt.startswith("rvr_style, ")
    manifest = json.loads((outdir / "manifest.json").read_text())
    assert manifest["query"] == "river" and len(manifest["images"]) == 2
    # recorded in export history with type 'search'
    assert db.execute("SELECT export_type FROM exports").fetchone()["export_type"] == "search"


def test_replace_scoped_by_query(env):
    from photoindex.database import get_db, utcnow
    from photoindex.services import captions_edit
    db = get_db(); now = utcnow()
    f1 = _file_with_caption(db, env, "a.jpg", "a man in a red shirt", now)
    f2 = _file_with_caption(db, env, "b.jpg", "a man in a blue coat", now)
    db.commit()
    res = captions_edit.replace_in_captions("man", "George Clooney", q="red")
    assert res["changed"] == 1
    caps = {r["file_id"]: r["caption_short"] for r in
            db.execute("SELECT file_id, caption_short FROM image_analysis")}
    assert "George Clooney" in caps[f1]
    assert caps[f2] == "a man in a blue coat"
