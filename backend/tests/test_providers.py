"""Unit tests for the real provider adapters, with the vendor SDK clients replaced by stubs.

No network or paid API calls are made. These verify our request shapes, batching, ordering,
retry classification and error mapping; they cannot prove the vendors accept the requests.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import openai
import pytest
from pinecone import exceptions as pc_exc

from app.core.config import get_settings
from app.core.exceptions import ProviderError
from app.core.retry import call_with_retries
from app.services.embedding_service import OpenAIEmbeddings, classify_openai_error
from app.services.reranking_service import CohereReranker, classify_cohere_error
from app.services.vector_service import (
    PineconeVectorStore,
    VectorRecord,
    classify_pinecone_error,
    vector_id,
)


def _openai_status_error(cls, status: int, body=None):
    req = httpx.Request("POST", "https://api.openai.com/v1/x")
    resp = httpx.Response(status, request=req)
    return cls("boom", response=resp, body=body)


# ------------------------------------------------------------------ retry helper


def test_retry_succeeds_after_transient_errors_and_sleeps_with_backoff():
    attempts, sleeps = [], []

    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise TimeoutError("slow")
        return "ok"

    out = call_with_retries(flaky, provider="x", classify=lambda e: (True, "retry"), max_retries=2, sleep=sleeps.append)
    assert out == "ok" and len(attempts) == 3 and len(sleeps) == 2 and sleeps[1] > 0


def test_retry_stops_immediately_on_non_retryable_and_when_exhausted():
    calls = []

    def always():
        calls.append(1)
        raise ValueError("secret detail sk-abc123")

    with pytest.raises(ProviderError) as e1:
        call_with_retries(always, provider="p", classify=lambda e: (False, "safe message"), sleep=lambda s: None)
    assert len(calls) == 1 and e1.value.message == "safe message" and "sk-abc123" not in e1.value.message
    calls.clear()
    with pytest.raises(ProviderError) as e2:
        call_with_retries(always, provider="p", classify=lambda e: (True, "still failing"), max_retries=2, sleep=lambda s: None)
    assert len(calls) == 3 and e2.value.retryable is True


# ------------------------------------------------------------------ error classification


def test_openai_error_classification():
    assert classify_openai_error(_openai_status_error(openai.RateLimitError, 429, {"code": "rate_limit_exceeded"}))[0] is True
    retry, msg = classify_openai_error(_openai_status_error(openai.RateLimitError, 429, "insufficient_quota"))
    assert retry is False and "quota" in msg
    assert classify_openai_error(_openai_status_error(openai.AuthenticationError, 401))[0] is False
    assert classify_openai_error(_openai_status_error(openai.InternalServerError, 500))[0] is True
    assert classify_openai_error(openai.APITimeoutError(httpx.Request("POST", "https://x")))[0] is True
    assert classify_openai_error(RuntimeError("?")) == (False, "Unexpected error while calling the OpenAI API.")


def test_cohere_and_pinecone_error_classification():
    assert classify_cohere_error(SimpleNamespace(status_code=429))[0] is True
    assert classify_cohere_error(SimpleNamespace(status_code=503))[0] is True
    assert classify_cohere_error(SimpleNamespace(status_code=401))[0] is False
    assert classify_cohere_error(httpx.ReadTimeout("t"))[0] is True
    assert classify_pinecone_error(pc_exc.RateLimitException())[0] is True
    assert classify_pinecone_error(pc_exc.UnauthorizedException())[0] is False
    assert classify_pinecone_error(pc_exc.NotFoundException())[0] is False
    assert classify_pinecone_error(pc_exc.ServiceException())[0] is True


# ------------------------------------------------------------------ OpenAI embeddings


class _FakeOpenAIEmbeddings:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        # Return items in reverse order to prove we sort by `index`.
        data = [SimpleNamespace(index=i, embedding=[float(len(t))] * 4) for i, t in enumerate(kwargs["input"])]
        return SimpleNamespace(data=list(reversed(data)))


def test_openai_embeddings_batching_order_and_dimensions(monkeypatch):
    monkeypatch.setattr(get_settings(), "embedding_batch_size", 2)
    api = _FakeOpenAIEmbeddings()
    emb = OpenAIEmbeddings(client=SimpleNamespace(embeddings=api))
    progress = []
    vectors = emb.embed_texts(["a", "bb", "ccc", "dddd", "eeeee"], on_batch=lambda d, t: progress.append((d, t)))
    assert [v[0] for v in vectors] == [1.0, 2.0, 3.0, 4.0, 5.0]
    assert [len(c["input"]) for c in api.calls] == [2, 2, 1] and progress == [(2, 5), (4, 5), (5, 5)]
    assert api.calls[0]["model"] == "text-embedding-3-small" and api.calls[0]["dimensions"] == get_settings().embedding_dimensions
    assert emb.embed_query("hello")[0] == 5.0


def test_openai_embeddings_retries_rate_limit_then_succeeds(monkeypatch):
    monkeypatch.setattr("app.core.retry.time.sleep", lambda s: None)
    state = {"n": 0}

    class Flaky(_FakeOpenAIEmbeddings):
        def create(self, **kwargs):
            state["n"] += 1
            if state["n"] == 1:
                raise _openai_status_error(openai.RateLimitError, 429, {"code": "rate_limit_exceeded"})
            return super().create(**kwargs)

    emb = OpenAIEmbeddings(client=SimpleNamespace(embeddings=Flaky()))
    assert emb.embed_texts(["x"]) == [[1.0] * 4] and state["n"] == 2


def test_openai_embeddings_requires_api_key():
    with pytest.raises(ProviderError):
        OpenAIEmbeddings()  # no key configured in the test environment


# ------------------------------------------------------------------ Cohere reranker


def test_cohere_reranker_maps_results_and_requests_top_n(monkeypatch):
    monkeypatch.setattr(get_settings(), "cohere_api_key", "test-key")
    rr = CohereReranker()
    seen = {}

    def fake_rerank(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(results=[SimpleNamespace(index=2, relevance_score=0.9), SimpleNamespace(index=0, relevance_score=0.2)])

    rr._client = SimpleNamespace(rerank=fake_rerank)
    out = rr.rerank("q", ["d0", "d1", "d2"], top_n=10)
    assert out == [(2, 0.9), (0, 0.2)]
    assert seen["model"] == get_settings().cohere_rerank_model and seen["top_n"] == 3 and seen["documents"] == ["d0", "d1", "d2"]
    assert rr.rerank("q", [], 5) == []


def test_cohere_reranker_error_becomes_provider_error_without_fallback(monkeypatch):
    monkeypatch.setattr(get_settings(), "cohere_api_key", "test-key")
    rr = CohereReranker()

    def bad(**kwargs):
        raise SimpleNamespaceError(401)

    class SimpleNamespaceError(Exception):
        def __init__(self, status):
            super().__init__("unauthorized key=abc")
            self.status_code = status

    rr._client = SimpleNamespace(rerank=bad)
    with pytest.raises(ProviderError) as exc:
        rr.rerank("q", ["d"], 1)
    assert "invalid" in exc.value.message and "abc" not in exc.value.message and exc.value.retryable is False


# ------------------------------------------------------------------ Pinecone store


class _FakeIndex:
    def __init__(self, pages=None):
        self.upserts, self.deletes, self.queries = [], [], []
        self.pages = pages or []

    def upsert(self, vectors, namespace, show_progress):
        self.upserts.append((namespace, len(vectors)))

    def query(self, **kw):
        self.queries.append(kw)
        m = SimpleNamespace(id="v1", score=0.5, metadata={"chunk_id": "c1"})
        return SimpleNamespace(matches=[m])

    def list_paginated(self, prefix, namespace, limit, pagination_token):
        page = self.pages.pop(0)
        return page

    def delete(self, ids, namespace):
        self.deletes.append((namespace, list(ids)))


def _store(index):
    store = PineconeVectorStore.__new__(PineconeVectorStore)
    store._s, store._pc, store._index = get_settings(), None, index
    import threading

    store._lock = threading.Lock()
    return store


def test_pinecone_upsert_batches_and_uses_namespace():
    idx = _FakeIndex()
    recs = [VectorRecord(id=f"d:{i}", values=[0.1], metadata={}) for i in range(250)]
    _store(idx).upsert("ws-1", recs)
    assert idx.upserts == [("ws-1", 100), ("ws-1", 100), ("ws-1", 50)]


def test_pinecone_query_passes_namespace_filter_and_metadata():
    idx = _FakeIndex()
    out = _store(idx).query("ws-1", [0.1, 0.2], 7, {"workspace_id": {"$eq": "1"}})
    q = idx.queries[0]
    assert q["namespace"] == "ws-1" and q["filter"] == {"workspace_id": {"$eq": "1"}} and q["top_k"] == 7
    assert q["include_metadata"] is True and out[0].metadata["chunk_id"] == "c1" and out[0].score == 0.5


def test_pinecone_delete_document_follows_pagination_by_id_prefix():
    pages = [
        SimpleNamespace(vectors=[SimpleNamespace(id="doc:1:0"), SimpleNamespace(id="doc:1:1")], pagination=SimpleNamespace(next="t2")),
        SimpleNamespace(vectors=[SimpleNamespace(id="doc:1:2")], pagination=None),
    ]
    idx = _FakeIndex(pages)
    assert _store(idx).delete_document("ws-1", "doc") == 3
    assert idx.deletes == [("ws-1", ["doc:1:0", "doc:1:1"]), ("ws-1", ["doc:1:2"])]


def test_vector_ids_are_deterministic():
    assert vector_id("doc", 1, 7) == "doc:1:7" == vector_id("doc", 1, 7)
