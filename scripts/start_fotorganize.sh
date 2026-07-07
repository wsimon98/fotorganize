#!/usr/bin/env bash
# Starts fotorganize in the background (Linux). PID -> data/fotorganize.pid.
# Run scripts/setup_linux.sh once first.
set -e
cd "$(dirname "$0")/.."

PY=backend/venv/bin/python
[ -x "$PY" ] || { echo "venv missing - run scripts/setup_linux.sh first"; exit 1; }

if [ -f data/fotorganize.pid ] && kill -0 "$(cat data/fotorganize.pid)" 2>/dev/null; then
  echo "fotorganize already running (PID $(cat data/fotorganize.pid)) - http://127.0.0.1:8420"
  exit 0
fi

mkdir -p data/logs
cd backend
nohup venv/bin/python -m photoindex serve >> ../data/logs/server.log 2>&1 &
echo $! > ../data/fotorganize.pid
cd ..

for i in $(seq 1 10); do
  if curl -s -o /dev/null http://127.0.0.1:8420/api/health 2>/dev/null; then
    echo "fotorganize started (PID $(cat data/fotorganize.pid)) - http://127.0.0.1:8420"
    exit 0
  fi
  sleep 1
done
echo "WARNING: server did not answer health check yet - check data/logs/server.log"
