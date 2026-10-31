"""Email/password accounts and refresh-session lifecycle."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError, Conflict
from app.core.security import (
    DUMMY_HASH,
    create_access_token,
    hash_password,
    hash_token,
    new_opaque_token,
    password_needs_rehash,
    verify_password,
)
from app.db.base import utcnow
from app.db.models import AuthSession, OAuthIdentity, User, UserRole
from app.services.audit_service import record_audit
from app.services.workspace_service import create_workspace

# A refresh token that was rotated this recently is treated as a benign concurrent refresh
# (e.g. two tabs) instead of token theft.
ROTATION_GRACE_SECONDS = 10


def user_to_out(db: Session, user: User) -> dict:
    google = db.execute(
        select(OAuthIdentity.id).where(OAuthIdentity.user_id == user.id, OAuthIdentity.provider == "google")
    ).first()
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role.value,
        "email_verified": user.email_verified,
        "has_password": user.password_hash is not None,
        "google_linked": google is not None,
    }


def signup(db: Session, *, email: str, password: str, display_name: str, ip: str | None) -> User:
    existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if existing:
        raise Conflict("An account with this email already exists", code="email_taken")
    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=display_name,
        role=UserRole.user,
        email_verified=False,  # no email provider is configured, so we never claim verification
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:  # concurrent signup with the same email
        db.rollback()
        raise Conflict("An account with this email already exists", code="email_taken") from exc
    create_workspace(db, user, f"{display_name}'s workspace")
    record_audit(db, action="user.signup", actor_id=user.id, target_type="user", target_id=user.id, ip_address=ip)
    return user


def authenticate(db: Session, *, email: str, password: str, ip: str | None) -> User:
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    # Always run a hash verification so response time does not reveal whether the email exists.
    stored = user.password_hash if user and user.password_hash else DUMMY_HASH
    ok = verify_password(password, stored)
    if not (user and user.password_hash and ok and user.is_active):
        record_audit(db, action="auth.login_failed", actor_id=user.id if user else None, ip_address=ip)
        db.commit()
        raise AuthenticationError("Incorrect email or password", code="invalid_credentials")
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    record_audit(db, action="auth.login", actor_id=user.id, ip_address=ip)
    return user


def issue_session(
    db: Session,
    user: User,
    *,
    family_id: uuid.UUID | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[str, int, str]:
    """Create a refresh session; return (access_token, expires_in, raw_refresh_token)."""
    s = get_settings()
    raw = new_opaque_token()
    session = AuthSession(
        user_id=user.id,
        family_id=family_id or uuid.uuid4(),
        token_hash=hash_token(raw),
        user_agent=(user_agent or "")[:255] or None,
        ip_address=ip,
        expires_at=utcnow() + timedelta(days=s.refresh_token_ttl_days),
    )
    db.add(session)
    db.flush()
    access, expires_in = create_access_token(user.id, user.role.value, session.id)
    return access, expires_in, raw


def rotate_refresh(
    db: Session, raw_token: str | None, *, ip: str | None, user_agent: str | None
) -> tuple[User, str, int, str]:
    if not raw_token:
        raise AuthenticationError("No active session", code="no_session")
    session = db.execute(
        select(AuthSession).where(AuthSession.token_hash == hash_token(raw_token)).with_for_update()
    ).scalar_one_or_none()
    if session is None:
        raise AuthenticationError("Session is not valid", code="invalid_session")

    now = utcnow()
    if session.revoked_at is not None or session.rotated_at is not None:
        recently_rotated = (
            session.rotated_at is not None
            and session.revoked_at is None
            and (now - session.rotated_at).total_seconds() <= ROTATION_GRACE_SECONDS
        )
        if not recently_rotated:
            # Reuse of a consumed token: assume theft and revoke the whole family.
            revoke_family(db, session.family_id)
            record_audit(db, action="auth.refresh_reuse_detected", actor_id=session.user_id, ip_address=ip)
            db.commit()
        raise AuthenticationError("Session is not valid", code="invalid_session")
    if session.expires_at <= now:
        raise AuthenticationError("Session expired", code="session_expired")

    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Session is not valid", code="invalid_session")

    session.rotated_at = now
    access, expires_in, new_raw = issue_session(
        db, user, family_id=session.family_id, ip=ip, user_agent=user_agent
    )
    return user, access, expires_in, new_raw


def revoke_family(db: Session, family_id: uuid.UUID) -> None:
    db.execute(
        update(AuthSession)
        .where(AuthSession.family_id == family_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


def logout(db: Session, raw_token: str | None, *, ip: str | None) -> None:
    """Revoke the whole session family for the presented refresh token (idempotent)."""
    if not raw_token:
        return
    session = db.execute(
        select(AuthSession).where(AuthSession.token_hash == hash_token(raw_token))
    ).scalar_one_or_none()
    if session is None:
        return
    revoke_family(db, session.family_id)
    record_audit(db, action="auth.logout", actor_id=session.user_id, ip_address=ip)


def session_is_active(db: Session, session_id: uuid.UUID) -> bool:
    """True while the refresh family behind an access token has not been revoked."""
    row = db.execute(select(AuthSession).where(AuthSession.id == session_id)).scalar_one_or_none()
    if row is None:
        return False
    family_alive = db.execute(
        select(AuthSession.id).where(
            AuthSession.family_id == row.family_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > utcnow(),
        )
    ).first()
    return family_alive is not None
