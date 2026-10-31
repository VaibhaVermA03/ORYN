#!/usr/bin/env bash
# ORYN local setup for macOS / Linux. Idempotent: never overwrites an existing .env.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing prerequisite: $1 ($2)"; exit 1; }; }
need python3 "Python 3.12+ from https://www.python.org/downloads/"
need node "Node.js 22+ from https://nodejs.org/"
need npm "comes with Node.js"
python3 - <<'PY' || { echo "Python 3.12 or newer is required."; exit 1; }
import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)
PY

echo "==> Backend: virtualenv and dependencies"
cd "$ROOT/backend"
[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
. .venv/bin/activate
python -m pip install --upgrade pip >/dev/null
pip install -r requirements.txt -r requirements-dev.txt

if [ ! -f .env ]; then
  cp .env.example .env
  SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
  python - "$SECRET" <<'PY'
import pathlib, sys
p = pathlib.Path(".env")
p.write_text(p.read_text().replace("APP_SECRET=\n", f"APP_SECRET={sys.argv[1]}\n", 1))
PY
  echo "Created backend/.env with a freshly generated APP_SECRET."
  echo "Fill in DATABASE_URL, OPENAI_API_KEY, PINECONE_API_KEY, COHERE_API_KEY (and Google OAuth if wanted)."
else
  echo "backend/.env already exists; left untouched."
fi

echo "==> Frontend: dependencies"
cd "$ROOT/frontend"
npm ci

cat <<'MSG'

Setup finished. Next:
  1. Edit backend/.env (database + provider keys).
  2. cd backend && . .venv/bin/activate && alembic upgrade head
  3. Start the API:      uvicorn app.main:app --reload --port 8000
  4. Start the frontend: cd frontend && npm run dev     -> http://localhost:5173
See README.md and docs/ for details.
MSG
