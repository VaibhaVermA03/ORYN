from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.exceptions import AppError, Conflict, NotFound, ProviderError
from app.core.rate_limit import client_ip, limiter
from app.db.models import EvaluationRun, User
from app.db.session import get_db
from app.schemas.evaluation import EvalResultOut, EvalRunDetail, EvalRunOut, EvalRunRequest
from app.services import evaluation_service as ev
from app.services import workspace_service as ws_svc
from app.services.audit_service import record_audit
from app.services.embedding_service import get_embedder
from app.services.llm_service import get_llm
from app.services.reranking_service import get_reranker
from app.services.vector_service import get_vector_store

router = APIRouter(prefix="/workspaces/{workspace_id}/evaluations", tags=["evaluation"])


@router.post("", response_model=EvalRunOut, status_code=202)
def start_evaluation(
    workspace_id: uuid.UUID,
    body: EvalRunRequest,
    request: Request,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start an evaluation run on the supplied dataset. Poll GET /evaluations/{id} for progress.

    Runs execute in a background thread of the API process; see docs/EVALUATION.md. Requires a
    workspace owner or admin because the run issues real (billable) provider calls.
    """
    s = get_settings()
    ws_svc.require_workspace_admin(db, workspace_id, user)
    if len(body.dataset.samples) > s.eval_max_samples:
        raise AppError(f"A dataset may contain at most {s.eval_max_samples} samples.", code="dataset_too_large", status_code=422)
    limiter.hit(f"eval:{user.id}", 5)
    ev.fail_stale_runs(db, workspace_id)
    running = db.execute(
        select(func.count()).select_from(EvaluationRun).where(
            EvaluationRun.workspace_id == workspace_id, EvaluationRun.status == "running"
        )
    ).scalar_one()
    if running:
        raise Conflict("An evaluation is already running for this workspace.", code="evaluation_running")
    try:
        get_embedder(), get_vector_store(), get_reranker(), get_llm()
    except ProviderError as exc:
        raise AppError(exc.message, code="provider_not_configured", status_code=503) from exc

    run = ev.create_run(
        db, workspace_id=workspace_id, created_by=user.id, name=body.dataset.name,
        samples=[x.model_dump() for x in body.dataset.samples], judge=body.judge,
    )
    record_audit(db, action="evaluation.start", actor_id=user.id, workspace_id=workspace_id, target_type="evaluation",
                 target_id=run.id, details={"samples": len(body.dataset.samples), "judge": body.judge},
                 ip_address=client_ip(request))
    db.commit()
    background.add_task(ev.run_evaluation, run.id)
    return EvalRunOut.model_validate(run)


@router.get("", response_model=list[EvalRunOut])
def list_runs(workspace_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ws_svc.require_workspace_admin(db, workspace_id, user)
    ev.fail_stale_runs(db, workspace_id)
    db.commit()
    runs = db.execute(
        select(EvaluationRun).where(EvaluationRun.workspace_id == workspace_id)
        .order_by(EvaluationRun.created_at.desc()).limit(50)
    ).scalars().all()
    return [EvalRunOut.model_validate(r) for r in runs]


@router.get("/{run_id}", response_model=EvalRunDetail)
def get_run(workspace_id: uuid.UUID, run_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ws_svc.require_workspace_admin(db, workspace_id, user)
    run = db.execute(
        select(EvaluationRun).where(EvaluationRun.id == run_id, EvaluationRun.workspace_id == workspace_id)
    ).scalar_one_or_none()
    if run is None:
        raise NotFound("Evaluation run not found")
    base = EvalRunOut.model_validate(run).model_dump()
    return EvalRunDetail(**base, results=[EvalResultOut.model_validate(r) for r in run.results])
