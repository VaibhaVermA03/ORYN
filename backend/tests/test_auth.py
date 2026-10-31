from __future__ import annotations

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.db.models import AuthSession, User
from tests.conftest import CSRF, auth, signup


def test_signup_success_creates_workspace_and_hashes_password(client, db):
    email, token, body = signup(client, "New.User@Example.com ")
    assert body["user"]["email"] == "new.user@example.com"
    assert body["user"]["role"] == "user"
    assert body["user"]["email_verified"] is False
    user = db.execute(select(User).where(User.email == "new.user@example.com")).scalar_one()
    assert user.password_hash.startswith("$argon2id$")
    r = client.get("/api/v1/workspaces", headers=auth(token))
    assert r.status_code == 200 and len(r.json()) == 1 and r.json()[0]["role"] == "owner"


def test_signup_sets_httponly_refresh_cookie(client):
    r = client.post(
        "/api/v1/auth/signup",
        json={"email": "cookie@example.com", "password": "correct-horse-9", "display_name": "C"},
    )
    cookie = r.headers["set-cookie"].lower()
    assert "oryn_refresh=" in cookie and "httponly" in cookie and "path=/api/v1/auth" in cookie
    assert "refresh_token" not in r.text  # refresh token is never in the JSON body


def test_signup_validation_failures(client):
    for payload in (
        {"email": "not-an-email", "password": "correct-horse-9", "display_name": "x"},
        {"email": "a@example.com", "password": "short", "display_name": "x"},
        {"email": "a@example.com", "password": "aaaaaaaaaaaa", "display_name": "x"},
        {"email": "a@example.com", "password": "password123", "display_name": "x"},
        {"email": "a@example.com", "password": "correct-horse-9", "display_name": "   "},
    ):
        r = client.post("/api/v1/auth/signup", json=payload)
        assert r.status_code == 422, payload
        assert r.json()["error"]["code"] == "validation_error"


def test_duplicate_email_rejected_case_insensitively(client):
    signup(client, "dup@example.com")
    r = client.post(
        "/api/v1/auth/signup",
        json={"email": "DUP@example.com", "password": "correct-horse-9", "display_name": "x"},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"


def test_login_success_and_wrong_password_is_generic(client):
    signup(client, "login@example.com", password="correct-horse-9")
    ok = client.post("/api/v1/auth/login", json={"email": "login@example.com", "password": "correct-horse-9"})
    assert ok.status_code == 200 and ok.json()["access_token"]
    bad = client.post("/api/v1/auth/login", json={"email": "login@example.com", "password": "wrong-password-1"})
    ghost = client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong-password-1"})
    assert bad.status_code == ghost.status_code == 401
    assert bad.json()["error"]["message"] == ghost.json()["error"]["message"]


def test_login_rate_limited(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_AUTH_PER_MINUTE", "3")
    get_settings.cache_clear()
    try:
        codes = [
            client.post("/api/v1/auth/login", json={"email": "x@example.com", "password": "nope-nope-1"}).status_code
            for _ in range(5)
        ]
        assert codes[:3] == [401, 401, 401] and codes[3] == 429
    finally:
        monkeypatch.delenv("RATE_LIMIT_AUTH_PER_MINUTE", raising=False)
        monkeypatch.setenv("RATE_LIMIT_AUTH_PER_MINUTE", "1000")
        get_settings.cache_clear()


def test_protected_endpoint_requires_valid_token(client):
    assert client.get("/api/v1/users/me").status_code == 401
    assert client.get("/api/v1/users/me", headers=auth("garbage")).status_code == 401
    _, token, _ = signup(client)
    assert client.get("/api/v1/users/me", headers=auth(token)).status_code == 200


def test_refresh_rotates_token_and_old_token_is_rejected(client):
    signup(client)
    old = client.cookies.get("oryn_refresh")
    r = client.post("/api/v1/auth/refresh", headers=CSRF)
    assert r.status_code == 200
    new = client.cookies.get("oryn_refresh")
    assert new and new != old
    assert client.get("/api/v1/users/me", headers=auth(r.json()["access_token"])).status_code == 200


def test_refresh_requires_csrf_header_and_trusted_origin(client):
    signup(client)
    assert client.post("/api/v1/auth/refresh").status_code == 403
    evil = {"X-Requested-By": "oryn-web", "Origin": "https://evil.example"}
    r = client.post("/api/v1/auth/refresh", headers=evil)
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"


def test_refresh_token_reuse_revokes_whole_family(client, db):
    _, token, _ = signup(client)
    stolen = client.cookies.get("oryn_refresh")
    assert client.post("/api/v1/auth/refresh", headers=CSRF).status_code == 200
    # Expire the benign-concurrency grace window, then replay the consumed token.
    from datetime import timedelta

    for s in db.execute(select(AuthSession)).scalars():
        if s.rotated_at:
            s.rotated_at = s.rotated_at - timedelta(minutes=5)
    db.commit()
    client.cookies.clear()
    client.cookies.set("oryn_refresh", stolen, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh", headers=CSRF).status_code == 401
    db.expire_all()
    assert all(s.revoked_at is not None for s in db.execute(select(AuthSession)).scalars())
    # The legitimate access token tied to the revoked family stops working too.
    assert client.get("/api/v1/users/me", headers=auth(token)).status_code == 401


def test_logout_revokes_session(client):
    _, token, _ = signup(client)
    assert client.post("/api/v1/auth/logout", headers=CSRF).status_code == 204
    assert client.post("/api/v1/auth/refresh", headers=CSRF).status_code == 401
    r = client.get("/api/v1/users/me", headers=auth(token))
    assert r.status_code == 401 and r.json()["error"]["code"] == "session_revoked"


def test_expired_access_token_rejected(client, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "access_token_ttl_minutes", -1)
    _, _, body = signup(client)
    me = client.get("/api/v1/users/me", headers=auth(body["access_token"]))
    assert me.status_code == 401 and me.json()["error"]["code"] == "token_expired"


def test_password_hash_roundtrip():
    h = hash_password("correct-horse-9")
    assert h.startswith("$argon2id$") and verify_password("correct-horse-9", h)
    assert not verify_password("other", h)


def test_error_responses_have_consistent_shape_and_request_id(client):
    r = client.get("/api/v1/users/me")
    err = r.json()["error"]
    assert set(err) == {"code", "message", "request_id"} and err["request_id"] == r.headers["x-request-id"]


def test_cors_preflight_allows_trusted_origin_with_csrf_header_and_credentials(client):
    """A cross-origin SPA (e.g. Vercel -> Render) sends X-Requested-By on refresh/logout, which
    triggers a preflight. It must succeed for the trusted origin and fail for others."""
    headers = {
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "x-requested-by,content-type,authorization",
    }
    ok = client.options("/api/v1/auth/refresh", headers=headers)
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert ok.headers["access-control-allow-credentials"] == "true"
    assert "x-requested-by" in ok.headers["access-control-allow-headers"].lower()
    evil = client.options("/api/v1/auth/refresh", headers=headers | {"Origin": "https://evil.example"})
    assert evil.status_code == 400 and "access-control-allow-origin" not in evil.headers
