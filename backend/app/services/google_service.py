"""Google OAuth 2.0 authorization-code flow (with PKCE) and OIDC ID-token validation.

Security properties:
* `state` and `nonce` are random per attempt and bound to the browser in a signed,
  HttpOnly, short-lived cookie; the callback rejects any mismatch.
* PKCE (S256) protects the authorization code in transit.
* The ID token is verified with Google's `google-auth` library (signature against Google's
  published certs, issuer, audience == our client ID, expiry); we then check the nonce.
* Identity is keyed by Google's stable `sub`. Email addresses are never taken from the browser.
* An existing password account is NEVER auto-linked by email alone; it must be linked
  explicitly from an authenticated session (see `create_link_token`).
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
import jwt
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppError, Conflict
from app.db.models import OAuthIdentity, User, UserRole
from app.services.audit_service import record_audit
from app.services.workspace_service import create_workspace

logger = logging.getLogger("oryn.google")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
STATE_COOKIE = "oryn_oauth"
STATE_TTL_SECONDS = 600
LINK_TTL_SECONDS = 300


class GoogleAuthError(AppError):
    status_code = 400
    code = "google_auth_failed"


def _sign(payload: dict, ttl: int, purpose: str) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    return jwt.encode(
        {**payload, "purpose": purpose, "iat": int(now.timestamp()), "exp": int((now + timedelta(seconds=ttl)).timestamp())},
        s.app_secret,
        algorithm="HS256",
    )


def _unsign(token: str, purpose: str) -> dict:
    try:
        data = jwt.decode(token, get_settings().app_secret, algorithms=["HS256"], options={"require": ["exp"]})
    except jwt.PyJWTError as exc:
        raise GoogleAuthError("Sign-in attempt expired or invalid", code="invalid_state") from exc
    if data.get("purpose") != purpose:
        raise GoogleAuthError("Sign-in attempt expired or invalid", code="invalid_state")
    return data


def create_link_token(user_id: uuid.UUID) -> tuple[str, int]:
    return _sign({"sub": str(user_id)}, LINK_TTL_SECONDS, "google_link"), LINK_TTL_SECONDS


def read_link_token(token: str) -> uuid.UUID:
    return uuid.UUID(_unsign(token, "google_link")["sub"])


def ensure_configured() -> None:
    s = get_settings()
    if not (s.google_client_id and s.google_client_secret):
        raise AppError("Google sign-in is not configured on this server", code="google_not_configured", status_code=503)


def begin_authorization(link_user_id: uuid.UUID | None = None) -> tuple[str, str]:
    """Return (authorization_url, signed_state_cookie_value)."""
    ensure_configured()
    s = get_settings()
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    cookie = _sign(
        {"state": state, "nonce": nonce, "verifier": verifier, "link": str(link_user_id) if link_user_id else None},
        STATE_TTL_SECONDS,
        "google_state",
    )
    params = {
        "client_id": s.google_client_id,
        "redirect_uri": s.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
        "access_type": "online",
    }
    return f"{AUTH_URL}?{urlencode(params)}", cookie


def read_state_cookie(cookie_value: str | None, returned_state: str | None) -> dict:
    if not cookie_value or not returned_state:
        raise GoogleAuthError("Sign-in attempt expired or invalid", code="invalid_state")
    data = _unsign(cookie_value, "google_state")
    if not secrets.compare_digest(str(data.get("state", "")), returned_state):
        raise GoogleAuthError("Sign-in attempt expired or invalid", code="invalid_state")
    return data


def exchange_code(code: str, verifier: str) -> dict:
    """Exchange the authorization code for tokens. Isolated so tests can mock the provider."""
    s = get_settings()
    try:
        resp = httpx.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": s.google_client_id,
                "client_secret": s.google_client_secret,
                "redirect_uri": s.google_redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        logger.warning("google_token_exchange_unreachable")
        raise GoogleAuthError("Could not reach Google. Please try again.", code="provider_unreachable") from exc
    if resp.status_code != 200:
        # Typical causes: expired/used code, redirect URI mismatch. Do not echo provider detail.
        logger.warning("google_token_exchange_rejected", extra={"status": resp.status_code})
        raise GoogleAuthError("Google rejected the sign-in code. Please try again.", code="code_rejected")
    return resp.json()


def verify_id_token(raw_id_token: str, nonce: str) -> dict:
    """Validate signature, issuer, audience and expiry (google-auth), then the nonce."""
    s = get_settings()
    try:
        claims = google_id_token.verify_oauth2_token(
            raw_id_token, google_requests.Request(), audience=s.google_client_id
        )
    except ValueError as exc:
        raise GoogleAuthError("Google identity could not be verified", code="invalid_id_token") from exc
    if claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise GoogleAuthError("Google identity could not be verified", code="invalid_id_token")
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise GoogleAuthError("Google identity could not be verified", code="invalid_nonce")
    return claims


def resolve_identity(db: Session, claims: dict, link_user_id: uuid.UUID | None, ip: str | None) -> User:
    """Map verified Google claims to a user (login, explicit link, or first-time signup)."""
    sub = claims.get("sub")
    email = (claims.get("email") or "").strip().lower()
    if not sub or not email:
        raise GoogleAuthError("Google did not return an email address", code="missing_email")
    if claims.get("email_verified") is not True:
        raise GoogleAuthError("Your Google email address is not verified", code="email_unverified")

    identity = db.execute(
        select(OAuthIdentity).where(OAuthIdentity.provider == "google", OAuthIdentity.subject == sub)
    ).scalar_one_or_none()

    if link_user_id is not None:
        user = db.get(User, link_user_id)
        if user is None or not user.is_active:
            raise GoogleAuthError("Account not found", code="link_failed")
        if identity is not None and identity.user_id != user.id:
            raise Conflict("That Google account is already linked to another ORYN account", code="identity_in_use")
        if identity is None:
            db.add(OAuthIdentity(user_id=user.id, provider="google", subject=sub, email=email))
            record_audit(db, action="auth.google_linked", actor_id=user.id, ip_address=ip)
        return user

    if identity is not None:
        user = db.get(User, identity.user_id)
        if user is None or not user.is_active:
            raise GoogleAuthError("This account is disabled", code="account_disabled")
        record_audit(db, action="auth.login_google", actor_id=user.id, ip_address=ip)
        return user

    existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if existing is not None:
        if not existing.email_verified:
            # Possible pre-registration hijack: refuse to merge. The owner can sign in with
            # their password and link Google explicitly from Settings.
            raise GoogleAuthError(
                "An account with this email already exists. Sign in with your password, then link Google in Settings.",
                code="account_exists",
            )
        db.add(OAuthIdentity(user_id=existing.id, provider="google", subject=sub, email=email))
        record_audit(db, action="auth.google_linked", actor_id=existing.id, ip_address=ip)
        return existing

    s = get_settings()
    is_bootstrap_admin = bool(s.bootstrap_admin_email) and email == s.bootstrap_admin_email.strip().lower()
    name = (claims.get("name") or email.split("@")[0])[:120]
    user = User(
        email=email,
        email_verified=True,  # Google asserted a verified address
        password_hash=None,
        display_name=name,
        role=UserRole.admin if is_bootstrap_admin else UserRole.user,
    )
    db.add(user)
    db.flush()
    db.add(OAuthIdentity(user_id=user.id, provider="google", subject=sub, email=email))
    create_workspace(db, user, f"{name}'s workspace")
    record_audit(db, action="user.signup_google", actor_id=user.id, target_type="user", target_id=user.id, ip_address=ip)
    if is_bootstrap_admin:
        record_audit(db, action="user.bootstrap_admin", actor_id=user.id, target_type="user", target_id=user.id)
    return user
