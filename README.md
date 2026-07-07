# fotorganize

A **private, local-first photo indexing and face/person tagging system** for Windows.

fotorganize scans photo folders (local, mapped drive, or UNC network share), indexes
images into SQLite, generates thumbnails, and (in later phases) detects faces, clusters
people, generates AI captions, and exports clean person-specific datasets for LoRA training.

**This app handles private family photos. Everything stays local. No cloud. No telemetry. No Docker.**

## Current status

**All phases 0-10 complete and tested (14 tests passing).** Source management +
lifecycle + hard-delete, scanner, thumbnails, Florence-2 captions/tags/OCR, InsightFace
face detection, clustering with auto-assignment to named people, People Review UI, search,
LoRA dataset export, duplicate detection + screenshot flagging, and opt-in XMP sidecars all
work. Main remaining real-world step: point it at the actual NAS and let the worker chew
through captions + faces. See [PROJECT_CHECKLIST.md](PROJECT_CHECKLIST.md) and
[HANDOFF.md](HANDOFF.md).

## Requirements

- Windows 10/11 (Linux works via the `.sh` scripts; less battle-tested)
- Python 3.11+ on PATH (developed on 3.13)
- ~5 GB disk for Python deps + AI models
- NVIDIA GPU strongly recommended for captioning (any recent card; RTX 50xx "Blackwell"
  needs the cu128 torch wheels, which `setup_ai.bat` installs). Everything falls back to
  CPU and still works — just slower.
- No Docker. No cloud accounts. The only network access is downloading model weights from
  Hugging Face on first run.

## Install & run (Windows)

```bat
git clone https://github.com/<you>/fotorganize
cd fotorganize
scripts\setup_windows.bat        :: one-time: venv + base deps
scripts\setup_ai.bat             :: one-time: torch (CUDA) + Florence-2 + InsightFace deps
scripts\start_fotorganize.bat    :: web server (background) + opens browser
```

Then at http://127.0.0.1:8420:

1. **Sources** → add a photo folder (local `C:\Photos`, mapped drive `Z:\photos`, or UNC
   `\\nas\share\photos`) → **Scan**.
2. **Dashboard** → **Start worker** (runs the AI jobs), then **Caption pending images** and
   **Detect faces** → **Cluster faces**.
3. **People Review** → name the face clusters ("George Clooney", "Taylor Swift", …). fotorganize auto-tags
   similar faces from then on.
4. **Search** → find photos by content ("dog", "man in a red shirt"), person, date… and
   fix captions in bulk — rename "man" to "George Clooney" across every match, which also
   tags those images as that person.
5. Export for LoRA training (ai-toolkit format — image + matching .txt captions):
   - a **person**: their page → **Export LoRA dataset**
   - a **place or thing**: search it ("river", "motorcycle") → **Export results for LoRA…**

Other scripts: `stop_fotorganize.bat`, `run_server.bat` (foreground w/ live logs),
`start_worker.bat` (worker in its own window — or just use the Dashboard button),
`scan_all_sources.bat`, `backup_database.bat`, `export_person_lora.bat`. Linux mirrors:
`setup_linux.sh`, `start_fotorganize.sh`, `stop_fotorganize.sh`, `start_worker.sh`,
`scan_all_sources.sh`, `export_person_lora.sh`.

## Stack

- **Backend:** Python 3.13, FastAPI, SQLite (WAL mode)
- **Frontend:** plain HTML/JS/CSS served by FastAPI (no build step — see DECISIONS.md)
- **Imaging:** Pillow + ImageHash (perceptual hash)
- **Jobs:** SQLite `jobs` table + background threads (single process for now)
- **AI (later phases):** InsightFace (faces), Florence-2 (captions) — local GPU, RTX 5060 Ti

## Layout

```
fotorganize/
  README.md / PROJECT_CHECKLIST.md / HANDOFF.md / DECISIONS.md / ATTRIBUTION.md / TROUBLESHOOTING.md
  .env.example          copy to .env to customize
  backend/
    requirements.txt
    photoindex/         Python package ("python -m photoindex ..." CLI + FastAPI app)
      main.py           FastAPI app
      config.py         env config
      database.py       SQLite schema + connection
      cli.py            CLI entry (scan, thumbnails, backup)
      routes/           API endpoints
      services/         scanner, thumbnails
      utils/            path handling, logging
  frontend/src/         static web UI (dark mode)
  scripts/              .bat files
  data/                 app.db, thumbnails/, face_crops/, exports/, logs/, test_photos/
  docs/                 database_schema.md, source_management.md, windows_setup.md, ...
```

## Privacy rules (non-negotiable)

- Binds to `127.0.0.1` by default. LAN mode is opt-in via `.env` (`ALLOW_LAN=true`) — see warning in docs/windows_setup.md.
- Never deletes or modifies original photos.
- Never uploads anything. No external APIs for face or image data.
- Missing files/sources are *marked*, never erased — labels survive a NAS being unplugged.

## CLI

```
python -m photoindex scan --all | --source-id 1
python -m photoindex thumbnails --missing
python -m photoindex captions --pending [--limit N] [--retry-failed]
python -m photoindex faces --pending [--limit N] [--retry-failed]
python -m photoindex cluster-faces
python -m photoindex worker [--once]          # long-running GPU job processor
python -m photoindex export-lora --person "George Clooney" --trigger "clooney_person" --zip
python -m photoindex backup
```

(Run from `backend/` with the venv activated, or use the .bat scripts.)
