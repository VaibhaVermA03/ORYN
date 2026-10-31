"""Upload validation, document queries, deletion and re-indexing. All queries are workspace-scoped."""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppError, Conflict, NotFound, PayloadTooLarge
from app.db.base import utcnow
from app.db.models import PROCESSING_STATUSES, Chunk, Document, DocumentStatus, User
from app.services.audit_service import record_audit
from app.services.extraction_service import sniff_file_type
from app.services.storage_service import get_storage, sanitize_filename
from app.services.vector_service import get_vector_store

logger = logging.getLogger("oryn.documents")


def save_upload(
    db: Session, *, workspace_id: uuid.UUID, user: User, filename: str, stream: BinaryIO, ip: str | None
) -> Document:
    """Validate and store one uploaded file, then queue it for ingestion.

    Raises AppError subclasses with actionable messages; the caller reports them per file.
    """
    s = get_settings()
    safe_name = sanitize_filename(filename)
    ext = safe_name.rpartition(".")[2].lower() if "." in safe_name else ""
    doc_id = uuid.uuid4()
    storage = get_storage()
    key = f"{workspace_id}/{doc_id}.{ext or 'bin'}"

    try:
        size, digest = storage.save(key, stream, s.max_upload_bytes)
        if size == 0:
            raise AppError("The file is empty.", code="empty_file", status_code=422)
        with storage.open_local(key) as path:
            file_type = sniff_file_type(Path(path), ext)

        existing = db.execute(
            select(Document).where(Document.workspace_id == workspace_id, Document.content_hash == digest)
        ).scalar_one_or_none()
        if existing is not None:
            raise Conflict(
                f"This file was already uploaded as '{existing.filename}'.", code="duplicate_document"
            )

        doc = Document(
            id=doc_id, workspace_id=workspace_id, uploaded_by=user.id, filename=safe_name,
            title=safe_name.rpartition(".")[0] or safe_name, storage_key=key, file_type=file_type,
            size_bytes=size, content_hash=digest, status=DocumentStatus.uploaded,
            ingestion_version=s.ingestion_version,
        )
        db.add(doc)
        record_audit(db, action="document.upload", actor_id=user.id, workspace_id=workspace_id,
                     target_type="document", target_id=doc_id, details={"filename": safe_name, "size": size},
                     ip_address=ip)
        try:
            db.flush()
        except IntegrityError as exc:  # concurrent duplicate upload
            db.rollback()
            raise Conflict("This file was already uploaded.", code="duplicate_document") from exc
        return doc
    except Exception:
        storage.delete(key)  # never leave orphaned files behind a rejected upload
        raise


def get_document(db: Session, workspace_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    doc = db.execute(
        select(Document).where(Document.id == document_id, Document.workspace_id == workspace_id)
    ).scalar_one_or_none()
    if doc is None:
        raise NotFound("Document not found")
    return doc


def list_documents(
    db: Session, workspace_id: uuid.UUID, *, q: str | None, status: str | None, page: int, page_size: int
) -> tuple[list[Document], int]:
    stmt = select(Document).where(Document.workspace_id == workspace_id)
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(Document.filename.ilike(f"%{escaped}%", escape="\\"))
    if status:
        try:
            stmt = stmt.where(Document.status == DocumentStatus(status))
        except ValueError as exc:
            raise AppError("Unknown status filter", code="invalid_filter", status_code=422) from exc
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    items = db.execute(
        stmt.order_by(Document.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()
    return list(items), total


def _is_actively_processing(doc: Document) -> bool:
    if doc.status not in PROCESSING_STATUSES:
        return False
    if doc.status == DocumentStatus.uploaded:
        return False  # queued, not yet claimed
    stale = timedelta(seconds=get_settings().ingestion_stale_lock_seconds)
    return doc.locked_at is not None and utcnow() - doc.locked_at < stale


def delete_document(db: Session, *, workspace_id: uuid.UUID, document_id: uuid.UUID, actor: User, ip: str | None) -> None:
    """Remove vectors first, then the database rows and file. A vector failure aborts the delete
    so no orphaned vectors can outlive their document record."""
    doc = db.execute(
        select(Document).where(Document.id == document_id, Document.workspace_id == workspace_id).with_for_update()
    ).scalar_one_or_none()
    if doc is None:
        raise NotFound("Document not found")
    if _is_actively_processing(doc):
        raise Conflict("The document is being processed. Try again in a moment.", code="document_busy")
    namespace = get_settings().namespace_for(str(workspace_id))
    get_vector_store().delete_document(namespace, str(doc.id))  # raises ProviderError on failure
    storage_key = doc.storage_key
    record_audit(db, action="document.delete", actor_id=actor.id, workspace_id=workspace_id,
                 target_type="document", target_id=doc.id, details={"filename": doc.filename}, ip_address=ip)
    db.delete(doc)
    db.flush()
    get_storage().delete(storage_key)


def request_reindex(db: Session, *, workspace_id: uuid.UUID, document_id: uuid.UUID, actor: User, ip: str | None) -> Document:
    doc = db.execute(
        select(Document).where(Document.id == document_id, Document.workspace_id == workspace_id).with_for_update()
    ).scalar_one_or_none()
    if doc is None:
        raise NotFound("Document not found")
    if _is_actively_processing(doc) or doc.status == DocumentStatus.uploaded:
        raise Conflict("The document is already being processed.", code="document_busy")
    doc.status = DocumentStatus.uploaded
    doc.attempts = 0
    doc.locked_at = None
    doc.error_summary = None
    record_audit(db, action="document.reindex", actor_id=actor.id, workspace_id=workspace_id,
                 target_type="document", target_id=doc.id, ip_address=ip)
    return doc


def get_chunk(db: Session, workspace_id: uuid.UUID, chunk_id: uuid.UUID) -> tuple[Chunk, Document]:
    """Source preview lookup. The workspace filter is part of the query, so a chunk ID from
    another workspace is indistinguishable from a missing one."""
    row = db.execute(
        select(Chunk, Document)
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.id == chunk_id, Chunk.workspace_id == workspace_id, Document.workspace_id == workspace_id)
    ).first()
    if row is None:
        raise NotFound("Source not found")
    return row[0], row[1]


def delete_workspace_data(db: Session, workspace_id: uuid.UUID) -> None:
    """Remove a workspace's vectors (whole namespace) and stored files. DB rows cascade."""
    get_vector_store().delete_namespace(get_settings().namespace_for(str(workspace_id)))
    get_storage().delete_prefix(str(workspace_id))


__all__ = ["PayloadTooLarge"]
