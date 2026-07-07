from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .. import config

_configured = False


def setup_logging() -> None:
    global _configured
    if _configured:
        return
    config.ensure_dirs()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(sh)
    fh = RotatingFileHandler(
        config.LOG_DIR / "app.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)
    _configured = True


def scan_logger(job_id: int) -> logging.Logger:
    """Separate log file per scan job."""
    logger = logging.getLogger(f"scan.job{job_id}")
    if not logger.handlers:
        fh = logging.FileHandler(config.LOG_DIR / f"scan_{job_id}.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
        logger.addHandler(fh)
    return logger
