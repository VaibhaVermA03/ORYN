from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.exceptions import AppError, ProviderError
from app.core.rate_limit import limiter
from app.db.models import User
from app.db.session import get_db
from app.schemas.chat import (
    ChatRequest,
    ConversationDetail,
    ConversationOut,
    ConversationPage,
    FeedbackRequest,
    MessageOut,
    RenameRequest,
)
from app.services import conversation_service as conv_svc
from app.services import workspace_service as ws_svc
from app.services.embedding_service import get_embedder
from app.services.llm_service import get_llm
from app.services.rag_service import stream_chat
from app.services.reranking_service import get_reranker
from app.services.vector_service import get_vector_store

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["chat"])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # tell nginx-style proxies not to buffer the stream
}


def _ensure_providers() -> None:
    """Fail fast (HTTP 503) when a required provider is not configured, before streaming starts."""
    try:
        get_embedder(), get_vector_store(), get_reranker(), get_llm()
    except ProviderError as exc:
        raise AppError(exc.message, code="provider_not_configured", status_code=503) from exc


@router.post("/chat/stream")
def chat_stream(
    workspace_id: uuid.UUID,
    body: ChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Server-Sent Events chat endpoint. See `app/services/rag_service.py` for the event protocol."""
    ws_svc.require_member(db, workspace_id, user)
    limiter.hit(f"chat:{user.id}", get_settings().rate_limit_chat_per_minute)
    _ensure_providers()
    ctx = conv_svc.start_turn(
        db, workspace_id=workspace_id, user=user, conversation_id=body.conversation_id, question=body.message
    )
    db.commit()
    # The generator opens its own DB sessions; the request-scoped session is closed by then.
    return StreamingResponse(stream_chat(ctx), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/conversations", response_model=ConversationPage)
def list_conversations(
    workspace_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ws_svc.require_member(db, workspace_id, user)
    items, total = conv_svc.list_conversations(db, workspace_id, user, page, page_size)
    return ConversationPage(
        items=[ConversationOut.model_validate(c) for c in items], total=total, page=page, page_size=page_size
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    workspace_id: uuid.UUID, conversation_id: uuid.UUID,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    ws_svc.require_member(db, workspace_id, user)
    conv = conv_svc.get_conversation(db, workspace_id, user, conversation_id)
    messages = conv_svc.conversation_messages(db, conv, user)
    db.commit()  # persists any interrupted-message repair
    return ConversationDetail(
        conversation=ConversationOut.model_validate(conv), messages=[MessageOut(**m) for m in messages]
    )


@router.patch("/conversations/{conversation_id}", response_model=ConversationOut)
def rename_conversation(
    workspace_id: uuid.UUID, conversation_id: uuid.UUID, body: RenameRequest,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    ws_svc.require_member(db, workspace_id, user)
    conv = conv_svc.get_conversation(db, workspace_id, user, conversation_id)
    conv.title = body.title
    db.commit()
    return ConversationOut.model_validate(conv)


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    workspace_id: uuid.UUID, conversation_id: uuid.UUID,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    ws_svc.require_member(db, workspace_id, user)
    conv = conv_svc.get_conversation(db, workspace_id, user, conversation_id)
    db.delete(conv)
    db.commit()


@router.put("/messages/{message_id}/feedback", status_code=204)
def put_feedback(
    workspace_id: uuid.UUID, message_id: uuid.UUID, body: FeedbackRequest,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    ws_svc.require_member(db, workspace_id, user)
    conv_svc.set_feedback(
        db, workspace_id=workspace_id, user=user, message_id=message_id, rating=body.rating, comment=body.comment
    )
    db.commit()


@router.delete("/messages/{message_id}/feedback", status_code=204)
def delete_feedback(
    workspace_id: uuid.UUID, message_id: uuid.UUID,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    ws_svc.require_member(db, workspace_id, user)
    conv_svc.clear_feedback(db, workspace_id=workspace_id, user=user, message_id=message_id)
    db.commit()


__all__ = ["router", "Request"]
