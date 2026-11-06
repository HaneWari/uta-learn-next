#!/usr/bin/env bash
# Uta Learn Next — one command, one process.
#
#   ./dev.sh            build the SPA if needed, then serve everything on :8000
#   ./dev.sh --rebuild  force a frontend rebuild first
#   ./dev.sh --dev      run vite on :5173 next to the API (hot reload, for hacking)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PORT="${PORT:-8000}"
REBUILD=0
VITE=0
for arg in "$@"; do
  case "$arg" in
    --rebuild) REBUILD=1 ;;
    --dev) VITE=1 ;;
  esac
done

# ---- python deps -----------------------------------------------------------
# Installed from pyproject.toml so the launcher and the package can never drift
# apart. `speech` brings fugashi + whisper, `export` brings playwright.
if ! python -c "import fastapi, uvicorn, fugashi, httpx, numpy, PIL" >/dev/null 2>&1; then
  echo "  installing python deps..."
  python -m pip install --quiet -e "backend[speech,export]"
fi

python -c "import faster_whisper" >/dev/null 2>&1 || \
  echo "  note: faster-whisper missing — the whisper fallback will be unavailable"

command -v ffmpeg >/dev/null 2>&1 || \
  echo "  note: ffmpeg not found — uploaded audio cannot be decoded"

# ---- frontend --------------------------------------------------------------
if [ "$REBUILD" = 1 ] || [ ! -f frontend/dist/index.html ]; then
  if [ ! -d frontend/node_modules ]; then
    echo "  installing frontend deps..."
    ( cd frontend && npm install )
  fi
  echo "  building frontend..."
  ( cd frontend && npm run build )
fi

# ---- serve -----------------------------------------------------------------
cleanup() { kill "${API_PID:-}" "${VITE_PID:-}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

if [ "$VITE" = 1 ]; then
  ( cd backend && exec python -m uvicorn main:app --host 0.0.0.0 --port "$PORT" ) &
  API_PID=$!
  ( cd frontend && exec npm run dev ) &
  VITE_PID=$!
  echo
  echo "  api   http://localhost:$PORT"
  echo "  app   http://localhost:5173   (hot reload)"
  wait
else
  echo
  echo "  Uta Learn Next  ->  http://localhost:$PORT"
  echo "  Ctrl-C to stop"
  echo
  ( cd backend && exec python -m uvicorn main:app --host 0.0.0.0 --port "$PORT" )
fi
