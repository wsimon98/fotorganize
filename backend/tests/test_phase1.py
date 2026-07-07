"""Phase 1 tests: path normalization, source lifecycle, scan idempotency,
missing-file marking, thumbnail path derivation.

Run from backend/:  venv\\Scripts\\python -m pytest tests -q
Uses a temp DB + temp photo dir; never touches data/app.db.
"""
import importlib
import os
import sys

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Reload config pointed at a temp data dir + fresh DB."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("THUMBNAIL_DIR", str(tmp_path / "thumbs"))
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("FACE_CROP_DIR", str(tmp_path / "faces"))
    monkeypatch.setenv("EXPORT_DIR", str(tmp_path / "exports"))
    from photoindex import config, database
    importlib.reload(config)
    # drop any cached thread-local connection from a previous test
    if hasattr(database._local, "conn"):
        database._local.conn.close()
        del database._local.conn
    database.init_db()
    yield tmp_path
    if hasattr(database._local, "conn"):
        database._local.conn.close()
        del database._local.conn


def make_photos(root, names):
    root.mkdir(parents=True, exist_ok=True)
    for i, name in enumerate(names):
        if name.endswith(".txt"):
            (root / name).write_text("not an image")
            continue
        img = Image.new("RGB", (64 + i, 48), (i * 40 % 255, 90, 120))
        img.save(root / name)


# ---------- path normalization ----------

def test_normalize_root():
    from photoindex.utils.paths import normalize_root
    assert normalize_root(r"z:\family\photos" + "\\") == r"Z:\family\photos"
    assert normalize_root("Z:/family/photos") == r"Z:\family\photos"
    assert normalize_root(r"\\nas-server\homes\family\photos") == \
        "\\\\nas-server\\homes\\family\\photos"
    assert normalize_root("//nas-server/homes/family/photos") == \
        "\\\\nas-server\\homes\\family\\photos"
    assert normalize_root('"C:\\Photos\\"') == r"C:\Photos"


def test_classify_path():
    from photoindex.utils.paths import classify_path
    assert classify_path("\\\\nas-server\\homes") == "unc"
    assert classify_path("C:\\Photos") == "local"


# ---------- source add / reconnect ----------

def _add_source(root):
    from photoindex.database import get_db, utcnow
    from photoindex.utils.paths import classify_path, normalize_root
    db = get_db()
    norm = normalize_root(str(root))
    now = utcnow()
    cur = db.execute(
        "INSERT INTO sources (name, root_path, path_type, status, created_at, updated_at)"
        " VALUES (?,?,?,'active',?,?)", ("test", norm, classify_path(norm), now, now))
    db.commit()
    return cur.lastrowid


def test_source_reconnect_same_path(env):
    """Re-adding same normalized path must reuse the row (API rule)."""
    from photoindex.database import get_db
    root = env / "photos"
    root.mkdir()
    sid = _add_source(root)
    db = get_db()
    # simulate the route's reconnect lookup with a differently-formatted path
    from photoindex.utils.paths import normalize_root
    other = normalize_root(str(root).replace("\\", "/") + "/")
    row = db.execute("SELECT id FROM sources WHERE root_path=?", (other,)).fetchone()
    assert row and row["id"] == sid


# ---------- scan behavior ----------

def test_scan_idempotent_and_missing_marking(env):
    from photoindex.database import get_db
    from photoindex.services.scanner import scan_source

    root = env / "photos"
    make_photos(root, ["a.jpg", "b.png", "sub_c.webp", "skip.txt"])
    (root / "sub").mkdir()
    make_photos(root / "sub", ["d.jpeg"])
    sid = _add_source(root)

    s1 = scan_source(sid)
    assert s1["new"] == 4 and s1["errors"] == 0

    db = get_db()
    count = lambda: db.execute("SELECT COUNT(*) c FROM files").fetchone()["c"]
    assert count() == 4

    # rescan: no duplicates, everything unchanged
    s2 = scan_source(sid)
    assert count() == 4
    assert s2["new"] == 0 and s2["unchanged"] == 4

    # delete one file -> marked missing, row kept
    os.remove(root / "a.jpg")
    s3 = scan_source(sid)
    assert s3["marked_missing"] == 1
    assert count() == 4
    row = db.execute("SELECT status FROM files WHERE relative_path='a.jpg'").fetchone()
    assert row["status"] == "missing"

    # restore the file -> reactivated
    make_photos(root, ["a.jpg"])
    s4 = scan_source(sid)
    assert s4["reactivated"] + s4["updated"] >= 1
    row = db.execute("SELECT status FROM files WHERE relative_path='a.jpg'").fetchone()
    assert row["status"] == "active"


def test_unreachable_source_marks_missing_keeps_files(env):
    from photoindex.database import get_db
    from photoindex.services.scanner import scan_source

    root = env / "photos2"
    make_photos(root, ["x.jpg"])
    sid = _add_source(root)
    scan_source(sid)

    # nuke the whole root (NAS unplugged)
    import shutil
    shutil.rmtree(root)
    result = scan_source(sid)
    assert result["status"] == "missing"
    db = get_db()
    src = db.execute("SELECT status FROM sources WHERE id=?", (sid,)).fetchone()
    assert src["status"] == "missing"
    f = db.execute("SELECT status FROM files WHERE source_id=?", (sid,)).fetchone()
    assert f["status"] == "active"  # untouched — root gone is not proof files are gone


def test_thumbnails_created_and_derived_path(env):
    from photoindex.database import get_db
    from photoindex.services.scanner import scan_source
    from photoindex.services.thumbnails import thumb_path

    root = env / "photos3"
    make_photos(root, ["t.jpg"])
    sid = _add_source(root)
    scan_source(sid)
    db = get_db()
    row = db.execute("SELECT sha256_hash, thumb_status FROM files WHERE source_id=?",
                     (sid,)).fetchone()
    assert row["thumb_status"] == "ok"
    p = thumb_path(row["sha256_hash"])
    assert p.exists()
    assert p.parent.name == row["sha256_hash"][:2]
