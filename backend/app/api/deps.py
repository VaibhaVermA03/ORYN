"""Shared FastAPI dependencies: authentication, roles, cookie CSRF guard."""

from __future__ import annotations

import uuid

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError, PermissionDenied
from app.core.security import decode_access_token
from app.db.models import User, UserRole
from app.db.session import get_db
from app.services.auth_service import session_is_active

REFRESH_COOKIE = "oryn_refresh"
CSRF_HEADER = "x-requested-by"
CSRF_HEADER_VALUE = "oryn-web"


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthenticationError("Authentication required")
    claims = decode_access_token(token)
    user = db.get(User, uuid.UUID(claims["sub"]))
    if user is None or not user.is_active:
        raise AuthenticationError("Authentication required")
    # A revoked refresh family (logout, theft detection) also invalidates its access tokens.
    if not session_is_active(db, uuid.UUID(claims["sid"])):
        raise AuthenticationError("Session has been revoked", code="session_revoked")
    request.state.user_id = user.id
    return user


def require_global_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.admin:
        raise PermissionDenied("Administrator access required")
    return user


def cookie_csrf_guard(request: Request) -> None:
    """CSRF defence for endpoints authenticated by the refresh cookie.

    1. The request must carry a custom header, which forces a CORS preflight that only
       explicitly trusted origins can pass.
    2. If the browser sent an Origin header it must be in the trusted-origin list.
    Combined with SameSite cookies this blocks cross-site request forgery.
    """
    if request.headers.get(CSRF_HEADER) != CSRF_HEADER_VALUE:
        raise PermissionDenied("Missing CSRF header", code="csrf_failed")
    origin = request.headers.get("origin")
    if origin is not None and origin.rstrip("/") not in get_settings().allowed_origins:
        raise PermissionDenied("Origin not allowed", code="csrf_failed")
