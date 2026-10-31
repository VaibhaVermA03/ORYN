"""Embedding provider abstraction. The default implementation uses OpenAI."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

import openai
from openai import OpenAI

from app.core.config import get_settings
from app.core.exceptions import ProviderError
from app.core.retry import call_with_retries


class EmbeddingProvider(Protocol):
    model: str
    dimensions: int

    def embed_texts(self, texts: Sequence[str], on_batch: Callable[[int, int], None] | None = None) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def classify_openai_error(exc: Exception) -> tuple[bool, str]:
    if isinstance(exc, openai.RateLimitError):
        # OpenAI uses 429 both for rate limits and for exhausted quota.
        body = str(getattr(exc, "body", "") or "")
        if "insufficient_quota" in body:
            return False, "The OpenAI account has no remaining quota."
        return True, "The OpenAI API is rate limiting requests. Please retry shortly."
    if isinstance(exc, (openai.APITimeoutError, openai.APIConnectionError)):
        return True, "The OpenAI API did not respond in time."
    if isinstance(exc, openai.InternalServerError):
        return True, "The OpenAI API is temporarily unavailable."
    if isinstance(exc, openai.AuthenticationError):
        return False, "The OpenAI API key is invalid or lacks access."
    if isinstance(exc, openai.BadRequestError):
        return False, "The OpenAI API rejected the request."
    if isinstance(exc, openai.APIStatusError):
        return False, f"The OpenAI API returned an error (status {exc.status_code})."
    return False, "Unexpected error while calling the OpenAI API."


class OpenAIEmbeddings:
    def __init__(self, client: OpenAI | None = None) -> None:
        s = get_settings()
        if client is None:
            if not s.openai_api_key:
                raise ProviderError("openai", "OPENAI_API_KEY is not configured")
            # SDK-level retries are disabled; retries are handled (and logged) by call_with_retries.
            client = OpenAI(api_key=s.openai_api_key, timeout=s.openai_timeout_seconds, max_retries=0)
        self._client = client
        self.model = s.openai_embedding_model
        self.dimensions = s.embedding_dimensions
        self._batch = s.embedding_batch_size
        self._retries = s.openai_max_retries

    def _embed_batch(self, batch: Sequence[str]) -> list[list[float]]:
        def call() -> list[list[float]]:
            kwargs: dict = {"model": self.model, "input": list(batch)}
            if self.model.startswith("text-embedding-3"):
                kwargs["dimensions"] = self.dimensions
            resp = self._client.embeddings.create(**kwargs)
            ordered = sorted(resp.data, key=lambda d: d.index)
            vectors = [d.embedding for d in ordered]
            if len(vectors) != len(batch):
                raise ProviderError("openai", "Embedding response had an unexpected length")
            return vectors

        return call_with_retries(call, provider="openai", classify=classify_openai_error, max_retries=self._retries)

    def embed_texts(self, texts: Sequence[str], on_batch: Callable[[int, int], None] | None = None) -> list[list[float]]:
        out: list[list[float]] = []
        total = len(texts)
        for start in range(0, total, self._batch):
            out.extend(self._embed_batch(texts[start : start + self._batch]))
            if on_batch:
                on_batch(min(start + self._batch, total), total)
        return out

    def embed_query(self, text: str) -> list[float]:
        return self._embed_batch([text])[0]


# ------------------------------------------------------------------ provider registry
_embedder: EmbeddingProvider | None = None


def get_embedder() -> EmbeddingProvider:
    global _embedder
    if _embedder is None:
        _embedder = OpenAIEmbeddings()
    return _embedder


def set_embedder(embedder: EmbeddingProvider | None) -> None:
    """Override the provider (used by tests; production code never calls this)."""
    global _embedder
    _embedder = embedder
