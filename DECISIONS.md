# DECISIONS

Record of all major technical choices. Newest at top.

---

## 2026-07-06 (session 4) — Worker is controllable from the web UI via PID file

- **Decision:** The worker writes `data/worker.pid` (touched each poll). The web app spawns
  it detached (`subprocess.Popen`, CREATE_NO_WINDOW on Windows) and stops it by tree-kill.
  Status = PID alive (ctypes OpenProcess on Windows). Stopping resets any 'running' job to
  'pending' so nothing is lost.
- **Reason:** First real use showed jobs sitting 'pending' forever with no indication the
  worker wasn't running and no way to start it without a terminal. A separate service
  manager (NSSM, Windows service) is more robust but adds install friction for a GitHub
  audience.
- **Consequences:** if the machine reboots, the worker doesn't auto-start — the Dashboard
  makes that obvious and one click fixes it.
- **Files:** services/worker_control.py, routes/worker.py, workers/worker.py

## 2026-07-06 (session 4) — FTS rebuilt as content-storing (migration 4)

- **Decision:** Replace the contentless `analysis_fts` with a regular FTS5 table.
- **Reason:** Contentless FTS5 cannot DELETE/UPDATE rows, which user caption editing
  requires. The failure was silent until the first re-index of an existing row.
- **Consequences:** captions/tags/OCR text is stored twice (image_analysis + FTS). At
  personal-library scale that's megabytes — fine. Migration repopulates automatically.
- **Files:** database.py (migration 4), services/captions_edit.py, services/analysis.py

## 2026-07-06 (session 4) — Bulk caption replace is whole-word, scoped by FTS query or selection

- **Decision:** `replace_in_captions(find, replace, file_ids|q)` uses regex with `\b`
  boundaries by default and case-insensitive matching; scope is an explicit id list (UI
  selection) or every FTS match of a query ("select all results"), never silently global
  unless neither is given.
- **Reason:** "man" must not corrupt "woman"/"human"; the two scopes map exactly to the
  user's workflows (fix these selected images / fix everything this search found).
- **Files:** services/captions_edit.py, routes/analysis.py, frontend Search page

---

## 2026-07-06 (session 3) — XMP sidecars: keyword-based, no MWG face regions

- **Decision:** Write person names + object tags as XMP keywords (dc:subject +
  MicrosoftPhoto:LastKeywordXMP + digiKam:TagsList `People/<Name>`). Do NOT write MWG
  face-region rectangles. Sidecar is `<original>.xmp`; opt-in via WRITE_XMP_SIDECARS.
- **Reason:** Keywords are read by every major tool (Windows, Lightroom, digiKam). MWG
  regions are complex and tool-specific — not worth it for a backup/portability feature.
- **Consequences:** other apps see people as keyword tags, not clickable face boxes. If face
  boxes in digiKam are wanted later, add MWG regions (noted in PROJECT_CHECKLIST).
- **Files:** backend/photoindex/services/sidecars.py

## 2026-07-06 (session 3) — Screenshot detection is a stored heuristic flag

- **Decision:** `files.is_screenshot` (NULL=unevaluated, 0/1). Heuristic: filename matches
  screenshot/capture/snip, OR (has OCR text >15 chars AND zero faces). Computed on demand by
  `flag_screenshots()`, not at scan time.
- **Reason:** Cheap, no model; good enough to power "screenshots only" search and exclude
  memes/screenshots from LoRA exports. On-demand so it can use caption/OCR results that
  arrive after scanning.
- **Consequences:** must re-run after captioning for the OCR signal to count. Documented.
- **Files:** backend/photoindex/services/duplicates.py

## 2026-07-06 (session 3) — Hard-delete removes DB records only, never files

- **Decision:** `POST /api/sources/{id}/delete` (confirm required) deletes the source's DB
  rows (files, faces, captions, links, fts) but never deletes photos on disk. Deactivate is
  offered first as the safer option.
- **Reason:** Core safety rule: never delete originals. Double-confirm in the UI. Reconnect-
  on-re-add covers the "I removed it by accident" case for deactivate, not hard-delete.
- **Files:** backend/photoindex/routes/sources.py

---

