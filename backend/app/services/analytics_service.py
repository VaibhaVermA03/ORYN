"""Aggregations over real database records. Nothing here is estimated or pre-populated; when there
is no data the fields are zero/null and the UI shows an empty state."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.models import (
    AuditEvent,
    Conversation,
    Document,
    DocumentStatus,
    EvaluationRun,
    Feedback,
    QueryMetric,
    User,
    Workspace,
)

WINDOW_DAYS = 30
SERIES_DAYS = 14


def _r(value: Any, digits: int = 1) -> float | None:
    return None if value is None else round(float(value), digits)


def workspace_analytics(db: Session, workspace_id: uuid.UUID) -> dict[str, Any]:
    now = utcnow()
    since = now - timedelta(days=WINDOW_DAYS)

    by_status = {s.value: 0 for s in DocumentStatus}
    for status, count in db.execute(
        select(Document.status, func.count()).where(Document.workspace_id == workspace_id).group_by(Document.status)
    ):
        by_status[status.value] = count
    chunks = db.execute(
        select(func.coalesce(func.sum(Document.chunk_count), 0)).where(
            Document.workspace_id == workspace_id, Document.status == DocumentStatus.ready
        )
    ).scalar_one()
    failures = [
        {"id": str(d.id), "filename": d.filename, "error_summary": d.error_summary, "updated_at": d.updated_at}
        for d in db.execute(
            select(Document).where(Document.workspace_id == workspace_id, Document.status == DocumentStatus.failed)
            .order_by(Document.updated_at.desc()).limit(10)
        ).scalars()
    ]

    m = QueryMetric
    scope = (m.workspace_id == workspace_id, m.created_at >= since)
    totals = db.execute(
        select(
            func.count(),
            func.count().filter(m.status == "ok"),
            func.count().filter(m.status == "error"),
            func.count().filter(m.status == "cancelled"),
            func.count().filter(m.provider_error.is_not(None)),
            func.count(func.distinct(m.user_id)),
            func.count().filter(m.created_at >= now - timedelta(days=7)),
        ).where(*scope)
    ).one()
    total, ok, errors, cancelled, provider_errors, active_users, last7 = totals

    lat = db.execute(
        select(
            func.avg(m.total_ms),
            func.percentile_cont(0.5).within_group(m.total_ms),
            func.percentile_cont(0.95).within_group(m.total_ms),
            func.avg(func.coalesce(m.dense_ms, 0) + func.coalesce(m.lexical_ms, 0) + func.coalesce(m.fusion_ms, 0)),
            func.avg(m.rerank_ms),
            func.avg(m.generation_ms),
        ).where(*scope, m.status == "ok", m.total_ms.is_not(None))
    ).one()

    provider_breakdown = {
        p: c for p, c in db.execute(
            select(m.provider_error, func.count()).where(*scope, m.provider_error.is_not(None)).group_by(m.provider_error)
        )
    }

    day = func.date_trunc("day", m.created_at)
    per_day = {
        d.date(): c for d, c in db.execute(
            select(day, func.count()).where(m.workspace_id == workspace_id, m.created_at >= now - timedelta(days=SERIES_DAYS - 1))
            .group_by(day)
        )
    }
    series = []
    for i in range(SERIES_DAYS - 1, -1, -1):
        d = (now - timedelta(days=i)).date()
        series.append({"date": d.isoformat(), "queries": per_day.get(d, 0)})

    conversations = db.execute(
        select(func.count()).select_from(Conversation).where(Conversation.workspace_id == workspace_id)
    ).scalar_one()

    up, down, with_comment = db.execute(
        select(
            func.count().filter(Feedback.rating == 1),
            func.count().filter(Feedback.rating == -1),
            func.count().filter(Feedback.comment.is_not(None)),
        ).where(Feedback.workspace_id == workspace_id)
    ).one()

    latest_eval = db.execute(
        select(EvaluationRun).where(EvaluationRun.workspace_id == workspace_id, EvaluationRun.status == "completed")
        .order_by(EvaluationRun.created_at.desc()).limit(1)
    ).scalar_one_or_none()
    eval_runs = db.execute(
        select(func.count()).select_from(EvaluationRun).where(EvaluationRun.workspace_id == workspace_id)
    ).scalar_one()

    return {
        "window_days": WINDOW_DAYS,
        "documents": {
            "total": sum(by_status.values()), "by_status": by_status, "indexed_chunks": int(chunks),
            "recent_failures": failures,
        },
        "usage": {
            "queries_30d": total, "queries_7d": last7, "active_users_30d": active_users,
            "conversations_total": conversations, "daily_queries": series,
        },
        "latency_ms": {
            "samples": ok, "avg_total": _r(lat[0]), "p50_total": _r(lat[1]), "p95_total": _r(lat[2]),
            "avg_retrieval": _r(lat[3]), "avg_rerank": _r(lat[4]), "avg_generation": _r(lat[5]),
        },
        "reliability": {
            "ok": ok, "errors": errors, "cancelled": cancelled, "provider_errors": provider_errors,
            "provider_error_rate": _r(provider_errors / total, 4) if total else None,
            "by_provider": provider_breakdown,
        },
        "feedback": {
            "up": up, "down": down, "with_comment": with_comment,
            "satisfaction": _r(up / (up + down), 4) if (up + down) else None,
        },
        "evaluation": {
            "runs": eval_runs,
            "latest": None if latest_eval is None else {
                "id": str(latest_eval.id), "dataset_name": latest_eval.dataset_name,
                "sample_count": latest_eval.sample_count, "metrics": latest_eval.metrics,
                "created_at": latest_eval.created_at,
            },
        },
    }


def platform_overview(db: Session) -> dict[str, Any]:
    """Global-admin aggregate counts. Never includes document, question or answer content."""
    since = utcnow() - timedelta(days=WINDOW_DAYS)
    q_total, q_err = db.execute(
        select(func.count(), func.count().filter(QueryMetric.status == "error")).where(QueryMetric.created_at >= since)
    ).one()
    by_status = {s.value: 0 for s in DocumentStatus}
    for status, count in db.execute(select(Document.status, func.count()).group_by(Document.status)):
        by_status[status.value] = count
    return {
        "window_days": WINDOW_DAYS,
        "users": db.execute(select(func.count()).select_from(User)).scalar_one(),
        "workspaces": db.execute(select(func.count()).select_from(Workspace)).scalar_one(),
        "documents": {"total": sum(by_status.values()), "by_status": by_status},
        "queries_30d": q_total,
        "error_rate_30d": _r(q_err / q_total, 4) if q_total else None,
    }


def list_audit_events(
    db: Session, *, workspace_id: uuid.UUID | None, action: str | None, page: int, page_size: int
) -> tuple[list[dict[str, Any]], int]:
    where = []
    if workspace_id is not None:
        where.append(AuditEvent.workspace_id == workspace_id)
    if action:
        where.append(AuditEvent.action == action)
    total = db.execute(select(func.count()).select_from(AuditEvent).where(*where)).scalar_one()
    rows = db.execute(
        select(AuditEvent, User.email).outerjoin(User, User.id == AuditEvent.actor_id).where(*where)
        .order_by(AuditEvent.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    items = [
        {
            "id": str(e.id), "action": e.action, "actor_email": email, "workspace_id": str(e.workspace_id) if e.workspace_id else None,
            "target_type": e.target_type, "target_id": e.target_id, "details": e.details, "ip_address": e.ip_address,
            "created_at": e.created_at,
        }
        for e, email in rows
    ]
    return items, total
