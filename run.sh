#!/bin/sh
# Start the Fiscal Policy Simulator (backend + frontend).
# Usage: ./run.sh     then open http://localhost:5173
set -e
cd "$(dirname "$0")"

# Backend (FastAPI) on :8000 — restart if not healthy
if ! curl -s --max-time 2 http://localhost:8000/health >/dev/null 2>&1; then
  lsof -ti :8000 2>/dev/null | xargs kill 2>/dev/null || true
  echo "starting backend on :8000 ..."
  nohup uv run uvicorn api.app:app --port 8000 >/tmp/policysim-api.log 2>&1 &
  i=0
  until curl -s --max-time 2 http://localhost:8000/health >/dev/null 2>&1; do
    i=$((i+1)); [ $i -gt 30 ] && { echo "backend failed to start — see /tmp/policysim-api.log"; exit 1; }
    sleep 1
  done
fi
echo "backend OK: $(curl -s http://localhost:8000/health)"

# Frontend (Vite) on :5173
if ! curl -s --max-time 2 -o /dev/null http://localhost:5173 2>/dev/null; then
  echo "starting frontend on :5173 ..."
  (cd ui && nohup npm run dev >/tmp/policysim-ui.log 2>&1 &)
  sleep 3
fi
echo "frontend OK -> http://localhost:5173"
echo
echo "Tip: the first microsim run takes a few minutes (national baseline);"
echo "repeat runs are served from the cache instantly."
