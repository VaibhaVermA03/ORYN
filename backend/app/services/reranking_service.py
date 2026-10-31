"""Second-stage relevance ranking. The default implementation calls the Cohere Rerank API.

There is deliberately NO silent fallback: if Cohere fails, the error propagates so the caller can
report it accurately instead of returning an unranked (and possibly misleading) result.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from typing import Protocol

import cohere
import httpx

from app.core.config import get_settings
from app.core.exceptions import ProviderError
from app.core.retry import call_with_retries


class Reranker(Protocol):
    model: str

    def rerank(self, query: str, documents: Sequence[str], top_n: int) -> list[tuple[int, float]]:
        """Return (document_index, relevance_score) pairs, best first, at most `top_n`."""
        ...


def classify_cohere_error(exc: Exception) -> tuple[bool, str]:
    status = getattr(exc, "status_code", None)
    if status == 429:
        return True, "The reranking service is rate limiting requests."
    if isinstance(status, int) and status >= 500:
        return True, "The reranking service is temporarily unavailable."
    if status in (401, 403):
        return False, "The Cohere API key is invalid or lacks access."
    if isinstance(status, int):
        return False, f"The reranking service rejected the request (status {status})."
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True, "The reranking service did not respond in time."
    return False, "Unexpected error while calling the reranking service."


class CohereReranker:
    def __init__(self) -> None:
        s = get_settings()
        if not s.cohere_api_key:
            raise ProviderError("cohere", "COHERE_API_KEY is not configured")
        self.model = s.cohere_rerank_model
        self._client = cohere.ClientV2(api_key=s.cohere_api_key, timeout=s.cohere_timeout_seconds)

    def rerank(self, query: str, documents: Sequence[str], top_n: int) -> list[tuple[int, float]]:
        if not documents:
            return []
        top_n = max(1, min(top_n, len(documents)))
        resp = call_with_retries(
            lambda: self._client.rerank(model=self.model, query=query, documents=list(documents), top_n=top_n),
            provider="cohere", classify=classify_cohere_error, max_retries=get_settings().openai_max_retries,
        )
        return [(r.index, float(r.relevance_score)) for r in resp.results]


_reranker: Reranker | None = None
_lock = threading.Lock()


def get_reranker() -> Reranker:
    global _reranker
    if _reranker is None:
        with _lock:
            if _reranker is None:
                _reranker = CohereReranker()
    return _reranker


def set_reranker(reranker: Reranker | None) -> None:
    """Override the provider (used by tests; production code never calls this)."""
    global _reranker
    _reranker = reranker
