"""Phase 3-8 tests: clustering + auto-assign, people/image_people sync, LoRA export.

No GPU/models needed — face embeddings and analysis rows are inserted directly, so these
run fast and offline. Mirrors the live end-to-end test done in session 2.
"""
import importlib
import json
import os
import sys

import numpy as np
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


def _mk_file(db, root, name, now):
    """Create a source (once) + a real jpg file + its DB row. Returns file_id."""
    src = db.execute("SELECT id FROM sources LIMIT 1").fetchone()
    if not src:
        db.execute("INSERT INTO sources (name, root_path, path_type, status, created_at,"
                   " updated_at) VALUES ('t', ?, 'local', 'active', ?, ?)",
                   (str(root), now, now))
        sid = db.execute("SELECT id FROM sources LIMIT 1").fetchone()[0]
    else:
        sid = src["id"]
    p = root / name
    Image.new("RGB", (256, 256), (120, 130, 140)).save(p)
    cur = db.execute(
        "INSERT INTO files (source_id, relative_path, full_path, sha256_hash,"
        " perceptual_hash, width, height, status, thumb_status, caption_status,"
        " face_status, created_at, updated_at) VALUES (?,?,?,?,?,?,?, 'active','ok',"
        " 'ok','ok', ?, ?)",
        (sid, name, str(p), name, None, 256, 256, now, now))
    return cur.lastrowid


def _add_face(db, file_id, vec, now, person_id=None, confirmed=0):
    cur = db.execute(
        "INSERT INTO faces (file_id, embedding_vector, quality_score, status, person_id,"
        " confirmed_by_user, created_at) VALUES (?,?,?, 'active', ?, ?, ?)",
        (file_id, vec.astype("float32").tobytes(), 0.9, person_id, confirmed, now))
    return cur.lastrowid


def _unit(v):
    v = np.asarray(v, dtype="float32")
    return v / np.linalg.norm(v)


def test_clustering_groups_same_identity(env):
    from photoindex.ai import clustering
    from photoindex.database import get_db, utcnow
    db = get_db(); now = utcnow()
    # two identities, 3 photos each; embeddings near two distinct directions
    a = _unit([1, 0, 0] + [0] * 509)
    b = _unit([0, 1, 0] + [0] * 509)
    rng = np.random.default_rng(0)
    for i in range(3):
        fid = _mk_file(db, env, f"a{i}.jpg", now)
        _add_face(db, fid, _unit(a + rng.normal(0, 0.02, 512)), now)
    for i in range(3):
        fid = _mk_file(db, env, f"b{i}.jpg", now)
        _add_face(db, fid, _unit(b + rng.normal(0, 0.02, 512)), now)
    db.commit()
    stats = clustering.cluster_all()
    assert stats["clusters_created"] == 2
    sizes = sorted(r["n"] for r in db.execute(
        "SELECT (SELECT COUNT(*) FROM faces f WHERE f.cluster_id=c.id) n FROM"
        " face_clusters c WHERE status='needs_review'"))
    assert sizes == [3, 3]


def test_auto_assign_to_named_person(env):
    from photoindex.ai import clustering
    from photoindex.database import get_db, utcnow
    db = get_db(); now = utcnow()
    a = _unit([1, 0, 0] + [0] * 509)
    # one confirmed face for person "George Clooney"
    db.execute("INSERT INTO people (display_name, created_at, updated_at) VALUES"
               " ('George Clooney', ?, ?)", (now, now))
    pid = db.execute("SELECT id FROM people").fetchone()["id"]
    f0 = _mk_file(db, env, "w0.jpg", now)
    _add_face(db, f0, a, now, person_id=pid, confirmed=1)
    # a new unassigned face very close to George Clooney
    f1 = _mk_file(db, env, "w1.jpg", now)
    fid1 = _add_face(db, f1, _unit(a + np.array([0.01] + [0] * 511)), now)
    db.commit()
    stats = clustering.cluster_all()
    assert stats["auto_assigned"] == 1
    row = db.execute("SELECT person_id FROM faces WHERE id=?", (fid1,)).fetchone()
    assert row["person_id"] == pid
    # image_people link created for the new file
    assert db.execute("SELECT COUNT(*) c FROM image_people WHERE person_id=? AND file_id=?",
                      (pid, f1)).fetchone()["c"] == 1


def test_lora_export_pairs_and_manifest(env):
    from photoindex.services import lora_export
    from photoindex.database import get_db, utcnow
    db = get_db(); now = utcnow()
    db.execute("INSERT INTO people (display_name, created_at, updated_at) VALUES"
               " ('Taylor Swift', ?, ?)", (now, now))
    pid = db.execute("SELECT id FROM people").fetchone()["id"]
    for i in range(3):
        fid = _mk_file(db, env, f"g{i}.jpg", now)
        _add_face(db, fid, _unit(np.random.default_rng(i).normal(0, 1, 512)), now,
                  person_id=pid, confirmed=1)
        db.execute("INSERT INTO image_analysis (file_id, caption_short, object_tags_json,"
                   " status, processed_at) VALUES (?, 'a woman smiling', '[\"woman\"]',"
                   " 'done', ?)", (fid, now))
    db.commit()
    res = lora_export.export_person(pid, trigger="taylor_person", zip_output=True,
                                    dedupe=False, caption_style="natural")
    assert res["exported"] == 3
    outdir = env / "exports" / os.path.basename(res["output_path"])
    jpgs = sorted(outdir.glob("person_*.jpg"))
    txts = sorted(outdir.glob("person_*.txt"))
    assert len(jpgs) == 3 and len(txts) == 3
    # every jpg has a matching txt (ai-toolkit requirement)
    for j in jpgs:
        assert j.with_suffix(".txt").exists()
    # captions include trigger + scene
    assert "taylor_person" in txts[0].read_text()
    manifest = json.loads((outdir / "manifest.json").read_text())
    assert manifest["person"] == "Taylor Swift" and len(manifest["images"]) == 3
    assert (outdir / "contact_sheet.jpg").exists()
    assert os.path.exists(res["zip_path"])


def test_face_status_updates_image_people(env):
    from photoindex.routes.people import _sync_image_people_for_file
    from photoindex.database import get_db, utcnow
    db = get_db(); now = utcnow()
    db.execute("INSERT INTO people (display_name, created_at, updated_at) VALUES"
               " ('Taylor Swift', ?, ?)", (now, now))
    pid = db.execute("SELECT id FROM people").fetchone()["id"]
    fid = _mk_file(db, env, "e.jpg", now)
    face = _add_face(db, fid, _unit(np.ones(512)), now, person_id=pid, confirmed=1)
    _sync_image_people_for_file(db, fid, now)
    db.commit()
    assert db.execute("SELECT COUNT(*) c FROM image_people WHERE file_id=?",
                      (fid,)).fetchone()["c"] == 1
    # mark the face not_person -> link should disappear
    db.execute("UPDATE faces SET status='not_person', person_id=NULL WHERE id=?", (face,))
    _sync_image_people_for_file(db, fid, now)
    db.commit()
    assert db.execute("SELECT COUNT(*) c FROM image_people WHERE file_id=?",
                      (fid,)).fetchone()["c"] == 0
