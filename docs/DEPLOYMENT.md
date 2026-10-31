# Deployment

Targets: backend + PostgreSQL on **Render**, frontend on **Vercel**. Pinecone, OpenAI and Cohere are external services.

> Not verified: nothing here has been deployed to Render or Vercel by the author. Treat these steps as a checked-by-reading guide and expect to
> adjust. The Docker images and `docker-compose.yml` were also never built in the authoring environment.

## 0. Decide your domains (important for cookies)
The refresh cookie is `HttpOnly`. For it to work between two sites, use **custom domains under one registrable domain**, e.g.
`app.example.com` (Vercel) and `api.example.com` (Render). Then set `COOKIE_DOMAIN=.example.com`, `COOKIE_SAMESITE=lax`, `COOKIE_SECURE=true`.
Using `*.vercel.app` + `*.onrender.com` makes the cookie third-party; that needs `COOKIE_SAMESITE=none` and is blocked or limited by Safari and
some privacy settings. Not recommended.

## 1. External services
- **Pinecone**: create an API key. With `PINECONE_AUTO_CREATE_INDEX=true` the serverless index (cosine, dimension = `EMBEDDING_DIMENSIONS`)
  is created on first use. If you create it yourself, the dimension must match.
- **OpenAI** and **Cohere**: create API keys.

## 2. Render (backend)
1. Create a PostgreSQL instance. Copy its **Internal Database URL** and change the scheme from `postgres://` to `postgresql+psycopg://`.
2. Either use the Blueprint (`render.yaml`, New -> Blueprint) or create a *Web Service* from the repo with root directory `backend`, runtime Docker.
3. Attach a **persistent disk** mounted at `/var/data` (needs a paid plan). Without it, uploaded files vanish on every deploy.
4. Environment variables (secrets as "secret" values): see `backend/.env.example`. Required in production: `APP_ENV=production`, `APP_SECRET`,
   `DATABASE_URL`, `OPENAI_API_KEY`, `PINECONE_API_KEY`, `COHERE_API_KEY`, `FRONTEND_ORIGINS=https://app.example.com`, `COOKIE_SECURE=true`,
   `COOKIE_DOMAIN=.example.com`, `STORAGE_DIR=/var/data/storage`, `TEMP_DIR=/var/data/tmp`, `FRONTEND_POST_LOGIN_URL=https://app.example.com/app`,
   `FRONTEND_LOGIN_URL=https://app.example.com/login`. The app refuses to start in production if the essentials are missing.
5. Migrations: the Blueprint runs `alembic upgrade head` as the pre-deploy command. If you create the service by hand, set the same pre-deploy command, or
   run it once from the Render shell. Migrations never run implicitly at startup.
6. Health check path: `/api/v1/health/live`. Readiness (database + provider configuration): `/api/v1/health/ready`.
7. Add the custom domain `api.example.com`.
8. First admin: Render shell -> `python -m app.cli make-admin --email you@example.com` (after that account has signed up).
9. Keep a **single instance**: rate limiting and the inline ingestion worker are per process. To scale out, set `INGESTION_WORKER_MODE=separate`
   and run `python -m app.workers.ingestion_worker` as a background worker sharing the same disk, which also needs a shared file system or object storage.

## 3. Vercel (frontend)
1. Import the repo, set **Root Directory** to `frontend`. Framework preset: Vite. Build command `npm run build`, output `dist`.
2. Environment variable: `VITE_API_BASE_URL=https://api.example.com` (no trailing slash, no `/api/v1`).
3. `frontend/vercel.json` already rewrites all non-asset paths to `index.html` (client-side routing) and sets security headers.
4. Add the custom domain `app.example.com`.
5. Update Google OAuth (see `GOOGLE_OAUTH_SETUP.md`) with the production redirect URI.

## 4. Smoke test after deploy
`curl https://api.example.com/api/v1/health/ready` -> all `ok`/`configured`; sign up in the UI; upload a small PDF; wait for **Ready**; ask a question;
open a citation.

## Local Docker Compose
`cp .env.example .env` (set `POSTGRES_PASSWORD`), `cp backend/.env.example backend/.env` (fill keys, `APP_SECRET`), then `docker compose up --build`.
The UI is on <http://localhost:5173>, nginx proxies `/api` (unbuffered, for SSE) to the backend. For Google sign-in in this mode, the redirect URI can stay
`http://localhost:8000/api/v1/auth/google/callback` because port 8000 is published.
