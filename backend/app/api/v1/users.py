from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.rate_limit import client_ip
from app.db.models import User
from app.db.session import get_db
from app.schemas.auth import UpdateProfileRequest, UserOut
from app.services import auth_service
from app.services.audit_service import record_audit

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return auth_service.user_to_out(db, user)


@router.patch("/me", response_model=UserOut)
def update_me(
    body: UpdateProfileRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user.display_name = body.display_name
    record_audit(db, action="user.profile_update", actor_id=user.id, target_type="user",
                 target_id=user.id, ip_address=client_ip(request))
    db.commit()
    return auth_service.user_to_out(db, user)
