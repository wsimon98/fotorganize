"""CLI: python -m photoindex <command>

Commands (per project spec):
  serve                          start the web server
  scan --all | --source-id N     scan sources synchronously
  thumbnails --missing [--retry-failed]
  backup                         copy app.db + docs to data/backups/<date>/
  (captions/faces/cluster-faces/export-lora arrive in Phases 3-8)
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

from . import config
from .database import get_db, init_db
from .utils.logging_setup import setup_logging


def cmd_serve(args):
    import uvicorn
    uvicorn.run("photoindex.main:app", host=config.bind_host(), port=config.PORT)


def cmd_scan(args):
    from .services import runner
    init_db()
    db = get_db()
    if args.all:
        ids = [r["id"] for r in db.execute(
            "SELECT id FROM sources WHERE status IN ('active','missing') ORDER BY id")]
        if not ids:
            print("no active sources. Add one in the web UI or via POST /api/sources")
            return
    else:
        if not args.source_id:
            print("need --all or --source-id N", file=sys.stderr)
            sys.exit(2)
        ids = [args.source_id]
    for sid in ids:
        job_id = runner.create_job("scan_source", {"source_id": sid})
        print(f"scanning source {sid} (job {job_id}) ...")
        runner.run_job_sync(job_id)
        job = db.execute("SELECT status, progress, error_message FROM jobs WHERE id=?",
                         (job_id,)).fetchone()
        print(f"  -> {job['status']}: {job['progress'] or job['error_message']}")


def cmd_thumbnails(args):
    from .services import thumbnails
    init_db()
    stats = thumbnails.generate_missing(retry_failed=args.retry_failed)
    print(f"thumbnails: {stats}")


def cmd_worker(args):
    from .workers import worker
    worker.run(once=args.once)


def cmd_captions(args):
    from .services import analysis
    init_db()
    stats = analysis.process_captions(limit=args.limit, retry_failed=args.retry_failed)
    print(f"captions: {stats}")


def cmd_faces(args):
    from .services import analysis
    init_db()
    stats = analysis.process_faces(limit=args.limit, retry_failed=args.retry_failed)
    print(f"faces: {stats}")


def cmd_cluster(args):
    from .ai import clustering
    init_db()
    stats = clustering.cluster_all()
    print(f"cluster-faces: {stats}")


def cmd_export_lora(args):
    from .services import lora_export
    init_db()
    db = get_db()
    if args.person_id:
        pid = args.person_id
    else:
        row = db.execute("SELECT id FROM people WHERE display_name=? COLLATE NOCASE",
                         (args.person,)).fetchone()
        if not row:
            print(f"person not found: {args.person}", file=sys.stderr)
            sys.exit(2)
        pid = row["id"]
    result = lora_export.export_person(pid, trigger=args.trigger, zip_output=args.zip)
    print(f"export: {result}")


def cmd_sidecars(args):
    from .services import sidecars
    init_db()
    print(sidecars.write_all(force=args.force))


def cmd_duplicates(args):
    from .services import duplicates
    init_db()
    if args.flag_screenshots:
        print("screenshots:", duplicates.flag_screenshots())
    exact = duplicates.exact_duplicate_groups()
    near = duplicates.near_duplicate_groups()
    print(f"exact duplicate groups: {len(exact)}; near-duplicate groups: {len(near)}")


def cmd_backup(args):
    init_db()
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    dest = config.PROJECT_ROOT / "data" / "backups" / stamp
    dest.mkdir(parents=True, exist_ok=True)
    db = get_db()
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(config.DB_PATH, dest / "app.db")
    for doc in ("README.md", "PROJECT_CHECKLIST.md", "HANDOFF.md", "DECISIONS.md",
                "ATTRIBUTION.md", "TROUBLESHOOTING.md"):
        p = config.PROJECT_ROOT / doc
        if p.exists():
            shutil.copy2(p, dest / doc)
    env = config.PROJECT_ROOT / ".env"
    if env.exists():
        shutil.copy2(env, dest / "dotenv.backup")
    print(f"backup written to {dest}")


def main(argv=None):
    setup_logging()
    ap = argparse.ArgumentParser(prog="photoindex")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("serve").set_defaults(fn=cmd_serve)

    p = sub.add_parser("scan")
    p.add_argument("--all", action="store_true")
    p.add_argument("--source-id", type=int)
    p.set_defaults(fn=cmd_scan)

    p = sub.add_parser("thumbnails")
    p.add_argument("--missing", action="store_true", help="(default behavior)")
    p.add_argument("--retry-failed", action="store_true")
    p.set_defaults(fn=cmd_thumbnails)

    p = sub.add_parser("worker", help="run the GPU worker loop (caption/face/cluster jobs)")
    p.add_argument("--once", action="store_true", help="run one job then exit")
    p.set_defaults(fn=cmd_worker)

    p = sub.add_parser("captions")
    p.add_argument("--pending", action="store_true", help="(default behavior)")
    p.add_argument("--limit", type=int)
    p.add_argument("--retry-failed", action="store_true")
    p.set_defaults(fn=cmd_captions)

    p = sub.add_parser("faces")
    p.add_argument("--pending", action="store_true", help="(default behavior)")
    p.add_argument("--limit", type=int)
    p.add_argument("--retry-failed", action="store_true")
    p.set_defaults(fn=cmd_faces)

    sub.add_parser("cluster-faces").set_defaults(fn=cmd_cluster)

    p = sub.add_parser("export-lora")
    p.add_argument("--person", help="person display name")
    p.add_argument("--person-id", type=int)
    p.add_argument("--trigger", default=None, help="trigger word for captions")
    p.add_argument("--zip", action="store_true", help="also produce a .zip")
    p.set_defaults(fn=cmd_export_lora)

    p = sub.add_parser("sidecars", help="write XMP sidecars (opt-in)")
    p.add_argument("--write", action="store_true", help="(default action)")
    p.add_argument("--force", action="store_true",
                   help="write even if WRITE_XMP_SIDECARS is disabled in .env")
    p.set_defaults(fn=cmd_sidecars)

    p = sub.add_parser("duplicates", help="report duplicate/near-duplicate groups")
    p.add_argument("--flag-screenshots", action="store_true")
    p.set_defaults(fn=cmd_duplicates)

    sub.add_parser("backup").set_defaults(fn=cmd_backup)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
