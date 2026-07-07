# PROJECT_CHECKLIST

Last updated: 2026-07-06 (session 4)

## Current phase

**ALL PHASES 0-10 COMPLETE + post-MVP usability round.** 18 tests passing. Session 4 added:
worker start/stop/status from the Dashboard (no terminal needed), single caption editing
(✏️ in image detail), bulk caption find/replace on the Search page (whole-word, all-results
or manual selection scope), FTS rebuilt content-storing (migration 4), and GitHub packaging
(LICENSE, .gitignore, .gitattributes, README install guide, git repo initialized — commit
cc83139, not yet pushed). LAN mode is ON for this install (firewall rule "fotorganize
(8420)", Private/Domain). Face detection runs on CPU (onnxruntime/cuDNN — see
TROUBLESHOOTING); captioning runs on GPU. User's real library: 289 images scanned,
150 faces detected, captioning in progress at session end.

### What to do next session
1. When the user approves, scan the real NAS (`\\nas-server\homes\family\photos`) — run
   captions + faces in batches via the worker; watch the Jobs page. This is the main
   remaining real-world step.
2. Optional polish: onnxruntime CUDA for faster faces (TROUBLESHOOTING); MWG face-region
   rectangles in XMP for digiKam face-box import; blur-score computation at scan time.

## Environment (verified 2026-07-06)

- Python 3.13.5 on Windows 11 (`python` on PATH)
- npm 11.10.1 (not currently needed — frontend has no build step)
- GPU: NVIDIA RTX 5060 Ti 16GB (`nvidia-smi` works; CUDA-from-Python not yet tested — needed in Phase 3/4)
- Photo source reachable as BOTH `Z:\family\photos` and `\\nas-server\homes\family\photos`
- Project root: `F:\fotorganize`

## Finished tasks

### Phase 0
- [x] Folder structure created at F:\fotorganize
- [x] All 6 doc files created
- [x] .env.example created
- [x] setup_windows.bat (venv + pip install + env checks)
- [x] run_server.bat, scan_all_sources.bat, backup_database.bat, export_person_lora.bat (placeholder)
- [x] start_fotorganize.bat / stop_fotorganize.bat — background start (PID file data\fotorganize.pid + port-8420 fallback kill), tested full cycle 2026-07-06
- [x] Linux .sh mirrors: setup_linux.sh, start_fotorganize.sh, stop_fotorganize.sh, scan_all_sources.sh (bash -n checked; untested on real Linux — note: Windows root_paths in DB would need re-adding as mount paths after a migration)
- [x] Python/npm/GPU/drive checks done

### Phase 1
- [x] SQLite schema: sources, files, jobs (+ schema_version) — see docs/database_schema.md
- [x] API: add/list sources, change source status (active/paused/inactive/missing), trigger scan
- [x] Scanner: walks source, sha256 + perceptual hash (ImageHash), EXIF (size, date_taken, camera, GPS), upsert by (source_id, relative_path)
- [x] Re-scan does not duplicate rows (verified by test)
- [x] Missing files marked `missing`, not deleted (verified by test)
- [x] Re-adding a source with the same root_path reconnects the old source row (no data loss)
- [x] Thumbnails (512px JPEG, sha256-named under data/thumbnails/ab/<sha>.jpg), generated during scan + on-demand
- [x] Web UI: Dashboard, Sources page (add/scan/pause/etc.), Images grid with thumbnails, Jobs page
- [x] CLI: `python -m photoindex scan --all | --source-id N`, `thumbnails --missing`, `backup`
- [x] Logging to console + data/logs/app.log; scan logs data/logs/scan_*.log

### Phase 3-6 + 8 (session 2)
- [x] Migration 2: image_analysis, faces, face_clusters, people, image_people, exports, analysis_fts (FTS5); files gained caption_status/face_status
- [x] Florence-2-base captioning (short + detailed + object tags + OCR) on GPU — verified real captions ("group of people playing poker", tags man/woman/table)
- [x] InsightFace buffalo_l face detection + 512-d embeddings + content-addressed face crops — verified 18 faces on 3 group photos
- [x] Clustering (numpy cosine, greedy) — verified 6 people × 3 copies grouped exactly
- [x] Auto-assign new faces to named people (the "remember my choices" behavior) — verified stray face re-tagged to George Clooney
- [x] Separate GPU worker process (`python -m photoindex worker`) claiming jobs from the jobs table
- [x] People Review UI (clusters, name/assign/merge/mark-not-person/bad-crop), People page, Person detail, Search (FTS over caption/tags/OCR + person/date/dimensions), Exports page
- [x] LoRA export (ai-toolkit format): image+.txt pairs, manifest.json, contact_sheet.jpg, rejected/, zip, dedupe — verified valid output
- [x] CLI: worker, captions, faces, cluster-faces, export-lora
- [x] Scripts: setup_ai.bat, start_worker.bat/.sh
- [x] Tests: test_phase38.py (clustering, auto-assign, export pairs+manifest, image_people sync) — 4 tests, all passing

