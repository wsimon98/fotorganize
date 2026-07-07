#!/usr/bin/env bash
# Runs the GPU worker loop (Linux). Ctrl+C to stop.
cd "$(dirname "$0")/../backend"
[ -x venv/bin/python ] || { echo "run scripts/setup_linux.sh first"; exit 1; }
echo "fotorganize worker starting - processes AI jobs. Ctrl+C to stop."
exec venv/bin/python -m photoindex worker