## 2026-07-06 (session 2) — Face detection runs on CPU (onnxruntime/cuDNN); captioning on GPU

- **Decision:** Ship with InsightFace on CPUExecutionProvider; don't block on getting
  onnxruntime CUDA working. Captioning (Florence-2 via torch) stays on GPU.
- **Reason:** onnxruntime-gpu 1.27 needs cuDNN 9 DLLs it can't find from torch's bundle;
  fixing it is a rabbit hole (matching cuDNN wheel + PATH). CPU buffalo_l is fast enough for
  a personal library, and the code already prefers CUDA and falls back gracefully.
- **Alternatives:** install standalone nvidia-cudnn-cu12 wheel + preload (may still mismatch);
  build a custom onnxruntime. Both cost more than they're worth right now.
- **Consequences:** large-library face detection is slower. Documented in TROUBLESHOOTING with
  the fix path. `faces.py` tries `os.add_dll_directory(torch/lib)` + `onnxruntime.preload_dlls()`
  best-effort.
- **Files:** backend/photoindex/ai/faces.py, TROUBLESHOOTING.md

## 2026-07-06 (session 2) — Separate GPU worker process, not in the web server

- **Decision:** AI jobs (caption_batch/face_batch/cluster_faces) run in `python -m photoindex
  worker`, a separate process that claims pending rows from the `jobs` table. The web app only
  enqueues. Scan/thumbnail jobs still run in the web process thread (cheap, no models).
- **Reason:** Model loading (Florence ~1GB, buffalo_l) must not block HTTP requests or live in
  the request process. A DB-backed queue keeps it resumable and lets CLI run the same code.
- **Consequences:** the user runs the worker in its own window (start_worker.bat). Jobs sit
  `pending` until the worker is up — the UI says so.
- **Files:** backend/photoindex/workers/worker.py, services/runner.py (enqueue, claim_next_worker_job)

## 2026-07-06 (session 2) — All Phase 3-8 tables in one migration (migration 2)

- **Decision:** Added every remaining table (image_analysis, faces, face_clusters, people,
  image_people, exports, analysis_fts) in a single migration rather than one per phase.
- **Reason:** The schema was designed together and FKs cross tables (faces→people, faces→
  clusters). One migration keeps the empty DB stable and avoids churn. Since there was no
  production data yet, no downside.
- **Consequences:** future schema changes still go in NEW migrations (never edit migration 2).
- **Files:** backend/photoindex/database.py

## 2026-07-06 (session 2) — Clustering: numpy greedy cosine + auto-assign, no sklearn

- **Decision:** Greedy single-pass clustering over L2-normalized ArcFace embeddings (cosine =
  dot product), threshold in clustering.py. Before clustering, unassigned faces near a NAMED
  person's confirmed faces are auto-linked to that person.
- **Reason:** Avoids adding scikit-learn; fine for a personal library's face counts. Auto-assign
  implements the spec's "remember choices and apply to similar faces".
- **Alternatives:** DBSCAN/HDBSCAN (better on big/noisy sets — revisit if needed); sqlite-vec
  ANN (only needed at very large scale).
- **Consequences:** thresholds (ASSIGN_THRESHOLD 0.42, CLUSTER_THRESHOLD 0.40) are constants for
  now; move to config if they need tuning. User-confirmed faces are never moved.
- **Files:** backend/photoindex/ai/clustering.py

## 2026-07-06 (session 2) — Florence-2-base, transformers pinned <4.50, trust_remote_code

