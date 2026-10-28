#!/usr/bin/env bash
# Dev: (re)start the backend detached from the calling shell, on :8765, data in $BTV_DATA_DIR (default /tmp/btv-data).
cd "$(dirname "$0")/../backend"
pkill -f "uvicorn app.main:app" 2>/dev/null || true
sleep 1
export BTV_DATA_DIR="${BTV_DATA_DIR:-/tmp/btv-data}"
nohup ../.venv/bin/python -c "import os,sys; os.setsid(); os.execv(sys.argv[1], sys.argv[1:])" ../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8765 > /tmp/btv.log 2>&1 < /dev/null &
for _ in $(seq 1 30); do curl -s -o /dev/null localhost:8765/api/system && { echo "backend up on :8765"; exit 0; }; sleep 0.5; done
echo "backend did not start:"; tail -20 /tmp/btv.log; exit 1
