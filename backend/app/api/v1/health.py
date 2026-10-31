from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health/live")
def liveness() -> dict:
    """Process liveness only: no dependencies are touched."""
    return {"status": "ok"}


@router.get("/health/ready")
def readiness(response: Response, db: Session = Depends(get_db)) -> dict:
    """Dependency readiness. `database` is checked live; external providers are reported
    as configured/unconfigured (no paid API calls are made by a health probe)."""
    s = get_settings()
    checks: dict[str, str] = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"

    checks["openai"] = "configured" if s.openai_api_key else "not_configured"
    checks["pinecone"] = "configured" if s.pinecone_api_key else "not_configured"
    checks["cohere"] = "configured" if s.cohere_api_key else "not_configured"
    checks["google_oauth"] = "configured" if s.google_client_id and s.google_client_secret else "not_configured"

    ready = checks["database"] == "ok"
    if not ready:
        response.status_code = 503
    return {"status": "ready" if ready else "not_ready", "checks": checks}
