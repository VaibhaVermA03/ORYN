from __future__ import annotations

import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import REFRESH_COOKIE, cookie_csrf_guard, get_current_user
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.rate_limit import client_ip, limiter
from app.db.models import User
from app.db.session import get_db
from app.schemas.auth import AuthResponse, LinkIntentResponse, LoginRequest, SignupRequest, UserOut
from app.services import auth_service, google_service

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger("oryn.auth")


def _set_refresh_cookie(response: Response, raw: str) -> None:
    s = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        raw,
        max_age=s.refresh_token_ttl_days * 86400,
        httponly=True,
        secure=s.cookie_secure,
        samesite=s.cookie_samesite,
        domain=s.cookie_domain,
        path=f"{s.api_prefix}/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(
        REFRESH_COOKIE, path=f"{s.api_prefix}/auth", domain=s.cookie_domain,
        secure=s.cookie_secure, httponly=True, samesite=s.cookie_samesite,
    )


def _auth_payload(db: Session, user: User, access: str, expires_in: int) -> AuthResponse:
    return AuthResponse(access_token=access, expires_in=expires_in, user=UserOut(**auth_service.user_to_out(db, user)))


@router.post("/signup", response_model=AuthResponse, status_code=201)
def signup(body: SignupRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_ip(request)
    limiter.hit(f"auth:ip:{ip}", get_settings().rate_limit_auth_per_minute)
    user = auth_service.signup(db, email=body.email, password=body.password, display_name=body.display_name, ip=ip)
    access, expires_in, raw = auth_service.issue_session(db, user, ip=ip, user_agent=request.headers.get("user-agent"))
    db.commit()
    _set_refresh_cookie(response, raw)
    return _auth_payload(db, user, access, expires_in)


@router.post("/login", response_model=AuthResponse)
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_ip(request)
    limit = get_settings().rate_limit_auth_per_minute
    limiter.hit(f"auth:ip:{ip}", limit)
    limiter.hit(f"auth:email:{body.email}", limit)
    user = auth_service.authenticate(db, email=body.email, password=body.password, ip=ip)
    access, expires_in, raw = auth_service.issue_session(db, user, ip=ip, user_agent=request.headers.get("user-agent"))
    db.commit()
    _set_refresh_cookie(response, raw)
    return _auth_payload(db, user, access, expires_in)


@router.post("/refresh", response_model=AuthResponse, dependencies=[Depends(cookie_csrf_guard)])
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_ip(request)
    limiter.hit(f"refresh:ip:{ip}", get_settings().rate_limit_auth_per_minute * 6)
    try:
        user, access, expires_in, raw = auth_service.rotate_refresh(
            db, request.cookies.get(REFRESH_COOKIE), ip=ip, user_agent=request.headers.get("user-agent")
        )
    except AppError:
        db.rollback()
        _clear_refresh_cookie(response)
        raise
    db.commit()
    _set_refresh_cookie(response, raw)
    return _auth_payload(db, user, access, expires_in)


@router.post("/logout", status_code=204, dependencies=[Depends(cookie_csrf_guard)])
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    auth_service.logout(db, request.cookies.get(REFRESH_COOKIE), ip=client_ip(request))
    db.commit()
    _clear_refresh_cookie(response)
    response.status_code = 204
    return response


# --------------------------------------------------------------------------- Google OAuth


def _login_redirect(error: str) -> RedirectResponse:
    s = get_settings()
    resp = RedirectResponse(f"{s.frontend_login_url}?{urlencode({'error': error})}", status_code=302)
    resp.delete_cookie(google_service.STATE_COOKIE, path=f"{s.api_prefix}/auth/google")
    return resp


@router.post("/google/link-intent", response_model=LinkIntentResponse)
def google_link_intent(user: User = Depends(get_current_user)):
    """Authenticated user asks to link Google; returns a short-lived token for /google/login."""
    google_service.ensure_configured()
    token, ttl = google_service.create_link_token(user.id)
    return LinkIntentResponse(link_token=token, expires_in=ttl)


@router.get("/google/login")
def google_login(request: Request, link_token: str | None = Query(default=None)):
    limiter.hit(f"auth:ip:{client_ip(request)}", get_settings().rate_limit_auth_per_minute)
    s = get_settings()
    try:
        link_user = google_service.read_link_token(link_token) if link_token else None
        url, cookie = google_service.begin_authorization(link_user)
    except AppError as exc:
        return _login_redirect(exc.code)
    resp = RedirectResponse(url, status_code=302)
    resp.set_cookie(
        google_service.STATE_COOKIE, cookie, max_age=google_service.STATE_TTL_SECONDS, httponly=True,
        secure=s.cookie_secure, samesite="lax", domain=s.cookie_domain, path=f"{s.api_prefix}/auth/google",
    )
    return resp


@router.get("/google/callback")
def google_callback(
    request: Request,
    db: Session = Depends(get_db),
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    s = get_settings()
    ip = client_ip(request)
    limiter.hit(f"auth:ip:{ip}", s.rate_limit_auth_per_minute)
    try:
        google_service.ensure_configured()
        if error:  # user cancelled or Google returned an error
            return _login_redirect("access_denied" if error == "access_denied" else "google_error")
        saved = google_service.read_state_cookie(request.cookies.get(google_service.STATE_COOKIE), state)
        if not code:
            return _login_redirect("missing_code")
        tokens = google_service.exchange_code(code, saved["verifier"])
        raw_id = tokens.get("id_token")
        if not raw_id:
            return _login_redirect("invalid_id_token")
        claims = google_service.verify_id_token(raw_id, saved["nonce"])
        link_user_id = None
        if saved.get("link"):
            import uuid as _uuid

            link_user_id = _uuid.UUID(saved["link"])
        user = google_service.resolve_identity(db, claims, link_user_id, ip)
        access, _, raw = auth_service.issue_session(db, user, ip=ip, user_agent=request.headers.get("user-agent"))
        db.commit()
    except AppError as exc:
        db.rollback()
        logger.info("google_callback_failed", extra={"code": exc.code})
        return _login_redirect(exc.code)

    resp = RedirectResponse(s.frontend_post_login_url, status_code=302)
    resp.delete_cookie(google_service.STATE_COOKIE, path=f"{s.api_prefix}/auth/google")
    _set_refresh_cookie(resp, raw)
    return resp
