#!/usr/bin/env bash
# Runs every automated check. Backend tests need an EMPTY PostgreSQL database dedicated to tests:
#   export TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/oryn_test
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

: "${TEST_DATABASE_URL:?Set TEST_DATABASE_URL to an empty test database (see the comment at the top of this script)}"

echo "==> Backend"
cd "$ROOT/backend"
# shellcheck disable=SC1091
. .venv/bin/activate
ruff check .
mypy app
pytest -q

echo "==> Frontend"
cd "$ROOT/frontend"
npm run typecheck
npm run lint
npm test
npm run build

echo "All checks passed."
