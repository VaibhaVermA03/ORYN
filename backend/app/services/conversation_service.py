"""Conversations, messages and feedback. Conversations are private to their author and are always
looked up by (id, workspace_id, user_id), so another user (even in the same workspace) gets 404."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import NotFound
from app.db.base import utcnow
from app.db.models import Conversation, Feedback, Message, MessageRole, MessageStatus, User


@dataclass
class ChatContext:
    workspace_id: uuid.UUID
    user_id: uuid.UUID
    conversation_id: uuid.UUID
    user_message_id: uuid.UUID
    assistant_message_id: uuid.UUID
    question: str
    history: list[dict[str, str]] = field(default_factory=list)


def get_conversation(db: Session, workspace_id: uuid.UUID, user: User, conversation_id: uuid.UUID) -> Conversation:
    conv = db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.workspace_id == workspace_id,
            Conversation.user_id == user.id,
        )
    ).scalar_one_or_none()
    if conv is None:
        raise NotFound("Conversation not found")
    return conv


def start_turn(
    db: Session, *, workspace_id: uuid.UUID, user: User, conversation_id: uuid.UUID | None, question: str
) -> ChatContext:
    """Persist the user's message and an empty assistant message (status=streaming)."""
    s = get_settings()
    if conversation_id is None:
        title = " ".join(question.split())[:60] or "New conversation"
        conv = Conversation(workspace_id=workspace_id, user_id=user.id, title=title)
        db.add(conv)
        db.flush()
        history: list[dict[str, str]] = []
    else:
        conv = get_conversation(db, workspace_id, user, conversation_id)
        prior = db.execute(
            select(Message)
            .where(Message.conversation_id == conv.id, Message.status == MessageStatus.complete)
            .order_by(Message.created_at.desc())
            .limit(s.chat_history_messages)
        ).scalars().all()
        history = [{"role": m.role.value, "content": m.content} for m in reversed(prior) if m.content]
    user_msg = Message(conversation_id=conv.id, role=MessageRole.user, content=question, status=MessageStatus.complete)
    db.add(user_msg)
    db.flush()
    assistant = Message(conversation_id=conv.id, role=MessageRole.assistant, content="", status=MessageStatus.streaming)
    db.add(assistant)
    conv.updated_at = utcnow()
    db.flush()
    return ChatContext(
        workspace_id=workspace_id, user_id=user.id, conversation_id=conv.id, user_message_id=user_msg.id,
        assistant_message_id=assistant.id, question=question, history=history,
    )


def list_conversations(
    db: Session, workspace_id: uuid.UUID, user: User, page: int, page_size: int
) -> tuple[list[Conversation], int]:
    where = (Conversation.workspace_id == workspace_id, Conversation.user_id == user.id)
    total = db.execute(select(func.count()).select_from(Conversation).where(*where)).scalar_one()
    items = db.execute(
        select(Conversation).where(*where).order_by(Conversation.updated_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()
    return list(items), total


def conversation_messages(db: Session, conv: Conversation, user: User) -> list[dict]:
    """Messages with the caller's feedback. Abandoned 'streaming' rows (server died) are failed."""
    s = get_settings()
    stale_before = utcnow() - timedelta(seconds=s.chat_total_timeout_seconds * 2)
    msgs = db.execute(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
    ).scalars().all()
    ratings = dict(
        db.execute(
            select(Feedback.message_id, Feedback.rating).where(
                Feedback.user_id == user.id, Feedback.message_id.in_([m.id for m in msgs] or [uuid.UUID(int=0)])
            )
        ).all()
    )
    out = []
    for m in msgs:
        if m.status == MessageStatus.streaming and m.created_at < stale_before:
            m.status, m.error_code = MessageStatus.failed, "interrupted"
        out.append({
            "id": m.id, "role": m.role.value, "content": m.content, "status": m.status.value,
            "sources": m.sources or [], "insufficient_context": m.insufficient_context,
            "error_code": m.error_code, "feedback": ratings.get(m.id), "created_at": m.created_at,
        })
    return out


def set_feedback(
    db: Session, *, workspace_id: uuid.UUID, user: User, message_id: uuid.UUID, rating: int, comment: str | None
) -> Feedback:
    msg = db.execute(
        select(Message).join(Conversation, Conversation.id == Message.conversation_id).where(
            Message.id == message_id, Message.role == MessageRole.assistant,
            Conversation.workspace_id == workspace_id, Conversation.user_id == user.id,
        )
    ).scalar_one_or_none()
    if msg is None:
        raise NotFound("Message not found")
    fb = db.execute(
        select(Feedback).where(Feedback.message_id == message_id, Feedback.user_id == user.id)
    ).scalar_one_or_none()
    if fb is None:
        fb = Feedback(message_id=message_id, user_id=user.id, workspace_id=workspace_id, rating=rating, comment=comment)
        db.add(fb)
    else:
        fb.rating, fb.comment = rating, comment
    db.flush()
    return fb


def clear_feedback(db: Session, *, workspace_id: uuid.UUID, user: User, message_id: uuid.UUID) -> None:
    fb = db.execute(
        select(Feedback).where(
            Feedback.message_id == message_id, Feedback.user_id == user.id, Feedback.workspace_id == workspace_id
        )
    ).scalar_one_or_none()
    if fb is None:
        raise NotFound("Feedback not found")
    db.delete(fb)
