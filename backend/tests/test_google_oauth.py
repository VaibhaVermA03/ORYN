"""Google OAuth flow with the external provider mocked at its two network boundaries."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from sqlalchemy import select

from app.db.models import OAuthIdentity, User
from app.services import google_service
from tests.conftest import auth, signup


def _begin(client, link_token: str | None = None):
    url = "/api/v1/auth/google/login" + (f"?link_token={link_token}" if link_token else "")
    r = client.get(url, follow_redirects=False)
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers["location"]).query)
    return r, q


def _mock_google(monkeypatch, claims: dict, *, id_token="idtok", reject_code=False):
    def fake_exchange(code, verifier):
        if reject_code:
            raise google_service.GoogleAuthError("rejected", code="code_rejected")
        return {"id_token": id_token}

    def fake_verify(raw, nonce):
        assert raw == id_token
        if claims.get("nonce_override") is not None:
            nonce = claims["nonce_override"]
        return {k: v for k, v in claims.items() if k != "nonce_override"} | {"nonce": nonce}

    monkeypatch.setattr(google_service, "exchange_code", fake_exchange)
    monkeypatch.setattr(google_service, "verify_id_token", fake_verify)


def test_login_redirect_contains_state_nonce_and_pkce(client):
    r, q = _begin(client)
    assert q["response_type"] == ["code"] and q["code_challenge_method"] == ["S256"]
    assert q["state"][0] and q["nonce"][0] and q["code_challenge"][0]
    assert q["client_id"] == ["test-client-id.apps.googleusercontent.com"]
    assert "oryn_oauth=" in r.headers["set-cookie"] and "HttpOnly" in r.headers["set-cookie"]


def test_new_google_user_is_created_and_logged_in(client, monkeypatch, db):
    _, q = _begin(client)
    _mock_google(monkeypatch, {"sub": "g-123", "email": "G.User@Example.com", "email_verified": True, "name": "G User"})
    r = client.get(f"/api/v1/auth/google/callback?code=abc&state={q['state'][0]}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].endswith("/app")
    assert client.cookies.get("oryn_refresh")
    user = db.execute(select(User).where(User.email == "g.user@example.com")).scalar_one()
    assert user.email_verified is True and user.password_hash is None
    ident = db.execute(select(OAuthIdentity)).scalar_one()
    assert (ident.provider, ident.subject, ident.user_id) == ("google", "g-123", user.id)
    # The session cookie works for refresh, giving the SPA its first access token.
    ref = client.post("/api/v1/auth/refresh", headers={"X-Requested-By": "oryn-web", "Origin": "http://localhost:5173"})
    assert ref.status_code == 200 and ref.json()["user"]["google_linked"] is True


def test_returning_google_user_is_matched_by_subject_not_email(client, monkeypatch, db):
    _, q = _begin(client)
    _mock_google(monkeypatch, {"sub": "g-777", "email": "first@example.com", "email_verified": True, "name": "F"})
    client.get(f"/api/v1/auth/google/callback?code=abc&state={q['state'][0]}", follow_redirects=False)
    client.cookies.clear()
    _, q2 = _begin(client)
    # Same subject, different email claim: still the same account.
    _mock_google(monkeypatch, {"sub": "g-777", "email": "changed@example.com", "email_verified": True, "name": "F"})
    r = client.get(f"/api/v1/auth/google/callback?code=abc&state={q2['state'][0]}", follow_redirects=False)
    assert r.headers["location"].endswith("/app")
    assert len(db.execute(select(User)).scalars().all()) == 1


def test_invalid_state_is_rejected(client, monkeypatch):
    _begin(client)
    _mock_google(monkeypatch, {"sub": "g-1", "email": "a@example.com", "email_verified": True})
    r = client.get("/api/v1/auth/google/callback?code=abc&state=forged", follow_redirects=False)
    assert "error=invalid_state" in r.headers["location"]
    assert not client.cookies.get("oryn_refresh")


def test_missing_state_cookie_is_rejected(client, monkeypatch):
    _mock_google(monkeypatch, {"sub": "g-1", "email": "a@example.com", "email_verified": True})
    r = client.get("/api/v1/auth/google/callback?code=abc&state=whatever", follow_redirects=False)
    assert "error=invalid_state" in r.headers["location"]


def test_cancelled_authorization_and_provider_error(client, monkeypatch):
    _begin(client)
    r = client.get("/api/v1/auth/google/callback?error=access_denied", follow_redirects=False)
    assert "error=access_denied" in r.headers["location"]
    _, q = _begin(client)
    _mock_google(monkeypatch, {}, reject_code=True)
    r = client.get(f"/api/v1/auth/google/callback?code=expired&state={q['state'][0]}", follow_redirects=False)
    assert "error=code_rejected" in r.headers["location"]


def test_nonce_mismatch_is_rejected(client, monkeypatch):
    """Uses the real verify_id_token's nonce check by stubbing only google-auth's signature step."""
    monkeypatch.setattr(
        google_service.google_id_token, "verify_oauth2_token",
        lambda *a, **k: {"iss": "https://accounts.google.com", "sub": "s", "email": "n@example.com",
                         "email_verified": True, "nonce": "attacker-nonce"},
    )
    try:
        google_service.verify_id_token("tok", "expected-nonce")
        raise AssertionError("nonce mismatch should fail")
    except google_service.GoogleAuthError as exc:
        assert exc.code == "invalid_nonce"


def test_wrong_issuer_is_rejected(monkeypatch):
    monkeypatch.setattr(
        google_service.google_id_token, "verify_oauth2_token",
        lambda *a, **k: {"iss": "https://evil.example", "sub": "s", "nonce": "n"},
    )
    try:
        google_service.verify_id_token("tok", "n")
        raise AssertionError("issuer mismatch should fail")
    except google_service.GoogleAuthError as exc:
        assert exc.code == "invalid_id_token"


def test_unverified_google_email_is_rejected(client, monkeypatch):
    _, q = _begin(client)
    _mock_google(monkeypatch, {"sub": "g-9", "email": "u@example.com", "email_verified": False})
    r = client.get(f"/api/v1/auth/google/callback?code=abc&state={q['state'][0]}", follow_redirects=False)
    assert "error=email_unverified" in r.headers["location"]


def test_existing_password_account_is_not_auto_linked_by_email(client, monkeypatch, db):
    signup(client, "victim@example.com")
    client.cookies.clear()
    _, q = _begin(client)
    _mock_google(monkeypatch, {"sub": "g-attacker", "email": "victim@example.com", "email_verified": True})
    r = client.get(f"/api/v1/auth/google/callback?code=abc&state={q['state'][0]}", follow_redirects=False)
    assert "error=account_exists" in r.headers["location"]
    assert db.execute(select(OAuthIdentity)).first() is None
    assert not client.cookies.get("oryn_refresh")


def test_explicit_link_from_authenticated_session(client, monkeypatch, db):
    _, token, _ = signup(client, "linker@example.com")
    intent = client.post("/api/v1/auth/google/link-intent", headers=auth(token))
    assert intent.status_code == 200
    client.cookies.clear()
    _, q = _begin(client, intent.json()["link_token"])
    _mock_google(monkeypatch, {"sub": "g-linked", "email": "linker@example.com", "email_verified": True})
    r = client.get(f"/api/v1/auth/google/callback?code=abc&state={q['state'][0]}", follow_redirects=False)
    assert r.headers["location"].endswith("/app")
    ident = db.execute(select(OAuthIdentity)).scalar_one()
    assert ident.subject == "g-linked"
    assert len(db.execute(select(User)).scalars().all()) == 1


def test_link_token_cannot_be_forged(client):
    r = client.get("/api/v1/auth/google/login?link_token=forged", follow_redirects=False)
    assert "error=invalid_state" in r.headers["location"]


def test_bootstrap_admin_only_via_verified_google_email(client, monkeypatch, db):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "bootstrap_admin_email", "root@example.com")
    # Password signup with that email does NOT grant admin (email is unverified).
    _, _, body = signup(client, "root@example.com")
    assert body["user"]["role"] == "user"


def test_bootstrap_admin_granted_for_verified_google_email(client, monkeypatch, db):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "bootstrap_admin_email", "boss@example.com")
    _, q = _begin(client)
    _mock_google(monkeypatch, {"sub": "g-boss", "email": "boss@example.com", "email_verified": True, "name": "Boss"})
    client.get(f"/api/v1/auth/google/callback?code=abc&state={q['state'][0]}", follow_redirects=False)
    user = db.execute(select(User).where(User.email == "boss@example.com")).scalar_one()
    assert user.role.value == "admin"
