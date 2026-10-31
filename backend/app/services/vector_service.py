"""Vector store abstraction. The default implementation uses Pinecone.

Tenant isolation: every workspace has its own Pinecone namespace (`ws-<workspace_id>`), and
every query additionally filters on `workspace_id` metadata. Vector IDs are deterministic:
`<document_id>:<ingestion_version>:<chunk_index>`.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any, Protocol

from pinecone import Pinecone, ServerlessSpec
from pinecone import exceptions as pc_exc

from app.core.config import get_settings
from app.core.exceptions import ProviderError
from app.core.retry import call_with_retries

logger = logging.getLogger("oryn.vector")

def _retry(fn: Callable[[], Any]) -> Any:
    return call_with_retries(fn, provider="pinecone", classify=classify_pinecone_error, max_retries=2)


UPSERT_BATCH = 100
DELETE_BATCH = 100


@dataclass(frozen=True)
class VectorRecord:
    id: str
    values: list[float]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class VectorMatch:
    id: str
    score: float
    metadata: dict[str, Any]


def vector_id(document_id: Any, ingestion_version: int, chunk_index: int) -> str:
    return f"{document_id}:{ingestion_version}:{chunk_index}"


class VectorStore(Protocol):
    def upsert(self, namespace: str, records: Sequence[VectorRecord]) -> None: ...

    def query(self, namespace: str, vector: Sequence[float], top_k: int, filter: dict[str, Any]) -> list[VectorMatch]: ...

    def delete_document(self, namespace: str, document_id: str) -> int: ...

    def delete_namespace(self, namespace: str) -> None: ...

    def check_ready(self) -> None: ...


def classify_pinecone_error(exc: Exception) -> tuple[bool, str]:
    if isinstance(exc, pc_exc.RateLimitException):
        return True, "The vector database is rate limiting requests."
    if isinstance(exc, pc_exc.ServiceException):
        return True, "The vector database is temporarily unavailable."
    if isinstance(exc, (pc_exc.UnauthorizedException, pc_exc.ForbiddenException)):
        return False, "The Pinecone API key is invalid or lacks access."
    if isinstance(exc, pc_exc.NotFoundException):
        return False, "The Pinecone index or namespace was not found."
    if isinstance(exc, (pc_exc.PineconeApiException, pc_exc.PineconeException)):
        return False, "The vector database rejected the request."
    # Network-level failures (timeouts, resets) surface as generic exceptions from the HTTP stack.
    name = type(exc).__name__.lower()
    if "timeout" in name or "connection" in name:
        return True, "The vector database did not respond in time."
    return False, "Unexpected error while calling the vector database."


class PineconeVectorStore:
    def __init__(self) -> None:
        s = get_settings()
        if not s.pinecone_api_key:
            raise ProviderError("pinecone", "PINECONE_API_KEY is not configured")
        self._s = s
        self._pc = Pinecone(api_key=s.pinecone_api_key)
        self._index: Any = None
        self._lock = threading.Lock()

    # -- index lifecycle ---------------------------------------------------
    def _get_index(self) -> Any:
        if self._index is not None:
            return self._index
        with self._lock:
            if self._index is None:
                self._index = self._connect()
        return self._index

    def _connect(self) -> Any:
        s = self._s

        def call() -> Any:
            if not self._pc.has_index(s.pinecone_index_name):
                if not s.pinecone_auto_create_index:
                    raise ProviderError(
                        "pinecone", f"Pinecone index '{s.pinecone_index_name}' does not exist", retryable=False
                    )
                logger.info("pinecone_creating_index", extra={"index": s.pinecone_index_name})
                self._pc.create_index(
                    name=s.pinecone_index_name,
                    dimension=s.embedding_dimensions,
                    metric="cosine",
                    spec=ServerlessSpec(cloud=s.pinecone_cloud, region=s.pinecone_region),
                )
            desc = self._pc.describe_index(s.pinecone_index_name)
            deadline = time.monotonic() + 90
            while not getattr(desc.status, "ready", True) and time.monotonic() < deadline:
                time.sleep(2)
                desc = self._pc.describe_index(s.pinecone_index_name)
            if desc.dimension is None or int(desc.dimension) != s.embedding_dimensions:
                raise ProviderError(
                    "pinecone",
                    f"Pinecone index dimension ({desc.dimension}) does not match EMBEDDING_DIMENSIONS "
                    f"({s.embedding_dimensions}). Use a matching index or change the setting.",
                )
            return self._pc.Index(host=desc.host or "")

        return _retry(call)

    def check_ready(self) -> None:
        self._get_index()

    # -- operations ---------------------------------------------------------
    def upsert(self, namespace: str, records: Sequence[VectorRecord]) -> None:
        index = self._get_index()
        for start in range(0, len(records), UPSERT_BATCH):
            batch = records[start : start + UPSERT_BATCH]
            payload = [{"id": r.id, "values": r.values, "metadata": r.metadata} for r in batch]
            _retry(partial(index.upsert, vectors=payload, namespace=namespace, show_progress=False))

    def query(self, namespace: str, vector: Sequence[float], top_k: int, filter: dict[str, Any]) -> list[VectorMatch]:
        index = self._get_index()
        resp = _retry(
            partial(
                index.query, vector=list(vector), top_k=top_k, namespace=namespace, filter=filter,
                include_metadata=True, timeout=self._s.pinecone_timeout_seconds,
            )
        )
        return [VectorMatch(id=m.id, score=float(m.score), metadata=dict(m.metadata or {})) for m in resp.matches]

    def delete_document(self, namespace: str, document_id: str) -> int:
        """Delete every vector whose ID starts with `<document_id>:` (all ingestion versions).

        Listing by ID prefix also removes vectors from partially failed ingestions that have no
        corresponding chunk rows. Returns the number of vectors deleted.
        """
        index = self._get_index()
        prefix = f"{document_id}:"
        deleted = 0
        token: str | None = None
        while True:
            page = _retry(
                partial(index.list_paginated, prefix=prefix, namespace=namespace, limit=DELETE_BATCH,
                        pagination_token=token)
            )
            ids = [v.id for v in (page.vectors or [])]
            if ids:
                _retry(partial(index.delete, ids=ids, namespace=namespace))
                deleted += len(ids)
            pagination = getattr(page, "pagination", None)
            token = getattr(pagination, "next", None) if pagination else None
            if not token:
                break
        return deleted

    def delete_namespace(self, namespace: str) -> None:
        index = self._get_index()
        try:
            _retry(partial(index.delete_namespace, namespace=namespace))
        except ProviderError as exc:
            # A namespace that never received vectors does not exist; that is a successful delete.
            if isinstance(exc.__cause__, pc_exc.NotFoundException):
                return
            raise


# ------------------------------------------------------------------ provider registry
_store: VectorStore | None = None
_store_lock = threading.Lock()


def get_vector_store() -> VectorStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = PineconeVectorStore()
    return _store


def set_vector_store(store: VectorStore | None) -> None:
    """Override the provider (used by tests; production code never calls this)."""
    global _store
    _store = store
