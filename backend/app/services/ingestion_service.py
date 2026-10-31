"""Document ingestion pipeline: extract -> chunk -> embed -> index -> ready.

Every status transition is committed to PostgreSQL, so a browser refresh (or a process
restart) never loses progress. The pipeline is idempotent: chunk rows are replaced, vector IDs
are deterministic, and stale vectors for the document are removed before upserting.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.exceptions import AppError, ProviderError
from app.db.base import utcnow
from app.db.models import Chunk, Document, DocumentStatus
from app.db.session import session_scope
from app.services.chunking_service import chunk_pages
from app.services.embedding_service import get_embedder
from app.services.extraction_service import ExtractionError, extract_pages, page_count
from app.services.storage_service import get_storage
from app.services.vector_service import VectorRecord, get_vector_store, vector_id

logger = logging.getLogger("oryn.ingestion")


def _set(document_id: uuid.UUID, status: DocumentStatus, **fields) -> None:
    """Commit a status transition and refresh the heartbeat used for stale-lock recovery."""
    with session_scope() as db:
        doc = db.get(Document, document_id)
        if doc is None:
            raise LookupError("document disappeared")
        doc.status = status
        doc.locked_at = utcnow()
        for key, value in fields.items():
            setattr(doc, key, value)


def _heartbeat(document_id: uuid.UUID) -> None:
    with session_scope() as db:
        doc = db.get(Document, document_id)
        if doc is not None:
            doc.locked_at = utcnow()


def _safe_message(exc: Exception) -> str:
    if isinstance(exc, AppError):
        return exc.message[:500]
    return "An unexpected error occurred while processing the document."


def _cleanup_partial(document_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
    """Best effort: remove vectors and chunk rows left behind by a failed attempt."""
    try:
        get_vector_store().delete_document(get_settings().namespace_for(str(workspace_id)), str(document_id))
    except Exception:  # noqa: BLE001
        logger.warning("partial_vector_cleanup_failed", extra={"document_id": str(document_id)})
    with session_scope() as db:
        db.execute(delete(Chunk).where(Chunk.document_id == document_id))


def process_document(document_id: uuid.UUID) -> str:
    """Run the pipeline for a claimed document. Returns the final status value."""
    s = get_settings()
    with session_scope() as db:
        doc = db.get(Document, document_id)
        if doc is None:
            return "missing"
        workspace_id, storage_key, file_type = doc.workspace_id, doc.storage_key, doc.file_type
        title, filename, attempts = doc.title, doc.filename, doc.attempts

    namespace = s.namespace_for(str(workspace_id))
    try:
        _set(document_id, DocumentStatus.extracting, error_summary=None)
        with get_storage().open_local(storage_key) as path:
            pages = extract_pages(path, file_type)

        _set(document_id, DocumentStatus.chunking, page_count=page_count(pages))
        chunks = chunk_pages(pages, s.chunk_size_chars, s.chunk_overlap_chars)
        if not chunks:
            raise ExtractionError("No extractable text was found in the file.", code="no_text")
        version = s.ingestion_version
        chunk_ids = [uuid.uuid4() for _ in chunks]
        with session_scope() as db:
            db.execute(delete(Chunk).where(Chunk.document_id == document_id))
            db.flush()
            db.add_all(
                Chunk(
                    id=chunk_ids[i], document_id=document_id, workspace_id=workspace_id, chunk_index=c.index,
                    page_number=c.page_number, text=c.text, token_count=max(1, len(c.text) // 4),
                    content_hash=c.content_hash, ingestion_version=version,
                    vector_id=vector_id(document_id, version, c.index),
                )
                for i, c in enumerate(chunks)
            )

        _set(document_id, DocumentStatus.embedding)
        vectors = get_embedder().embed_texts(
            [c.text for c in chunks], on_batch=lambda done, total: _heartbeat(document_id)
        )

        _set(document_id, DocumentStatus.indexing)
        store = get_vector_store()
        store.delete_document(namespace, str(document_id))  # drop stale vectors from earlier versions
        store.upsert(
            namespace,
            [
                VectorRecord(
                    id=vector_id(document_id, version, c.index),
                    values=vectors[i],
                    metadata={
                        "workspace_id": str(workspace_id),
                        "document_id": str(document_id),
                        "chunk_id": str(chunk_ids[i]),
                        "filename": filename,
                        "document_title": title,
                        "chunk_index": c.index,
                        "page_number": c.page_number if c.page_number is not None else -1,
                        "content_hash": c.content_hash,
                        "ingestion_version": version,
                    },
                )
                for i, c in enumerate(chunks)
            ],
        )

        _set(
            document_id, DocumentStatus.ready, chunk_count=len(chunks), ingestion_version=version,
            indexed_at=utcnow(), error_summary=None, locked_at=None,
        )
        logger.info("document_ready", extra={"document_id": str(document_id), "chunks": len(chunks)})
        return DocumentStatus.ready.value

    except Exception as exc:  # noqa: BLE001 - every failure must be recorded, never swallowed
        retryable = isinstance(exc, ProviderError) and exc.retryable
        logger.warning(
            "ingestion_failed",
            extra={"document_id": str(document_id), "exc_type": type(exc).__name__, "retryable": retryable},
        )
        _cleanup_partial(document_id, workspace_id)
        message = _safe_message(exc)
        with session_scope() as db:
            doc = db.get(Document, document_id)
            if doc is None:
                return "missing"
            if retryable and attempts < s.ingestion_max_attempts:
                backoff = 15 * (2 ** (attempts - 1))
                doc.status = DocumentStatus.uploaded
                doc.locked_at = utcnow() + timedelta(seconds=backoff)  # "not before" time for the claim query
                doc.error_summary = f"Temporary error, retrying automatically: {message}"[:500]
                return "retry"
            doc.status = DocumentStatus.failed
            doc.locked_at = None
            doc.chunk_count = 0
            doc.error_summary = message
            return DocumentStatus.failed.value


def claim_next_document() -> uuid.UUID | None:
    """Atomically claim the oldest runnable document (safe across multiple workers)."""
    with session_scope() as db:
        now = utcnow()
        doc = db.execute(
            select(Document)
            .where(
                Document.status == DocumentStatus.uploaded,
                (Document.locked_at.is_(None)) | (Document.locked_at <= now),
            )
            .order_by(Document.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).scalar_one_or_none()
        if doc is None:
            return None
        doc.status = DocumentStatus.extracting
        doc.locked_at = now
        doc.attempts += 1
        return doc.id


def recover_stale_documents() -> int:
    """Re-queue (or fail) documents whose worker died mid-pipeline."""
    s = get_settings()
    cutoff = utcnow() - timedelta(seconds=s.ingestion_stale_lock_seconds)
    recovered = 0
    with session_scope() as db:
        stale = db.execute(
            select(Document).where(
                Document.status.in_(
                    [DocumentStatus.extracting, DocumentStatus.chunking, DocumentStatus.embedding, DocumentStatus.indexing]
                ),
                Document.locked_at < cutoff,
            ).with_for_update(skip_locked=True)
        ).scalars().all()
        for doc in stale:
            if doc.attempts >= s.ingestion_max_attempts:
                doc.status = DocumentStatus.failed
                doc.error_summary = "Processing timed out repeatedly."
                doc.locked_at = None
            else:
                doc.status = DocumentStatus.uploaded
                doc.locked_at = None
            recovered += 1
    return recovered
