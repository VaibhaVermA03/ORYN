# API overview

Base path `/api/v1`. Interactive OpenAPI docs are served by FastAPI at `/docs` when `APP_ENV` is not `production`.
Errors always look like `{"error": {"code": "...", "message": "...", "request_id": "..."}}`.
Authenticated endpoints need `Authorization: Bearer <access token>`.

## Auth (`/auth`)
| Method | Path | Notes |
|---|---|---|
| POST | /auth/signup | body `email, password, display_name`; returns access token, sets refresh cookie |
| POST | /auth/login | body `email, password` |
| POST | /auth/refresh | cookie + `X-Requested-By: oryn-web` + trusted Origin; rotates the refresh token |
| POST | /auth/logout | same CSRF rules; 204 |
| GET | /auth/google/login | browser redirect; optional `link_token` |
| GET | /auth/google/callback | redirects to the frontend (`?error=code` on failure) |
| POST | /auth/google/link-intent | authenticated; returns a short-lived `link_token` |

## Users
`GET /users/me`, `PATCH /users/me` (`display_name`).

## Workspaces
`GET /workspaces`, `POST /workspaces`, `GET|PATCH|DELETE /workspaces/{id}`, `GET|POST /workspaces/{id}/members`,
`PATCH|DELETE /workspaces/{id}/members/{user_id}`. Non-members get 404.

## Documents (`/workspaces/{id}`)
`POST /documents` (multipart field `files`, up to `MAX_FILES_PER_REQUEST`; per-file results in `results[]`), `GET /documents?q=&status=&page=&page_size=`,
`GET|DELETE /documents/{doc id}`, `POST /documents/{doc id}/reindex`, `GET /chunks/{chunk id}`.

## Chat (`/workspaces/{id}`)
`POST /chat/stream` body `{message, conversation_id?}` -> SSE (`status`, `sources`, `token`, `done`, `error`).
`GET /conversations`, `GET|PATCH|DELETE /conversations/{id}`, `PUT|DELETE /messages/{id}/feedback` (`{rating: 1|-1, comment?}`).

## Analytics and evaluation
`GET /workspaces/{id}/analytics`, `GET /workspaces/{id}/audit-events` (workspace owner/admin or platform admin);
`POST|GET /workspaces/{id}/evaluations`, `GET /workspaces/{id}/evaluations/{run}`;
`GET /admin/overview`, `GET /admin/audit-events` (platform admin).

## Health
`GET /health/live` (process up), `GET /health/ready` (database checked live; provider keys reported as configured/missing, not called).
