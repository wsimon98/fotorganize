"""SQLite connection + tiny migration system.

Rules (see DECISIONS.md):
- WAL mode so the web server can read during scans.
- Never edit an existing migration; add a new numbered one.
- Rows are marked (status columns), never deleted, when things go missing.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone

from . import config

_local = threading.local()


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_db() -> sqlite3.Connection:
    """One connection per thread (sqlite3 objects are not thread-safe)."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        config.ensure_dirs()
        conn = sqlite3.connect(config.DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        # web server and worker are separate processes writing the same DB; wait for
        # each other's write locks instead of raising 'database is locked'
        conn.execute("PRAGMA busy_timeout=30000")
        _local.conn = conn
    return conn


MIGRATIONS: list[str] = [
    # 1 — Phase 1 core tables
    """
    CREATE TABLE sources (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        root_path TEXT NOT NULL UNIQUE,          -- normalized (utils.paths.normalize_root)
        path_type TEXT NOT NULL,                 -- local | mapped | unc
        status TEXT NOT NULL DEFAULT 'active',   -- active | paused | inactive | missing
        last_scan_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE files (
        id INTEGER PRIMARY KEY,
        source_id INTEGER NOT NULL REFERENCES sources(id),
        relative_path TEXT NOT NULL,             -- forward slashes, relative to source root
        full_path TEXT NOT NULL,                 -- OS-native absolute path at last scan
        file_size INTEGER,
        modified_time TEXT,
        sha256_hash TEXT,
        perceptual_hash TEXT,
        mime_type TEXT,
        width INTEGER,
        height INTEGER,
        date_taken TEXT,
        camera_model TEXT,
        gps_lat REAL,
        gps_lon REAL,
        status TEXT NOT NULL DEFAULT 'active',   -- active | missing | deleted | ignored
        thumb_status TEXT NOT NULL DEFAULT 'pending',  -- pending | ok | failed
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (source_id, relative_path)
    );
    CREATE INDEX idx_files_sha256 ON files(sha256_hash);
    CREATE INDEX idx_files_status ON files(status);
    CREATE INDEX idx_files_source ON files(source_id);

    CREATE TABLE jobs (
        id INTEGER PRIMARY KEY,
        job_type TEXT NOT NULL,                  -- scan_source | thumbnails | ...
        status TEXT NOT NULL DEFAULT 'pending',  -- pending | running | done | failed
        payload_json TEXT,
        error_message TEXT,
        progress TEXT,                           -- free-text progress e.g. "1234 files"
        created_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT
    );
    """,
    # 2 — Phase 3-8 AI tables (captions, faces, clustering, people, exports)
    """
    -- per-file AI processing state, so the worker can find pending work fast
    ALTER TABLE files ADD COLUMN caption_status TEXT NOT NULL DEFAULT 'pending';
    ALTER TABLE files ADD COLUMN face_status TEXT NOT NULL DEFAULT 'pending';
    CREATE INDEX idx_files_caption_status ON files(caption_status);
    CREATE INDEX idx_files_face_status ON files(face_status);

    -- Phase 3: captions / tags / OCR
    CREATE TABLE image_analysis (
        id INTEGER PRIMARY KEY,
        file_id INTEGER NOT NULL REFERENCES files(id),
        caption_short TEXT,
        caption_detailed TEXT,
        object_tags_json TEXT,          -- JSON list of detected object labels
        scene_tags_json TEXT,           -- JSON list (reserved; may reuse object tags)
        ocr_text TEXT,
        model_name TEXT,
        model_version TEXT,
        analysis_version INTEGER DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'done',   -- done | failed
        error_message TEXT,
        processed_at TEXT,
        UNIQUE (file_id)
    );

    -- Full-text search over captions + tags + OCR (Phase 6)
    CREATE VIRTUAL TABLE analysis_fts USING fts5(
        caption_short, caption_detailed, object_tags, ocr_text,
        content='', tokenize='porter unicode61'
    );

    -- Phase 5: people (named), created before faces so FK targets exist
    CREATE TABLE people (
        id INTEGER PRIMARY KEY,
        display_name TEXT NOT NULL UNIQUE,
        relationship TEXT,
        cover_face_id INTEGER,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    -- Phase 5: auto clusters of similar faces
    CREATE TABLE face_clusters (
        id INTEGER PRIMARY KEY,
        auto_label TEXT,
        status TEXT NOT NULL DEFAULT 'needs_review',  -- needs_review | named | split_needed | rejected
        confidence REAL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    -- Phase 4: detected faces
    CREATE TABLE faces (
        id INTEGER PRIMARY KEY,
        file_id INTEGER NOT NULL REFERENCES files(id),
        face_crop_path TEXT,            -- derived path, stored for convenience
        bounding_box_json TEXT,         -- {"x1","y1","x2","y2"}
        landmarks_json TEXT,
        embedding_vector BLOB,          -- float32 ArcFace embedding (512-d)
        quality_score REAL,
        blur_score REAL,
        pose_score REAL,
        cluster_id INTEGER REFERENCES face_clusters(id),
        person_id INTEGER REFERENCES people(id),
        confirmed_by_user INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'active',  -- active | rejected | not_person | bad_crop
        model_name TEXT,
        model_version TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX idx_faces_file ON faces(file_id);
    CREATE INDEX idx_faces_cluster ON faces(cluster_id);
    CREATE INDEX idx_faces_person ON faces(person_id);
    CREATE INDEX idx_faces_status ON faces(status);

    -- Phase 5: person <-> image links (a person appears in an image)
    CREATE TABLE image_people (
        id INTEGER PRIMARY KEY,
        file_id INTEGER NOT NULL REFERENCES files(id),
        person_id INTEGER NOT NULL REFERENCES people(id),
        confidence REAL,
        source TEXT NOT NULL DEFAULT 'face_match',  -- face_match | manual | inferred
        confirmed_by_user INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        UNIQUE (file_id, person_id)
    );
    CREATE INDEX idx_image_people_person ON image_people(person_id);
    CREATE INDEX idx_image_people_file ON image_people(file_id);

    -- Phase 8: LoRA export history
    CREATE TABLE exports (
        id INTEGER PRIMARY KEY,
        person_id INTEGER REFERENCES people(id),
        export_type TEXT,
        settings_json TEXT,
        output_path TEXT,
        zip_path TEXT,
        created_at TEXT NOT NULL
    );
    """,
    # 3 — Phase 9/10 flags
    """
    -- Phase 9: screenshot/meme heuristic result. NULL = not evaluated, 0/1 = result.
    ALTER TABLE files ADD COLUMN is_screenshot INTEGER DEFAULT NULL;
    -- Phase 10: last time we wrote an XMP sidecar for this file (NULL = never)
    ALTER TABLE files ADD COLUMN sidecar_written_at TEXT DEFAULT NULL;
    """,
    # 4 — rebuild FTS as a regular (content-storing) table: the original contentless
    # table cannot DELETE/UPDATE rows, which caption editing needs. Repopulates from
    # image_analysis so existing captions stay searchable.
    """
    DROP TABLE IF EXISTS analysis_fts;
    CREATE VIRTUAL TABLE analysis_fts USING fts5(
        caption_short, caption_detailed, object_tags, ocr_text,
        tokenize='porter unicode61'
    );
    INSERT INTO analysis_fts (rowid, caption_short, caption_detailed, object_tags, ocr_text)
        SELECT file_id, COALESCE(caption_short,''), COALESCE(caption_detailed,''),
               COALESCE(object_tags_json,''), COALESCE(ocr_text,'')
        FROM image_analysis WHERE status='done';
    """,
    # 5 — per-face gender + age estimate (InsightFace genderage model output)
    """
    ALTER TABLE faces ADD COLUMN gender TEXT DEFAULT NULL;   -- 'male' | 'female' | NULL
    ALTER TABLE faces ADD COLUMN age INTEGER DEFAULT NULL;   -- rough estimate
    """,
]


def init_db() -> None:
    db = get_db()
    db.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
    )
    row = db.execute("SELECT MAX(version) v FROM schema_version").fetchone()
    current = row["v"] or 0
    for i, sql in enumerate(MIGRATIONS, start=1):
        if i > current:
            db.executescript(sql)
            db.execute("INSERT INTO schema_version (version) VALUES (?)", (i,))
            db.commit()
