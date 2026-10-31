# ORYN — Enterprise Knowledge Platform

Private, multi-tenant "ask your documents" application. Upload PDF, DOCX or TXT files to a workspace, then ask questions in natural language.
Answers stream in, are grounded only in that workspace's documents, and carry citations you can open. Includes analytics, evaluation on your own
datasets, workspace roles, Google sign-in and an audit trail.

**Stack:** React 19 + TypeScript + Vite + Tailwind (frontend) · FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL (backend) · OpenAI (embeddings, chat) ·
Pinecone (vectors) · Cohere (rerank).

```
ORYN/
  backend/    FastAPI app, Alembic migrations, tests (114)
  frontend/   React SPA, Vitest tests (35)
  docs/       ARCHITECTURE, SECURITY, API, EVALUATION, GOOGLE_OAUTH_SETUP, DEPLOYMENT, TROUBLESHOOTING
  scripts/    setup.sh, setup.ps1, verify.sh
  .github/workflows/ci.yml, docker-compose.yml, render.yaml
```

## Prerequisites
- Python **3.12+**, Node.js **22.22.2+** (or 24), npm
- PostgreSQL **14+** (local install or Docker)
- Accounts and API keys: **OpenAI**, **Pinecone**, **Cohere** (required for real use). Google OAuth credentials are optional.

## Local setup

### macOS / Linux
```bash
bash scripts/setup.sh                  # venv, pip install, npm ci, creates backend/.env with a generated APP_SECRET
```
### Windows (PowerShell)
```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```
(Windows script is untested by the author; if it fails, run the equivalent commands from `setup.sh` by hand.)

### Create the database
```sql
-- psql -U postgres
CREATE USER oryn WITH PASSWORD 'choose-a-password';
CREATE DATABASE oryn OWNER oryn;
```
Or with Docker: `docker run -d --name oryn-pg -e POSTGRES_USER=oryn -e POSTGRES_PASSWORD=choose-a-password -e POSTGRES_DB=oryn -p 5432:5432 postgres:16-alpine`

### Configure `backend/.env`
Edit the file `setup` created:
```
DATABASE_URL=postgresql+psycopg://oryn:choose-a-password@localhost:5432/oryn
OPENAI_API_KEY=...        # https://platform.openai.com/api-keys
PINECONE_API_KEY=...      # https://app.pinecone.io  (index is auto-created, cosine, 1536 dims)
COHERE_API_KEY=...        # https://dashboard.cohere.com/api-keys
# optional Google sign-in: see docs/GOOGLE_OAUTH_SETUP.md
```

### Migrate and run
```bash
# terminal 1 — backend
cd backend
source .venv/bin/activate              # Windows: .\.venv\Scripts\Activate.ps1
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# terminal 2 — frontend
cd frontend
npm run dev
```
| What | URL |
|---|---|
| App | http://localhost:5173 |
| API health | http://localhost:8000/api/v1/health/ready |
| API docs (non-production) | http://localhost:8000/docs |

The Vite dev server proxies `/api` to port 8000, so cookies are same-origin in development.

### First administrator
There is **no default admin account**. Sign up normally, then promote yourself:
```bash
cd backend && source .venv/bin/activate
python -m app.cli make-admin --email you@example.com
```
(Or set `BOOTSTRAP_ADMIN_EMAIL` and sign in with that verified Google account.) Platform admin unlocks the "Platform admin" page; workspace owners already get analytics.

## Tests and builds
```bash
export TEST_DATABASE_URL=postgresql+psycopg://oryn:choose-a-password@localhost:5432/oryn_test   # an EMPTY dedicated database
bash scripts/verify.sh                # ruff, mypy, pytest, tsc, eslint, vitest, vite build
# or individually:
cd backend  && pytest -q && ruff check . && mypy app
cd frontend && npm run typecheck && npm run lint && npm test && npm run build
```
> The backend test suite **drops and recreates tables** in `TEST_DATABASE_URL`. Never point it at a database you care about.

## Docker Compose (everything in containers)
```bash
cp .env.example .env && cp backend/.env.example backend/.env    # fill POSTGRES_PASSWORD, APP_SECRET and the provider keys
docker compose up --build                                        # UI on http://localhost:5173
```

## Logo
Drop your SVG at `frontend/src/assets/brand/logo.svg`; it is picked up automatically at build time. Until then a neutral placeholder mark is shown.

## Deploying
Render (backend + Postgres) and Vercel (frontend): see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## What has and has not been verified
**Executed in the authoring sandbox (Python 3.13, Node 22.22.0):** 114 backend tests against a real PostgreSQL; 35 frontend tests; `ruff`, `mypy`,
`tsc`, `eslint`, production `vite build`; Alembic upgrade/downgrade round trip; clean-venv install and `npm ci` through `setup.sh`; `pip-audit` and `npm audit`
(no known vulnerabilities at the time); a real `uvicorn` server with incremental SSE streaming, disconnect-cancellation persistence and CSRF checks; a real
headless Chromium run through sign-up, reload-session, upload, processing, streamed answer, citation drawer, feedback, dark theme, sign-out and a phone-width layout.
That browser and server run used in-memory fakes for OpenAI, Pinecone and Cohere.

**Never executed — needs your credentials or infrastructure:** real OpenAI / Pinecone / Cohere calls (adapters are only tested against stubbed SDK clients), real Google
OAuth, Docker image builds and `docker compose`, Render and Vercel deployment, `setup.ps1` on Windows, cross-origin cookies in Safari, load or concurrency testing,
a security audit, accessibility testing with a screen reader (keyboard/ARIA structure is covered by tests only).

**Known limitations:** single-instance rate limiting and ingestion worker; local-disk file storage; no OCR for scanned PDFs; the frontend bundle is one ~720 kB chunk (not code-split);
`@hookform/resolvers` is pinned at 5.2.2 because 6.0.0 conflicts with npm's peer resolution; TypeScript is pinned at 6.0.3 because typescript-eslint does not yet support 7.
