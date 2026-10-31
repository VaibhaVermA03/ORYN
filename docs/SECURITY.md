# Security notes

## Authentication
- Passwords: Argon2id. Policy: 10-128 chars, letters plus a number or symbol, not in a common-password list, not the email name.
- Login timing is equalised for unknown emails (a dummy hash is verified). The error message never reveals which field was wrong.
- Access token: JWT, 15 minutes, kept **in memory** by the frontend (never localStorage).
- Refresh token: opaque random value in an `HttpOnly` cookie scoped to `/api/v1/auth`, stored server-side as a keyed HMAC hash, rotated
  on every use. Reuse of an already-rotated token (after a 10 s grace window for racing tabs) revokes the whole token family.
  Access tokens stop working as soon as their family is revoked.
- Logout revokes the session server-side.

## CSRF and CORS
Cookie-authenticated endpoints (`/auth/refresh`, `/auth/logout`) require the custom header `X-Requested-By: oryn-web` **and** a trusted
`Origin`. All other endpoints use the `Authorization` header, which browsers do not attach automatically. CORS allows only the explicit
origins in `FRONTEND_ORIGINS` (a wildcard is rejected at startup).

## Google sign-in
Authorization-code flow with `state`, `nonce` and PKCE (S256) held in a signed HttpOnly cookie. The ID token is verified with
`google-auth`. Identity is keyed by Google's `sub`. A Google login is **never** auto-linked to an existing password account just because
the email matches; the user must sign in with the password and link explicitly from Settings. Unverified Google emails are rejected.

## Authorization
Workspace roles: owner, admin, member. Analytics and evaluation need owner/admin. Platform admin (`users.role = admin`) is separate and is
granted only by `python -m app.cli make-admin` or by a verified Google sign-in matching `BOOTSTRAP_ADMIN_EMAIL`. There is no default
admin account or password. Platform admin overview exposes aggregate counts only, no document content.

## Uploads
Extension allow-list (pdf, txt, docx), magic-byte sniffing, size limit, per-workspace content-hash duplicate rejection, sanitized
filenames, files stored under generated names, never served back by path. Text extraction happens in the worker, not the request.

## Prompt injection
Document text is untrusted. It is wrapped in `<source>` tags with an instruction not to follow it, the model gets no tools, and the answer is
rendered as Markdown **without raw HTML**; links are restricted to http(s)/mailto and images are not rendered. This reduces risk but cannot
eliminate it; a malicious document can still try to bias an answer.

## Other controls
Security headers on every response, request body size limit, request ids, JSON logs with secret redaction, audit events for sensitive actions
(signup, login failures, member changes, uploads/deletes, evaluation start, refresh reuse), `.env` files git-ignored, production start-up
validation (secret length, explicit origins, secure cookies, required provider keys).

## What this is not
No penetration test or third-party audit has been performed. Dependency scans (`pip-audit`, `npm audit`) reported no known vulnerabilities on the
build date, which says nothing about future advisories. Re-run them regularly.