### Phase 7 / 9 / 10 (session 3)
- [x] Phase 7: source hard-delete (`POST /api/sources/{id}/delete`, confirm=true required) — removes all DB records, never touches original files; UI "Delete" button with double-confirm. Deactivate/pause/restore already existed.
- [x] Phase 9: duplicate detection — exact (sha256) + near (phash union-find), `GET /api/maintenance/duplicates`; screenshot/meme flagging (`files.is_screenshot`, filename + OCR/no-face heuristic); Duplicates UI page; LoRA export gained `exclude_screenshots`; Search gained a screenshots filter.
- [x] Phase 10: XMP sidecars (`services/sidecars.py`) — read + write `<original>.xmp` with dc:subject + MicrosoftPhoto + digiKam TagsList; OPT-IN via `WRITE_XMP_SIDECARS` (default false); originals never modified; `POST /api/maintenance/write-sidecars`, CLI `sidecars --write [--force]`.
- [x] Migration 3: files.is_screenshot, files.sidecar_written_at
- [x] Tests: test_phase7910.py (hard-delete keeps originals, exact+near dupes, screenshot flag, sidecar write/read) — 4 tests

## Active tasks

- (none — MVP complete)

## Blocked tasks

- (none)

## Next exact steps (for next session / next AI)

1. Read HANDOFF.md.
2. Run the tests to confirm the environment: `cd backend && venv\Scripts\python -m pytest tests -q` (expect 10 passing).
3. Optional wins: onnxruntime CUDA for faster faces (TROUBLESHOOTING), Phase 9 duplicate-groups page, Phase 10 XMP sidecars.
4. Do NOT run a full NAS scan until the user says so.

## Test status

- `backend/tests/` — 10 tests PASSING (`venv\Scripts\python -m pytest tests -q` from backend/)
  - test_phase1.py (6): path normalization, source add/dedup/reconnect, scan idempotency, missing-file marking, thumbnail path derivation.
  - test_phase38.py (4): clustering groups identity, auto-assign to named person, LoRA export image/.txt pairs + manifest, image_people sync on face status change.
  - test_phase7910.py (4): hard-delete removes records but keeps originals, exact+near duplicate groups, screenshot flagging, XMP sidecar write/read.
- End-to-end GPU test (session 2, manual): scan → caption → faces → cluster → name → auto-assign → export, all verified working. Demo data has since been removed.

## Commands that currently work

```
scripts\setup_windows.bat                  :: base deps (FastAPI, Pillow, etc.)
scripts\setup_ai.bat                        :: AI deps (torch cu128, Florence, InsightFace)
scripts\start_fotorganize.bat              :: background web server + browser
scripts\stop_fotorganize.bat
scripts\start_worker.bat                    :: GPU worker (processes caption/face/cluster jobs) - run in its own window
scripts\run_server.bat                     :: foreground server, http://127.0.0.1:8420
scripts\scan_all_sources.bat
scripts\backup_database.bat
cd backend && venv\Scripts\python -m photoindex scan --all | --source-id N
                                       ... thumbnails --missing
                                       ... captions --pending [--limit N] [--retry-failed]
                                       ... faces --pending [--limit N] [--retry-failed]
                                       ... cluster-faces
                                       ... worker [--once]
                                       ... export-lora --person "George Clooney" --trigger "clooney_person" --zip
                                       ... duplicates [--flag-screenshots]
                                       ... sidecars --write [--force]
                                       ... backup
```

## Commands that failed and why (all fixed)

- `pip install insightface` clobbered torch cu128 with a CPU build → setup_ai.bat re-pins cu128 last.
- `onnxruntime` + `onnxruntime-gpu` both installed → conflict; keep only onnxruntime-gpu.
- SQLite `HAVING` without `GROUP BY` → 500 on /api/clusters; fixed with subquery wrapper.
- See TROUBLESHOOTING.md for all of these.

## Known bugs / limitations

- Face detection runs on CPU (onnxruntime can't find cuDNN from torch's bundle). Works, just slower on big libraries. Captioning is on GPU.
- Florence-2 downloads remote code on first run (trust_remote_code=True) — expected.
