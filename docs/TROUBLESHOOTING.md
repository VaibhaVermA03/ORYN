# Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| API exits at start with "Invalid ORYN configuration" | The message lists each problem (short `APP_SECRET`, wildcard origin, missing provider key in production...). Fix `.env`. |
| `password authentication failed` / `connection refused` | Wrong `DATABASE_URL` or PostgreSQL not running. The scheme must be `postgresql+psycopg://`. |
| `relation "users" does not exist` | Migrations not applied: `cd backend && alembic upgrade head`. |
| Signed in, but reload logs me out | Refresh cookie not sent. Local dev: use the Vite proxy (leave `VITE_API_BASE_URL` empty). Production: see cookie domains in `DEPLOYMENT.md`; `COOKIE_SECURE=true` requires HTTPS. |
| Browser console: CORS error | The exact frontend origin (scheme+host+port, no trailing slash) must be in `FRONTEND_ORIGINS`. |
| 403 on `/auth/refresh` | Missing `X-Requested-By` header or an untrusted `Origin`; also happens when calling it with curl. |
| Upload says "Ready" never arrives / stuck at *Queued* | Worker not running: check `INGESTION_WORKER_MODE` (`inline` for single process). Look for `ingestion_*` log lines. |
| Document shows *Failed* | The reason is shown under the file name (empty/scanned PDF without text, corrupt file, provider error). Fix and click retry. Scanned PDFs need OCR, which ORYN does not do. |
| Pinecone error "dimension" | `EMBEDDING_DIMENSIONS` must equal the index dimension (1536 for `text-embedding-3-small`). Use a new index name if changing models. |
| Answers always say "not enough information" | No `ready` documents in the selected workspace, or the rerank threshold (`MIN_RERANK_SCORE`) is too high for your content. |
| `Google sign-in is not configured` | Set the three `GOOGLE_*` variables and restart; see `GOOGLE_OAUTH_SETUP.md`. |
| Streaming answer arrives all at once | A proxy is buffering. nginx needs `proxy_buffering off` (included in `frontend/nginx.conf`); Cloudflare and some corporate proxies buffer SSE. |
| `npm` warns `EBADENGINE` for jsdom | jsdom 30 wants Node >= 22.22.2. Upgrade Node; tests still ran on 22.22.0 here. |
| Backend tests fail with "database must be empty" | `TEST_DATABASE_URL` must point to a dedicated **empty** database; the suite creates and drops tables. Never point it at real data. |
| 429 responses | Per-process rate limits; tune `RATE_LIMIT_*`. |
