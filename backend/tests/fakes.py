"""In-memory provider fakes used ONLY by tests. They live outside `app/` so they can never be
selected in a running deployment."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable, Sequence
from typing import Any

from app.core.exceptions import ProviderError
from app.services.vector_service import VectorMatch, VectorRecord

DIM = 64
_TOKEN = re.compile(r"[a-z0-9]+")


def _vec(text: str) -> list[float]:
    """Hashed bag-of-words vector: texts sharing words are close, so dense search is meaningful."""
    v = [0.0] * DIM
    for tok in _TOKEN.findall(text.lower()):
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        v[h % DIM] += 1.0
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


class FakeEmbedder:
    model = "fake-embedding"
    dimensions = DIM

    def __init__(self) -> None:
        self.calls = 0
        self.fail_with: ProviderError | None = None
        self.fail_times = 0

    def embed_texts(self, texts: Sequence[str], on_batch: Callable[[int, int], None] | None = None) -> list[list[float]]:
        self.calls += 1
        if self.fail_with is not None and (self.fail_times == 0 or self.calls <= self.fail_times):
            raise self.fail_with
        out = [_vec(t) for t in texts]
        if on_batch:
            on_batch(len(texts), len(texts))
        return out

    def embed_query(self, text: str) -> list[float]:
        if self.fail_with is not None:
            raise self.fail_with
        return _vec(text)


class FakeVectorStore:
    def __init__(self) -> None:
        self.namespaces: dict[str, dict[str, VectorRecord]] = {}
        self.fail_delete: ProviderError | None = None
        self.fail_upsert: ProviderError | None = None
        self.fail_query: ProviderError | None = None
        self.queries: list[dict[str, Any]] = []

    def upsert(self, namespace: str, records: Sequence[VectorRecord]) -> None:
        if self.fail_upsert:
            raise self.fail_upsert
        ns = self.namespaces.setdefault(namespace, {})
        for r in records:
            ns[r.id] = r

    def query(self, namespace: str, vector: Sequence[float], top_k: int, filter: dict[str, Any]) -> list[VectorMatch]:
        self.queries.append({"namespace": namespace, "filter": filter, "top_k": top_k})
        if self.fail_query:
            raise self.fail_query
        scored = []
        for r in self.namespaces.get(namespace, {}).values():
            if any(r.metadata.get(k) != (v.get("$eq") if isinstance(v, dict) else v) for k, v in filter.items()):
                continue
            score = sum(a * b for a, b in zip(vector, r.values, strict=False))
            scored.append(VectorMatch(id=r.id, score=score, metadata=dict(r.metadata)))
        scored.sort(key=lambda m: m.score, reverse=True)
        return scored[:top_k]

    def delete_document(self, namespace: str, document_id: str) -> int:
        if self.fail_delete:
            raise self.fail_delete
        ns = self.namespaces.get(namespace, {})
        ids = [i for i in ns if i.startswith(f"{document_id}:")]
        for i in ids:
            del ns[i]
        return len(ids)

    def delete_namespace(self, namespace: str) -> None:
        if self.fail_delete:
            raise self.fail_delete
        self.namespaces.pop(namespace, None)

    def check_ready(self) -> None:
        return None

    def count(self, namespace: str) -> int:
        return len(self.namespaces.get(namespace, {}))


class FakeReranker:
    """Scores a document by the fraction of (non-trivial) query words it contains."""

    model = "fake-rerank"
    _STOP = {"the", "a", "an", "is", "are", "what", "how", "do", "does", "of", "to", "in", "for", "and", "our"}

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.fail_with: ProviderError | None = None

    def rerank(self, query: str, documents: Sequence[str], top_n: int) -> list[tuple[int, float]]:
        self.calls.append({"query": query, "documents": list(documents), "top_n": top_n})
        if self.fail_with is not None:
            raise self.fail_with
        q = {w for w in _TOKEN.findall(query.lower()) if w not in self._STOP}
        scored = []
        for i, d in enumerate(documents):
            words = set(_TOKEN.findall(d.lower()))
            scored.append((i, len(q & words) / (len(q) or 1)))
        scored.sort(key=lambda x: -x[1])
        return scored[:top_n]


class FakeLLM:
    model = "fake-llm"

    def __init__(self) -> None:
        self.calls: list[list[dict]] = []
        self.tokens = ["The ", "answer ", "is ", "in ", "the ", "docs ", "[1]."]
        self.fail_after: int | None = None
        self.fail_with: ProviderError | None = None
        self.delay = 0.0

    async def stream(self, messages):
        import asyncio

        self.calls.append(list(messages))
        for i, tok in enumerate(self.tokens):
            if self.fail_after is not None and i >= self.fail_after:
                raise self.fail_with or ProviderError("openai", "The OpenAI API did not respond in time.", retryable=True)
            if self.delay:
                await asyncio.sleep(self.delay)
            yield tok


class FakeJudge:
    model = "fake-judge"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.faithfulness = {"total_claims": 4, "supported_claims": 2}
        self.relevance = {"score": 4}
        self.correctness = {"score": 5}

    def judge(self, system: str, user: str) -> dict:
        self.calls.append((system, user))
        if "supported by the CONTEXT" in system:
            return dict(self.faithfulness)
        if "REFERENCE" in system:
            return dict(self.correctness)
        return dict(self.relevance)
