#!/usr/bin/env bash
# One-time Linux setup — mirror of setup_windows.bat.
# Note for a future migration: sources.root_path values are Windows-style; you would
# re-add sources with their Linux mount paths (e.g. /mnt/nas/family/photos) —
# see docs/source_management.md (reconnect works per-path, so plan a migration script).
set -e
cd "$(dirname "$0")/.."

echo "=== fotorganize setup (Linux) ==="
python3 --version || { echo "ERROR: python3 not found"; exit 1; }

if [ ! -d backend/venv ]; then
  python3 -m venv backend/venv
fi
backend/venv/bin/pip install --upgrade pip -q
backend/venv/bin/pip install -r backend/requirements.txt

command -v nvidia-smi >/dev/null && nvidia-smi --query-gpu=name --format=csv,noheader || echo "no NVIDIA GPU visible (fine until Phase 3)"

[ -f .env ] || cp .env.example .env && echo "created .env"
chmod +x scripts/*.sh
echo "=== Setup complete ==="
echo "Next: scripts/start_fotorganize.sh  then open http://127.0.0.1:8420"
