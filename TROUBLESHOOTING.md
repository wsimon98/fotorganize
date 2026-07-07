# TROUBLESHOOTING

Known problems and fixes. Add every real error you hit, with the fix.

## Setup / install

- **`python` not found in .bat** — Windows Store alias stub. Fix: install real Python or run `where python` and put the real one first on PATH. This machine: Python 3.13.5 works.
- **pip install slow/fails on Pillow** — Python 3.13 needs recent Pillow (>=10.4). requirements.txt already pins a compatible floor.
- **venv activation in PowerShell blocked** — `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or use the .bat scripts (cmd) instead.

## Windows paths / network shares

- **UNC paths (`\\nas-server\homes\family\photos`)** work directly with Python's pathlib/os — no drive mapping required. Both the UNC form and `Z:\family\photos` point at the same NAS folder on this machine; **add only ONE of them as a source** or you will index everything twice (different paths, but sha256 dedup will reveal it).
- **`Z:` missing after reboot** — mapped drives are per-login-session. Prefer adding the UNC path as the source; it is stable.
- **Scan says source `missing`** — the root path was unreachable at scan time (NAS asleep/offline). Nothing was deleted; set status back to active and rescan when the NAS is up.
- **Long paths (>260 chars)** — enable Windows long paths (`HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled=1`) if scanner logs `FileNotFoundError` on paths that exist.
- **cmd.exe cannot `cd` to a UNC path** — irrelevant to the app (Python handles UNC fine), but explains odd behavior if you poke around in a terminal.

## Database

- **`database is locked`** — normally prevented by WAL mode. If it happens: only one scan runs at a time by design; check for a crashed process holding the file (close extra terminals, or reboot). Never delete `app.db-wal` while the server is running.
- **Reset test data** — stop server, delete `data\app.db*` and `data\thumbnails\*`. Sources/tags are lost (that's the point of a reset). Backups: `scripts\backup_database.bat` → `data\backups\`.

## GPU / CUDA (Phase 3+)  — verified working, session 2

- GPU is an RTX 5060 Ti (Blackwell, sm_120). **Older PyTorch CUDA builds do NOT support Blackwell** — use cu128 wheels (`pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128`). Verified: torch 2.11.0+cu128, `cuda.is_available()` = True. Captioning runs on GPU.
- **torch gets clobbered by insightface.** `pip install insightface` (or the AI requirements) pulls a CPU `torch` from PyPI and UNINSTALLS the cu128 build. Fix: install AI deps, then re-run the cu128 install LAST. `scripts\setup_ai.bat` does this automatically (step 4 re-pins cu128).
- **`onnxruntime` and `onnxruntime-gpu` conflict.** Both use the same `import onnxruntime` package dir. If both are installed, uninstalling one deletes shared files and you get `module 'onnxruntime' has no attribute 'get_available_providers'`. Fix: `pip uninstall -y onnxruntime onnxruntime-gpu` then `pip install onnxruntime-gpu`. Keep ONLY onnxruntime-gpu.
- **Face detection falls back to CPU** even with onnxruntime-gpu installed and `CUDAExecutionProvider` listed. onnxruntime can't load cuDNN 9 DLLs from torch's bundle, so it silently uses CPU. This is currently accepted (buffalo_l on CPU is fine for a personal library). To try to fix: `pip install nvidia-cudnn-cu12 nvidia-cublas-cu12` then rely on `onnxruntime.preload_dlls()` (already called in faces.py), or add the cuDNN bin dir to PATH. Verify with a face run and look for `Applied providers: ['CUDAExecutionProvider', ...]` instead of `['CPUExecutionProvider']`.

## Model downloads (Phase 3+)

- Hugging Face downloads go to `%USERPROFILE%\.cache\huggingface` by default. Set `HF_HOME=F:\fotorganize\data\models` in .env if C: space is a concern. Downloading model weights is the one approved kind of network access — never image data.

## Images / thumbnails

- **Photos show sideways or upside-down** — fixed 2026-07-07: all image reads apply EXIF
  orientation (`ImageOps.exif_transpose`). If you still see rotated thumbnails, they're
  from an older version: delete `data\thumbnails\*`, set `UPDATE files SET
  thumb_status='pending'`, restart the server (it auto-resumes thumbnail jobs).
- **Fixed/regenerated thumbnails still look wrong in the browser** — thumbnail URLs carry
  a `?v=<updated_at>` cache-buster now. If you served thumbs with long-lived cache headers
  before, browsers keep the stale copy until the URL changes — hard refresh (Ctrl+F5) or
  just reload the page (new v param). Lesson recorded: never serve mutable content with
  `max-age` and an unchanging URL.
- **`database is locked` killed a job** — fixed 2026-07-07: `busy_timeout=30000` pragma +
  retries on job-status writes. The web server and worker are two processes sharing the
  SQLite file; both self-heal orphaned 'running' jobs at startup (server: scan/thumbnails,
  worker: caption/face/cluster) and auto-resume them. Batches never redo finished files.

## Server

- **Port 8420 already in use** — change `PORT` in `.env`.
- **Browser shows old UI after code change** — hard refresh (Ctrl+F5); static files are served without cache-busting.
- **Backend code change not taking effect** — the server does not auto-reload. Restart it (`scripts\stop_fotorganize.bat` then `start_fotorganize.bat`).
- **500 on /api/clusters: `HAVING clause on a non-aggregate query`** — this SQLite build rejects `HAVING` without `GROUP BY`. Fixed (subquery wrapper). If you hit similar, wrap the computed column in a subquery and filter in the outer query.

## AI jobs

- **Enqueued a caption/face job but nothing happens** — the web app only queues jobs; you must run the worker: `scripts\start_worker.bat` (or `python -m photoindex worker`). Jobs stay `pending` until the worker is running.
- **Florence-2 "downloaded new version of files ... make sure they do not contain malicious code"** — expected; Florence uses `trust_remote_code=True`. This is the one allowed network use (model + code from Hugging Face). No image data leaves the machine.
- **First caption/face run is slow** — it downloads models (Florence base ~1GB, buffalo_l ~300MB) to `%USERPROFILE%\.cache\huggingface` and `%USERPROFILE%\.insightface`. Subsequent runs are fast.
- **Re-run AI with a newer model** — set `files.caption_status`/`face_status` back to `'pending'` (or use `--retry-failed`) and re-run. Old results carry model_name/model_version.
