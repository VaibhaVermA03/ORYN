from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

DISCLAIMER = (
    "Scores are computed on the supplied dataset only. A small sample is a noisy signal and does not "
    "guarantee production accuracy. LLM-judged metrics are estimates and can be biased."
)


class EvalSample(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    ground_truth: str | None = Field(default=None, max_length=4000)
    # Filenames (as shown in the Knowledge Base) that should appear in the retrieved context.
    relevant_documents: list[str] | None = Field(default=None, max_length=20)

    @field_validator("question")
    @classmethod
    def _q(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("question must not be blank")
        return v


class EvalDataset(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    samples: list[EvalSample] = Field(min_length=1)


class EvalRunRequest(BaseModel):
    dataset: EvalDataset
    judge: bool = False  # enable LLM-judged metrics (extra OpenAI calls and cost)


class EvalResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question: str
    ground_truth: str | None
    answer: str | None
    contexts: list[Any]
    metrics: dict[str, Any]
    error: str | None


class EvalRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    dataset_name: str
    status: str
    sample_count: int
    config: dict[str, Any]
    metrics: dict[str, Any]
    error_summary: str | None
    created_at: datetime
    finished_at: datetime | None
    disclaimer: str = DISCLAIMER


class EvalRunDetail(EvalRunOut):
    results: list[EvalResultOut]
