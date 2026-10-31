"""Hybrid retrieval: dense (Pinecone) + lexical (PostgreSQL full-text) fused with RRF.

Every stage is scoped to one authorized workspace:
  * dense:   Pinecone namespace `ws-<id>` AND metadata filter workspace_id == <id>
  * lexical: SQL WHERE chunks.workspace_id = <id> AND documents.workspace_id = <id>
  * hydrate: chunk rows are re-read from PostgreSQL with the same workspace filter, so a vector
             match that is stale, deleted, from a document being re-indexed, or (hypothetically)
             from another tenant can never reach the prompt or a citation.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import Text, cast, func, literal_column, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Chunk, Document, DocumentStatus
from app.services.embedding_service import EmbeddingProvider
from app.services.vector_service import VectorStore


@dataclass
class Candidate:
    chunk_id: str
    document_id: str
    filename: str
    page_number: int | None
    chunk_index: int
    text: str
    dense_rank: int | None = None
    dense_score: float | None = None
    lexical_rank: int | None = None
    lexical_score: float | None = None
    rrf_score: float = 0.0
    rerank_score: float | None = None


@dataclass
class RetrievalResult:
    candidates: list[Candidate]
    dense_count: int = 0
    lexical_count: int = 0
    timings: dict[str, float] = field(default_factory=dict)


def rrf_fuse(rankings: Sequence[Sequence[str]], k: int = 60) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion: score(d) = sum over rankings of 1 / (k + rank_r(d)), rank from 1.

    Ties break on id so the output is deterministic. Duplicates inside one ranking count once.
    """
    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        seen: set[str] = set()
        for rank, item in enumerate(ranking, start=1):
            if item in seen:
                continue
            seen.add(item)
            scores[item] += 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def dense_search(
    store: VectorStore, embedder: EmbeddingProvider, namespace: str, workspace_id: uuid.UUID, query: str, top_k: int
) -> list[tuple[str, float]]:
    vector = embedder.embed_query(query)
    matches = store.query(namespace, vector, top_k, {"workspace_id": {"$eq": str(workspace_id)}})
    out: list[tuple[str, float]] = []
    for m in matches:
        # Defence in depth: ignore anything whose metadata does not name this workspace.
        if m.metadata.get("workspace_id") != str(workspace_id) or not m.metadata.get("chunk_id"):
            continue
        out.append((str(m.metadata["chunk_id"]), m.score))
    return out


def lexical_search(db: Session, workspace_id: uuid.UUID, query: str, top_k: int) -> list[tuple[str, float]]:
    """PostgreSQL full-text search with OR semantics.

    `websearch_to_tsquery` normalizes the question (stemming, stop-word removal); we then turn
    its AND operators into OR so that natural-language questions still match documents containing
    only some of the terms. `ts_rank_cd` orders results by cover density.
    """
    base = func.websearch_to_tsquery(literal_column("'english'"), query)
    ored = func.to_tsquery(literal_column("'english'"), func.replace(cast(base, Text), "&", "|"))
    rank = func.ts_rank_cd(Chunk.tsv, ored)
    rows = db.execute(
        select(Chunk.id, rank.label("rank"))
        .join(Document, Document.id == Chunk.document_id)
        .where(
            Chunk.workspace_id == workspace_id,
            Document.workspace_id == workspace_id,
            Document.status == DocumentStatus.ready,
            Chunk.tsv.op("@@")(ored),
        )
        .order_by(rank.desc(), Chunk.id)
        .limit(top_k)
    ).all()
    return [(str(r[0]), float(r[1])) for r in rows]


def hydrate(db: Session, workspace_id: uuid.UUID, chunk_ids: Sequence[str]) -> dict[str, Candidate]:
    ids: list[uuid.UUID] = []
    for c in chunk_ids:
        try:
            ids.append(uuid.UUID(c))
        except ValueError:
            continue
    if not ids:
        return {}
    rows = db.execute(
        select(Chunk, Document.filename)
        .join(Document, Document.id == Chunk.document_id)
        .where(
            Chunk.id.in_(ids),
            Chunk.workspace_id == workspace_id,
            Document.workspace_id == workspace_id,
            Document.status == DocumentStatus.ready,
        )
    ).all()
    return {
        str(chunk.id): Candidate(
            chunk_id=str(chunk.id), document_id=str(chunk.document_id), filename=filename,
            page_number=chunk.page_number, chunk_index=chunk.chunk_index, text=chunk.text,
        )
        for chunk, filename in rows
    }


def has_ready_documents(db: Session, workspace_id: uuid.UUID) -> bool:
    return db.execute(
        select(Document.id).where(Document.workspace_id == workspace_id, Document.status == DocumentStatus.ready).limit(1)
    ).first() is not None


def retrieve(
    db: Session, *, workspace_id: uuid.UUID, query: str, store: VectorStore, embedder: EmbeddingProvider, settings: Settings
) -> RetrievalResult:
    namespace = settings.namespace_for(str(workspace_id))
    timings: dict[str, float] = {}

    t = time.perf_counter()
    dense = dense_search(store, embedder, namespace, workspace_id, query, settings.dense_top_k)
    timings["dense_ms"] = (time.perf_counter() - t) * 1000

    t = time.perf_counter()
    lexical = lexical_search(db, workspace_id, query, settings.lexical_top_k)
    timings["lexical_ms"] = (time.perf_counter() - t) * 1000

    t = time.perf_counter()
    fused = rrf_fuse([[c for c, _ in dense], [c for c, _ in lexical]], settings.rrf_k)
    dense_info = {c: (i, s) for i, (c, s) in enumerate(dense, start=1)}
    lex_info = {c: (i, s) for i, (c, s) in enumerate(lexical, start=1)}
    top = fused[: settings.rerank_candidates]
    rows = hydrate(db, workspace_id, [c for c, _ in top])
    candidates: list[Candidate] = []
    for chunk_id, score in top:
        cand = rows.get(chunk_id)
        if cand is None:  # stale vector (document deleted/re-indexing) or foreign chunk: drop it
            continue
        cand.rrf_score = score
        if chunk_id in dense_info:
            cand.dense_rank, cand.dense_score = dense_info[chunk_id]
        if chunk_id in lex_info:
            cand.lexical_rank, cand.lexical_score = lex_info[chunk_id]
        candidates.append(cand)
    timings["fusion_ms"] = (time.perf_counter() - t) * 1000

    return RetrievalResult(candidates=candidates, dense_count=len(dense), lexical_count=len(lexical), timings=timings)
