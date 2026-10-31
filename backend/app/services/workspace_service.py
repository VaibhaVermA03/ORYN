"""Workspace membership and authorization. Every tenant-scoped query goes through here."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import Conflict, NotFound, PermissionDenied
from app.db.models import Membership, User, UserRole, Workspace, WorkspaceRole
from app.services.audit_service import record_audit

ADMIN_ROLES = (WorkspaceRole.owner, WorkspaceRole.admin)


def create_workspace(
    db: Session, user: User, name: str, description: str | None = None
) -> tuple[Workspace, Membership]:
    ws = Workspace(name=name, description=description, created_by=user.id)
    db.add(ws)
    db.flush()
    membership = Membership(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.owner)
    db.add(membership)
    record_audit(db, action="workspace.create", actor_id=user.id, workspace_id=ws.id,
                 target_type="workspace", target_id=ws.id)
    return ws, membership


def list_user_workspaces(db: Session, user: User) -> list[tuple[Workspace, Membership]]:
    rows = db.execute(
        select(Workspace, Membership)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(Membership.user_id == user.id)
        .order_by(Workspace.created_at)
    ).all()
    return [(w, m) for w, m in rows]


def get_membership(db: Session, workspace_id: uuid.UUID, user: User) -> Membership:
    """Return the caller's membership or raise NotFound.

    A non-member gets 404 (not 403) so workspace IDs cannot be probed for existence.
    """
    m = db.execute(
        select(Membership).where(
            Membership.workspace_id == workspace_id, Membership.user_id == user.id
        )
    ).scalar_one_or_none()
    if m is None:
        raise NotFound("Workspace not found")
    return m


def require_member(db: Session, workspace_id: uuid.UUID, user: User) -> Membership:
    return get_membership(db, workspace_id, user)


def require_workspace_admin(db: Session, workspace_id: uuid.UUID, user: User) -> Membership:
    m = get_membership(db, workspace_id, user)
    if m.role not in ADMIN_ROLES:
        raise PermissionDenied("Workspace administrator access required")
    return m


def can_view_workspace_analytics(db: Session, workspace_id: uuid.UUID, user: User) -> None:
    """Workspace owners/admins, or global admins (aggregate counts only, never content)."""
    if user.role == UserRole.admin:
        if db.get(Workspace, workspace_id) is None:
            raise NotFound("Workspace not found")
        return
    require_workspace_admin(db, workspace_id, user)


def list_members(db: Session, workspace_id: uuid.UUID) -> list[tuple[Membership, User]]:
    return list(
        db.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.workspace_id == workspace_id)
            .order_by(Membership.created_at)
        ).all()
    )


def add_member(
    db: Session, workspace_id: uuid.UUID, actor: User, email: str, role: WorkspaceRole, ip: str | None
) -> tuple[Membership, User]:
    require_workspace_admin(db, workspace_id, actor)
    target = db.execute(select(User).where(User.email == email, User.is_active.is_(True))).scalar_one_or_none()
    if target is None:
        # Invitations by email are not implemented (no mail provider); the person must sign up first.
        raise NotFound("No ORYN account exists for that email. Ask them to sign up first.")
    exists = db.execute(
        select(Membership).where(Membership.workspace_id == workspace_id, Membership.user_id == target.id)
    ).scalar_one_or_none()
    if exists:
        raise Conflict("That user is already a member of this workspace")
    m = Membership(workspace_id=workspace_id, user_id=target.id, role=role)
    db.add(m)
    record_audit(db, action="member.add", actor_id=actor.id, workspace_id=workspace_id,
                 target_type="user", target_id=target.id, details={"role": role.value}, ip_address=ip)
    db.flush()
    return m, target


def change_member_role(
    db: Session, workspace_id: uuid.UUID, actor: User, user_id: uuid.UUID, role: WorkspaceRole, ip: str | None
) -> Membership:
    actor_m = require_workspace_admin(db, workspace_id, actor)
    m = db.execute(
        select(Membership).where(Membership.workspace_id == workspace_id, Membership.user_id == user_id)
    ).scalar_one_or_none()
    if m is None:
        raise NotFound("Member not found")
    if m.role == WorkspaceRole.owner:
        raise PermissionDenied("The workspace owner's role cannot be changed")
    if m.role == WorkspaceRole.admin and actor_m.role != WorkspaceRole.owner:
        raise PermissionDenied("Only the owner can change an administrator's role")
    m.role = role
    record_audit(db, action="member.role_change", actor_id=actor.id, workspace_id=workspace_id,
                 target_type="user", target_id=user_id, details={"role": role.value}, ip_address=ip)
    return m


def remove_member(
    db: Session, workspace_id: uuid.UUID, actor: User, user_id: uuid.UUID, ip: str | None
) -> None:
    actor_m = get_membership(db, workspace_id, actor)
    m = db.execute(
        select(Membership).where(Membership.workspace_id == workspace_id, Membership.user_id == user_id)
    ).scalar_one_or_none()
    if m is None:
        raise NotFound("Member not found")
    leaving_self = user_id == actor.id
    if m.role == WorkspaceRole.owner:
        raise PermissionDenied("The workspace owner cannot be removed")
    if not leaving_self:
        if actor_m.role not in ADMIN_ROLES:
            raise PermissionDenied("Workspace administrator access required")
        if m.role == WorkspaceRole.admin and actor_m.role != WorkspaceRole.owner:
            raise PermissionDenied("Only the owner can remove an administrator")
    db.delete(m)
    record_audit(db, action="member.remove", actor_id=actor.id, workspace_id=workspace_id,
                 target_type="user", target_id=user_id, ip_address=ip)
