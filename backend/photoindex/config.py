"""Config loaded from <project root>/.env (falls back to defaults).

Project root = parent of backend/. All relative paths resolve against it.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def _path(key: str, default: str) -> Path:
    p = Path(os.getenv(key, default))
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p


def _bool(key: str, default: bool) -> bool:
    return os.getenv(key, str(default)).strip().lower() in ("1", "true", "yes", "on")


HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8420"))
ALLOW_LAN = _bool("ALLOW_LAN", False)

DB_PATH = _path("DB_PATH", "data/app.db")
THUMBNAIL_DIR = _path("THUMBNAIL_DIR", "data/thumbnails")
FACE_CROP_DIR = _path("FACE_CROP_DIR", "data/face_crops")
EXPORT_DIR = _path("EXPORT_DIR", "data/exports")
LOG_DIR = _path("LOG_DIR", "data/logs")
FRONTEND_DIR = PROJECT_ROOT / "frontend" / "src"

SCAN_BATCH_SIZE = int(os.getenv("SCAN_BATCH_SIZE", "200"))
THUMBNAIL_SIZE = int(os.getenv("THUMBNAIL_SIZE", "512"))

GPU_ENABLED = _bool("GPU_ENABLED", True)
CAPTION_MODEL = os.getenv("CAPTION_MODEL", "microsoft/Florence-2-base")
FACE_MODEL = os.getenv("FACE_MODEL", "buffalo_l")

SHOW_INACTIVE_SOURCES = _bool("SHOW_INACTIVE_SOURCES", False)
WRITE_XMP_SIDECARS = _bool("WRITE_XMP_SIDECARS", False)

# extensions indexed in Phase 1 (lowercase, with dot)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def bind_host() -> str:
    return "0.0.0.0" if ALLOW_LAN else HOST


def ensure_dirs() -> None:
    for d in (DB_PATH.parent, THUMBNAIL_DIR, FACE_CROP_DIR, EXPORT_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)
