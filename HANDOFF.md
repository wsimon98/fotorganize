# HANDOFF

Last session: 2026-07-06 (session 4 — worker UI control, caption editing, GitHub prep)

## Session 4 summary (newest)

Driven by real first-use feedback: the user queued a face job and nothing happened because
no worker was running and there was no way to start one from the UI.

- **Worker control from the web UI**: Dashboard shows a live worker status chip
  (running/not + current job progress) with Start/Stop buttons. Backend:
  `services/worker_control.py` (spawn detached `python -m photoindex worker`, PID-alive
  check via ctypes on Windows, taskkill/T to stop, interrupted jobs reset to pending) +
  `routes/worker.py` (`GET /api/worker/status`, `POST /api/worker/start|stop`). The worker
  now writes/touches `data/worker.pid`. Enqueue buttons offer to start the worker if it's
  down.
- **Caption editing (single)**: ✏️ button in the image detail modal edits caption_short;
  `POST /api/files/{id}/caption`. Creates the analysis row if the image was never AI'd.
- **Bulk caption find/replace**: `POST /api/captions/replace` — replace text across ALL
  FTS matches (`q`) or an explicit `file_ids` selection; whole-word by default ("man"
  doesn't hit "woman"). Search page grew a "Fix captions" panel: find/replace inputs,
  scope = all results or manually selected tiles (Select images… toggles selection mode).
  This is the "rename 'man' to 'George Clooney' everywhere" feature. Updates FTS live.
- **Migration 4 (IMPORTANT)**: the original `analysis_fts` was contentless FTS5, which
  cannot DELETE/UPDATE — caption edits blew up. Rebuilt as a regular content-storing FTS5
  table and repopulated from image_analysis. Both FTS writers now do plain DELETE+INSERT.
- **GitHub-ready**: LICENSE (MIT + buffalo_l non-commercial note), .gitignore (excludes
  .env, data/* — verified no private data staged), .gitattributes (bat=CRLF, sh=LF),
  README rewritten with Requirements + clone-and-run install. `git init`, initial commit
  `cc83139` on branch main, 75 files. NOT yet pushed anywhere — user decides the remote.
- **LAN mode enabled earlier this session**: ALLOW_LAN=true in .env (user request),
  Windows Firewall rule "fotorganize (8420)" (Private/Domain profiles). URL for LAN
  devices: http://your-pc-ip:8420.
- Tests now **18 passing** (new tests/test_caption_edit.py: single edit + FTS sync,
  whole-word replace, file_ids scope, query scope).
- Live state at session end: user's real source scanned (289 files, 150 faces), caption
  job running via the new worker control.
- **Gender/age per face (migration 5)**: InsightFace's genderage output is now stored
  (`faces.gender` 'male'/'female', `faces.age` estimate), shown under each face crop in
  the image detail modal. Face detection was re-queued on the user's library to backfill.
- **Captions on grid tiles**: Images and Search grids now show the AI caption under each
  thumbnail (falls back to filename), full caption in the hover tooltip.
- **Worker self-heal**: on startup the worker resets any orphaned 'running' jobs to
  'pending' (a tree-killed worker used to leave jobs stuck forever; batches are resumable
  via per-file status columns so nothing reprocesses).
- **Caption→person workflow (user feedback: "not user friendly")**: renaming "man" to a
  person's name in captions now ALSO creates that person and tags the images —
  `tag_person` option on `POST /api/captions/replace` (checkbox on the Search page's
  "Name a person in these captions" panel, on by default). New
  `POST /api/captions/sync-people` + "Re-scan captions for these names" button on the
  People page retroactively links images whose captions mention a known person.
  image_people rows get source='caption'. People tiles fall back to an image thumbnail
  when there's no face-crop cover. 20 tests passing.
- **EXIF orientation fix**: phone photos were displayed sideways/upside-down. All image
  reads now apply `ImageOps.exif_transpose` (scanner/phash, thumbnails, face detection,
  captioner, LoRA export). Thumbnails + faces re-queued on the user's library to rebuild
  right-side-up; stored width/height are now post-rotation display dimensions.
  Re-detection right-side-up found **195 faces vs 150** — rotation was hiding 45 faces.
- **Cache-busting thumbnails**: browsers had cached rotated thumbs under the old
  max-age=86400 header. Thumb endpoints now send `Cache-Control: no-cache` (ETag/304
  revalidation) AND all thumb `<img>` URLs carry `?v=<files.updated_at>` so regenerated
  thumbnails always display fresh. Verified visually.
- **`database is locked` hardening**: concurrent server+worker writes killed a thumbnail
  job mid-run (left 'running' forever). Fixes: `PRAGMA busy_timeout=30000`, retry loop on
  job-status writes, and the web server now resets+auto-resumes orphaned in-process jobs
  (scan/thumbnails) at startup, mirroring the worker's self-heal. Verified: stuck job 5
  auto-resumed after restart and completed 88 remaining thumbnails.

---

## Session 3 summary (newest)

Finished the last three phases; **all phases 0-10 are now done**, 14 tests passing.

- **Phase 7 (source lifecycle):** hard-delete endpoint `POST /api/sources/{id}/delete`
  (requires `{confirm:true}`) removes every DB record for a source but NEVER touches the
  original files. UI "Delete" button with a double-confirm. (pause/deactivate/restore/
  reconnect already existed from session 1.)
- **Phase 9 (duplicates/cleanup):** `services/duplicates.py` — exact (sha256) and near
  (phash union-find) duplicate groups via `GET /api/maintenance/duplicates`; screenshot/
  meme flagging into `files.is_screenshot` (filename hints OR OCR-text-and-no-faces).
  New Duplicates UI page. LoRA export gained `exclude_screenshots`; Search gained a
  screenshots filter.
- **Phase 10 (XMP sidecars):** `services/sidecars.py` writes `<original>.xmp` with
  dc:subject + MicrosoftPhoto keywords + digiKam TagsList (person names + object tags).
  OPT-IN: `WRITE_XMP_SIDECARS` in .env (default false); the UI/CLI can force a one-off
  write. Originals are never modified. Reading parses dc:subject back.
- **Migration 3:** `files.is_screenshot`, `files.sidecar_written_at`.
- **New:** routes/maintenance.py; CLI `duplicates`, `sidecars`; tests/test_phase7910.py.

For the earlier AI pipeline work see the session-2 section below.

## What was changed in the latest session (session 2)

Built the entire AI pipeline on top of the Phase 0-1 foundation, tested it end-to-end on
the GPU, then removed all demo data.

- **DB migration 2** (backend/photoindex/database.py): added `image_analysis`, `faces`,
  `face_clusters`, `people`, `image_people`, `exports`, and an FTS5 `analysis_fts` table;
  added `caption_status` + `face_status` columns to `files`.
- **AI modules** (backend/photoindex/ai/): `captioner.py` (Florence-2), `faces.py`
  (InsightFace buffalo_l), `clustering.py` (numpy cosine + auto-assign to named people).
- **Services**: `analysis.py` (batch caption/face over pending files), `lora_export.py`
  (ai-toolkit export). `runner.py` now handles caption_batch/face_batch/cluster_faces and
  has `enqueue()` + `claim_next_worker_job()`.
- **Worker**: `workers/worker.py` + `python -m photoindex worker` — separate GPU process.
- **Routes**: analysis.py, people.py, search.py, exports.py (all mounted in main.py).
- **Frontend**: new pages Search, People, Person detail, People Review, Export, Exports;
  image-detail modal now shows caption/tags/OCR + face crops; dashboard has AI enqueue buttons.
- **Scripts**: setup_ai.bat, start_worker.bat, start_worker.sh; requirements-ai.txt.
- **Tests**: test_phase38.py (4 tests). Total suite now 10, all passing.

## What works right now (verified end-to-end on GPU this session, then data cleared)

- Captioning: Florence-2-base on CUDA fp16 produced real captions + object tags + OCR.
- Faces: InsightFace found 18 faces across 3 group photos; crops written.
- Clustering: grouped 6 identities × 3 copies exactly into 6 clusters.
- Auto-assign: after naming a cluster "George Clooney", a manually-strayed face was re-tagged to George Clooney
  on the next cluster run (this is the "remember my choices" behavior).
- People Review UI renders clusters with face crops; naming/assigning works.
- LoRA export: produced person_0001.jpg + .txt, manifest.json, contact_sheet.jpg,
  rejected/ (near-dupes correctly rejected), and a .zip.
- Full `pytest` = 10 passing.

## What does not work yet / limitations

- **Face detection runs on CPU.** onnxruntime-gpu can't locate cuDNN from torch's bundle,
  so it falls back to CPU (works, just slower on large libraries). Captioning IS on GPU.
  Fix path in TROUBLESHOOTING.md. Code already prefers CUDA and falls back gracefully.
- Phase 7 hard-delete UI, Phase 9 duplicate-groups page, Phase 10 XMP sidecars: not built.
- No auth (localhost-only by design).

## How to run

```bat
scripts\setup_windows.bat          :: once — base deps
scripts\setup_ai.bat               :: once — torch cu128 + Florence + InsightFace (~4 GB)
scripts\start_fotorganize.bat      :: web server (background) + browser
scripts\start_worker.bat           :: GPU worker, IN ITS OWN WINDOW — processes AI jobs
```

Web app: add a source → Scan. Then Dashboard buttons: "Caption pending", "Detect faces",
"Cluster faces" (these enqueue jobs; the worker window does the work). Then People Review
to name clusters, Person page to export a LoRA dataset.

CLI equivalent (no worker needed, runs synchronously):
```bat
cd backend
venv\Scripts\python -m photoindex scan --all
venv\Scripts\python -m photoindex captions --pending
venv\Scripts\python -m photoindex faces --pending
venv\Scripts\python -m photoindex cluster-faces
venv\Scripts\python -m photoindex export-lora --person "George Clooney" --trigger "clooney_person" --zip
```

## How to run a scan / How to reset test data

Scan: Sources page → Scan button, or `scripts\scan_all_sources.bat`, or CLI above.
Reset: stop server + worker, delete `data\app.db*` and the contents of `data\thumbnails`,
`data\face_crops`, `data\exports`. Person labels live in the DB, so this wipes them (that's
the point of a reset). Use `scripts\backup_database.bat` first if unsure.

## Architecture notes for the next AI

- The web process NEVER loads AI models. It only enqueues jobs (status=pending). The
  separate `worker` process claims and runs them. Keep it that way — model loading in the
  web process would block requests and duplicate VRAM.
- AI results store model_name + model_version so a newer model can re-run later (re-run by
  setting files.caption_status/face_status back to 'pending', or `--retry-failed`).
- User face assignments (confirmed_by_user=1) are ground truth and are never moved by
  re-clustering. Re-clustering only touches unassigned, unconfirmed faces.
- Embeddings are stored as float32 BLOBs; clustering reads them with numpy. If face counts
  get huge (100k+), consider sqlite-vec (noted in ATTRIBUTION) — not needed yet.

## What the next AI should do FIRST

1. Read PROJECT_CHECKLIST.md and this file. All phases 0-10 are complete.
2. `cd backend && venv\Scripts\python -m pytest tests -q` (expect 14 passing).
3. The main remaining real-world step is scanning the actual NAS
   (`\\nas-server\homes\family\photos`) — ONLY when the user says go. Then run captions +
   faces via the worker in batches and watch the Jobs page. Optional polish is listed in
   PROJECT_CHECKLIST "What to do next session".