- **Decision:** Default caption model microsoft/Florence-2-base; transformers pinned >=4.44,<4.50
  (4.49 installed and verified working with Florence's remote code on Blackwell).
- **Reason:** base fits VRAM easily and is fast; Florence needs trust_remote_code=True. Newer
  transformers (4.50+) have broken Florence's bundled remote code in the past, hence the ceiling.
- **Consequences:** first run downloads model + remote code from HF (the one allowed network use).
  `CAPTION_MODEL` in .env can switch to Florence-2-large.
- **Files:** backend/photoindex/ai/captioner.py, backend/requirements-ai.txt

---

## 2026-07-06 — Thumbnail naming by content hash (sha256), not file id

- **Decision:** Thumbnails live at `data/thumbnails/<sha256[0:2]>/<sha256>.jpg` (512px max, JPEG q85).
- **Reason:** Content-addressed names survive rescans, file moves, and DB rebuilds; exact duplicates share one thumbnail for free.
- **Alternatives:** file-id-based names (breaks if DB is rebuilt); mirroring source folder structure (leaks paths, breaks on rename).
- **Consequences:** thumbnail path is *derived*, not stored — `thumb_status` column on `files` tracks ok/failed/pending.
- **Files:** backend/photoindex/services/thumbnails.py

## 2026-07-06 — Plain HTML/JS frontend served by FastAPI (no React/Vite build)

- **Decision:** Frontend is static files in `frontend/src/` (hash-routed single page, vanilla JS), mounted by FastAPI. No npm build step.
- **Reason:** Faster to build, zero toolchain, trivially debuggable by a less capable AI, meets "no fancy UI until core functions work". npm is available if we ever outgrow this.
- **Alternatives:** React/Vite (more moving parts, build step, node_modules on a NAS-adjacent project).
- **Consequences:** If UI complexity grows (People Review drag/drop in Phase 5), we may introduce a small lib (e.g. preact via single file) — revisit then.
- **Files:** frontend/src/*, backend/photoindex/main.py

## 2026-07-06 — Python package named `photoindex`, inside `backend/`

- **Decision:** Package is `backend/photoindex/` (not `backend/app/` as in the original layout sketch).
- **Reason:** The spec requires the CLI `python -m photoindex ...`; naming the package that way gives the CLI for free with no shim module.
- **Alternatives:** `backend/app/` + separate `photoindex` alias package (two names for one thing = confusion for future AI).
- **Consequences:** Run server as `uvicorn photoindex.main:app` from `backend/`. All internal imports are `photoindex.*`.
- **Files:** backend/photoindex/*

## 2026-07-06 — SQLite in WAL mode, schema versioning via `schema_version` table

- **Decision:** SQLite at `data/app.db`, WAL journal mode, `PRAGMA foreign_keys=ON`, tiny integer migration system in database.py.
- **Reason:** WAL lets the web server read while a scan writes. Migrations = numbered functions, so later phases add tables without wrecking data.
- **Alternatives:** SQLAlchemy+Alembic (heavier than needed at this stage; can adopt later without breaking `.db` file).
- **Consequences:** All schema changes MUST go through a new migration in database.py — never edit old migrations.
- **Files:** backend/photoindex/database.py, docs/database_schema.md

## 2026-07-06 — Jobs: SQLite jobs table + in-process background threads (no worker process yet)

- **Decision:** Scans/thumbnail jobs are rows in `jobs`; the FastAPI process runs them in a daemon thread (one scan at a time via a lock). CLI runs the same functions synchronously.
- **Reason:** Single-user local app; simplest thing that gives resumability + a Jobs page. Spec allows "simple job queue table in SQLite at first".
- **Alternatives:** separate worker process (planned for Phase 3/4 when GPU AI jobs arrive — model loading should not live inside the web process).
- **Consequences:** Phase 3 will add `python -m photoindex worker` as a separate process claiming `jobs` rows; API stays the same.
- **Files:** backend/photoindex/services/runner.py

## 2026-07-06 — Re-adding a source with the same path reconnects the old record

- **Decision:** `POST /api/sources` first looks for an existing source with the same normalized `root_path`; if found (any status) it reactivates that row instead of inserting.
- **Reason:** Spec rule: re-adding a source must restore prior tags/labels. Files reference source_id, so reusing the row keeps everything.
- **Consequences:** root_path is normalized (case-folded drive letter, trailing slash stripped, `\` canonical) before compare — see utils/paths.py.
- **Files:** backend/photoindex/routes/sources.py, utils/paths.py

## 2026-07-06 — Port 8420, bind 127.0.0.1 default

- **Decision:** Default `HOST=127.0.0.1`, `PORT=8420`. `ALLOW_LAN=true` in .env switches to 0.0.0.0 (with startup warning in log).
- **Reason:** Privacy-first per spec; 8420 avoids common dev ports and this machine's existing services (3100, 8188, 8787, 1234).
- **Files:** backend/photoindex/config.py, .env.example
