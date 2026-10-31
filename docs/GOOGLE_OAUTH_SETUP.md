# Google sign-in setup

Google sign-in is optional. Without credentials the "Continue with Google" button redirects back with a "not configured" message and
password sign-in keeps working.

1. Open <https://console.cloud.google.com/>, create or pick a project.
2. **APIs & Services -> OAuth consent screen.** Choose *External*, fill in app name and support email. Scopes: `openid`, `email`, `profile`.
   While the app is in *Testing*, add every Google account that should be able to sign in under **Test users**.
3. **APIs & Services -> Credentials -> Create credentials -> OAuth client ID -> Web application.**
4. Under **Authorized redirect URIs** add the **backend** callback exactly (scheme, host, port, path):
   - local: `http://localhost:8000/api/v1/auth/google/callback`
   - production: `https://api.example.com/api/v1/auth/google/callback`
   Authorized JavaScript origins are not needed for this server-side flow.
5. Copy the client id and secret into `backend/.env` (or Render environment variables):
   ```
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/auth/google/callback
   FRONTEND_POST_LOGIN_URL=http://localhost:5173/app
   FRONTEND_LOGIN_URL=http://localhost:5173/login
   ```
6. Restart the API. `GET /api/v1/health/ready` should show `google_oauth: configured`.

Bootstrap the first administrator either by setting `BOOTSTRAP_ADMIN_EMAIL=you@example.com` and signing in with that **verified** Google
account, or with `python -m app.cli make-admin --email you@example.com` for an existing account.

Errors come back as `/login?error=<code>`. Common codes: `redirect_uri_mismatch` is shown by Google itself (the URI in step 4 does not match
`GOOGLE_REDIRECT_URI`); `account_exists` means a password account with that email exists, so sign in with the password and use *Settings ->
Link Google account*; `invalid_state` means the sign-in took more than a few minutes or cookies are blocked.

> Not verified: this flow was tested against stubbed Google endpoints only, never against a real Google project.
