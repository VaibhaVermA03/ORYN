from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.exceptions import AppError, ProviderError
from app.core.rate_limit import client_ip, limiter
from app.db.models import User
from app.db.session import get_db
from app.schemas.document import ChunkOut, DocumentOut, DocumentPage, UploadError, UploadResponse, UploadResult
from app.services import document_service as docs
from app.services import workspace_service as ws_svc
from app.workers.ingestion_worker import wake_worker

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["documents"])


@router.post("/documents", response_model=UploadResponse)
def upload_documents(
    workspace_id: uuid.UUID,
    request: Request,
    files: list[UploadFile] = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload one or more files. Each file is validated independently and reported in `results`;
    the HTTP status is 200 even when some files are rejected. A request with more than
    MAX_FILES_PER_REQUEST files is rejected as a whole."""
    s = get_settings()
    ws_svc.require_member(db, workspace_id, user)
    limiter.hit(f"upload:{user.id}", s.rate_limit_upload_per_minute)
    if len(files) > s.max_files_per_request:
        raise AppError(f"At most {s.max_files_per_request} files can be uploaded at once.",
                       code="too_many_files", status_code=422)
    ip = client_ip(request)
    results: list[UploadResult] = []
    accepted = False
    for f in files:
        try:
            doc = docs.save_upload(db, workspace_id=workspace_id, user=user, filename=f.filename or "document",
                                   stream=f.file, ip=ip)
            db.commit()
            accepted = True
            results.append(UploadResult(filename=doc.filename, accepted=True, document=DocumentOut.model_validate(doc)))
        except AppError as exc:
            db.rollback()
            results.append(UploadResult(filename=f.filename or "document", accepted=False,
                                        error=UploadError(code=exc.code, message=exc.message)))
    if accepted:
        wake_worker()
    return UploadResponse(results=results)


@router.get("/documents", response_model=DocumentPage)
def list_documents(
    workspace_id: uuid.UUID,
    q: str | None = Query(default=None, max_length=200),
    status: str | None = Query(default=None, max_length=20),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ws_svc.require_member(db, workspace_id, user)
    items, total = docs.list_documents(db, workspace_id, q=q, status=status, page=page, page_size=page_size)
    return DocumentPage(items=[DocumentOut.model_validate(d) for d in items], total=total, page=page, page_size=page_size)


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(
    workspace_id: uuid.UUID, document_id: uuid.UUID,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Processing status endpoint: poll this (or the list) to follow ingestion progress."""
    ws_svc.require_member(db, workspace_id, user)
    return DocumentOut.model_validate(docs.get_document(db, workspace_id, document_id))


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(
    workspace_id: uuid.UUID, document_id: uuid.UUID, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    ws_svc.require_member(db, workspace_id, user)  # any member may manage documents in their workspace
    docs.delete_document(db, workspace_id=workspace_id, document_id=document_id, actor=user, ip=client_ip(request))
    db.commit()


@router.post("/documents/{document_id}/reindex", response_model=DocumentOut, status_code=202)
def reindex_document(
    workspace_id: uuid.UUID, document_id: uuid.UUID, request: Request,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    ws_svc.require_member(db, workspace_id, user)
    doc = docs.request_reindex(db, workspace_id=workspace_id, document_id=document_id, actor=user, ip=client_ip(request))
    db.commit()
    wake_worker()
    return DocumentOut.model_validate(doc)


@router.get("/chunks/{chunk_id}", response_model=ChunkOut)
def get_chunk(
    workspace_id: uuid.UUID, chunk_id: uuid.UUID,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Authorized source preview used by the citation drawer."""
    ws_svc.require_member(db, workspace_id, user)
    chunk, doc = docs.get_chunk(db, workspace_id, chunk_id)
    return ChunkOut(chunk_id=chunk.id, document_id=doc.id, filename=doc.filename,
                    page_number=chunk.page_number, chunk_index=chunk.chunk_index, text=chunk.text)


__all__ = ["router", "ProviderError"]
