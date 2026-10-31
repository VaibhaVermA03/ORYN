from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.db.models import AuditEvent


def record_audit(
    db: Session,
    *,
    action: str,
    actor_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: str | uuid.UUID | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
) -> None:
    """Append an audit event to the current transaction (committed with the caller's work)."""
    db.add(
        AuditEvent(
            actor_id=actor_id,
            workspace_id=workspace_id,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            details=details,
            ip_address=ip_address,
        )
    )
