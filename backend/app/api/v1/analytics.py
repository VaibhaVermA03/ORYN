from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_global_admin
from app.db.models import User
from app.db.session import get_db
from app.services import analytics_service as analytics
from app.services import workspace_service as ws_svc

router = APIRouter(tags=["analytics"])


@router.get("/workspaces/{workspace_id}/analytics", response_model=dict[str, Any])
def workspace_analytics(
    workspace_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Aggregated measurements for a workspace. Workspace owners/admins and platform admins only."""
    ws_svc.can_view_workspace_analytics(db, workspace_id, user)
    return analytics.workspace_analytics(db, workspace_id)


@router.get("/workspaces/{workspace_id}/audit-events", response_model=dict[str, Any])
def workspace_audit_events(
    workspace_id: uuid.UUID,
    action: str | None = Query(default=None, max_length=64),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ws_svc.can_view_workspace_analytics(db, workspace_id, user)
    items, total = analytics.list_audit_events(db, workspace_id=workspace_id, action=action, page=page, page_size=page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/admin/overview", response_model=dict[str, Any])
def admin_overview(_: User = Depends(require_global_admin), db: Session = Depends(get_db)):
    """Platform-wide aggregate counts for global administrators (no content, no per-user data)."""
    return analytics.platform_overview(db)


@router.get("/admin/audit-events", response_model=dict[str, Any])
def admin_audit_events(
    workspace_id: uuid.UUID | None = None,
    action: str | None = Query(default=None, max_length=64),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: User = Depends(require_global_admin),
    db: Session = Depends(get_db),
):
    items, total = analytics.list_audit_events(db, workspace_id=workspace_id, action=action, page=page, page_size=page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}
