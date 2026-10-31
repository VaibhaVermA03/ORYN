from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.exceptions import NotFound
from app.core.rate_limit import client_ip
from app.db.models import User, WorkspaceRole
from app.db.session import get_db
from app.schemas.workspace import (
    MemberAdd,
    MemberOut,
    MemberUpdate,
    WorkspaceCreate,
    WorkspaceOut,
    WorkspaceUpdate,
)
from app.services import document_service
from app.services import workspace_service as ws_svc
from app.services.audit_service import record_audit

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _ws_out(ws, role: WorkspaceRole) -> WorkspaceOut:
    return WorkspaceOut(id=ws.id, name=ws.name, description=ws.description, role=role.value, created_at=ws.created_at)


@router.get("", response_model=list[WorkspaceOut])
def list_workspaces(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [_ws_out(w, m.role) for w, m in ws_svc.list_user_workspaces(db, user)]


@router.post("", response_model=WorkspaceOut, status_code=201)
def create_workspace(body: WorkspaceCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ws, m = ws_svc.create_workspace(db, user, body.name, body.description)
    db.commit()
    return _ws_out(ws, m.role)


@router.get("/{workspace_id}", response_model=WorkspaceOut)
def get_workspace(workspace_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = ws_svc.require_member(db, workspace_id, user)
    return _ws_out(m.workspace, m.role)


@router.patch("/{workspace_id}", response_model=WorkspaceOut)
def update_workspace(
    workspace_id: uuid.UUID,
    body: WorkspaceUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    m = ws_svc.require_workspace_admin(db, workspace_id, user)
    ws = m.workspace
    if body.name is not None:
        ws.name = " ".join(body.name.split())
    if body.description is not None:
        ws.description = body.description
    record_audit(db, action="workspace.update", actor_id=user.id, workspace_id=ws.id,
                 target_type="workspace", target_id=ws.id, ip_address=client_ip(request))
    db.commit()
    return _ws_out(ws, m.role)


@router.delete("/{workspace_id}", status_code=204)
def delete_workspace(
    workspace_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Owner only. Deletes the workspace's vectors, stored files and all database records."""
    m = ws_svc.require_workspace_admin(db, workspace_id, user)
    if m.role != WorkspaceRole.owner:
        from app.core.exceptions import PermissionDenied

        raise PermissionDenied("Only the workspace owner can delete it")
    document_service.delete_workspace_data(db, workspace_id)  # raises before any DB change on failure
    record_audit(db, action="workspace.delete", actor_id=user.id, target_type="workspace",
                 target_id=workspace_id, details={"name": m.workspace.name}, ip_address=client_ip(request))
    db.delete(m.workspace)
    db.commit()


@router.get("/{workspace_id}/members", response_model=list[MemberOut])
def list_members(workspace_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ws_svc.require_member(db, workspace_id, user)
    return [
        MemberOut(user_id=u.id, email=u.email, display_name=u.display_name, role=m.role.value, joined_at=m.created_at)
        for m, u in ws_svc.list_members(db, workspace_id)
    ]


@router.post("/{workspace_id}/members", response_model=MemberOut, status_code=201)
def add_member(
    workspace_id: uuid.UUID,
    body: MemberAdd,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    m, target = ws_svc.add_member(db, workspace_id, user, body.email, WorkspaceRole(body.role), client_ip(request))
    db.commit()
    return MemberOut(user_id=target.id, email=target.email, display_name=target.display_name,
                     role=m.role.value, joined_at=m.created_at)


@router.patch("/{workspace_id}/members/{user_id}", response_model=MemberOut)
def update_member(
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    body: MemberUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    m = ws_svc.change_member_role(db, workspace_id, user, user_id, WorkspaceRole(body.role), client_ip(request))
    db.commit()
    target = db.get(User, user_id)
    if target is None:
        raise NotFound("Member not found")
    return MemberOut(user_id=target.id, email=target.email, display_name=target.display_name,
                     role=m.role.value, joined_at=m.created_at)


@router.delete("/{workspace_id}/members/{user_id}", status_code=204)
def remove_member(
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ws_svc.remove_member(db, workspace_id, user, user_id, client_ip(request))
    db.commit()
