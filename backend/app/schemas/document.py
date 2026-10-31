from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    filename: str
    title: str
    file_type: str
    size_bytes: int
    status: str
    error_summary: str | None
    page_count: int | None
    chunk_count: int
    attempts: int
    created_at: datetime
    updated_at: datetime
    indexed_at: datetime | None


class DocumentPage(BaseModel):
    items: list[DocumentOut]
    total: int
    page: int
    page_size: int


class UploadError(BaseModel):
    code: str
    message: str


class UploadResult(BaseModel):
    filename: str
    accepted: bool
    document: DocumentOut | None = None
    error: UploadError | None = None


class UploadResponse(BaseModel):
    results: list[UploadResult]


class ChunkOut(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    page_number: int | None
    chunk_index: int
    text: str
