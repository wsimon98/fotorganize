# Windows setup

Verified on Windows 11 / Python 3.13.5 / RTX 5060 Ti. No Docker anywhere.

## Install

```bat
cd F:\fotorganize
scripts\setup_windows.bat
```

Creates `backend\venv`, installs `backend\requirements.txt`, copies `.env.example` → `.env`
if missing, and reports Python/npm/GPU status. npm is informational only — the frontend has
no build step.

## Run

```bat
scripts\start_fotorganize.bat    :: background — writes PID to data\fotorganize.pid, opens browser
scripts\stop_fotorganize.bat     :: stops via PID file, falls back to killing port 8420
```

Or foreground with live console logs: `scripts\run_server.bat` (stop with Ctrl+C).
Both are safe to run twice — start detects an already-running server, stop reports
"was not running".

## Linux (future migration)

`.sh` mirrors live in scripts/: `setup_linux.sh`, `start_fotorganize.sh`,
`stop_fotorganize.sh`, `scan_all_sources.sh`. Syntax-checked but not yet exercised on a
real Linux box. Big caveat: `sources.root_path` values in the DB are Windows paths — after
moving, re-add each source with its Linux mount path (e.g. `/mnt/nas/family/photos`);
file records reconnect per source row, so plan a small path-rewrite migration when the
time comes (or ask the AI to write one).

## Config (.env)

See `.env.example` for all keys. Common changes: `PORT`, `THUMBNAIL_SIZE`, `HF_HOME`
(Phase 3 model cache location).

## LAN mode — read before enabling

Setting `ALLOW_LAN=true` binds to `0.0.0.0`: **every device on your network can browse
your entire family photo library, no password.** There is no authentication yet.
Only enable on a trusted home LAN, and consider Windows Firewall rules limiting the port
to specific IPs. The server logs a warning at startup when LAN mode is on.

## Scheduled scanning (optional)

Task Scheduler → run `F:\fotorganize\scripts\scan_all_sources.bat` nightly. It scans all
active sources and fills in missing thumbnails; logs land in `data\logs\`.

## GPU (needed from Phase 3)

RTX 5060 Ti = Blackwell (sm_120). Use recent CUDA wheels:

```bat
backend\venv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cu128
backend\venv\Scripts\python -c "import torch; print(torch.cuda.is_available())"
```
