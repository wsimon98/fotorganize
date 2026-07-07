#!/usr/bin/env bash
# Scan all active sources + fill missing thumbnails (Linux mirror of scan_all_sources.bat).
set -e
cd "$(dirname "$0")/../backend"
[ -x venv/bin/python ] || { echo "venv missing - run scripts/setup_linux.sh first"; exit 1; }
echo "Scanning all active sources... logs go to data/logs/"
venv/bin/python -m photoindex scan --all
echo "Building any missing thumbnails..."
venv/bin/python -m photoindex thumbnails --missing
echo "Done."
