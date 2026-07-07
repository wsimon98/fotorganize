#!/usr/bin/env bash
# Stops the background fotorganize server (Linux).
cd "$(dirname "$0")/.."

if [ -f data/fotorganize.pid ]; then
  PID=$(cat data/fotorganize.pid)
  if kill "$PID" 2>/dev/null; then
    echo "fotorganize stopped (PID $PID)"
    rm -f data/fotorganize.pid
    exit 0
  fi
  rm -f data/fotorganize.pid
fi

# fallback: kill by command line
if pkill -f "photoindex serve" 2>/dev/null; then
  echo "fotorganize stopped (matched 'photoindex serve')"
else
  echo "fotorganize was not running."
fi
