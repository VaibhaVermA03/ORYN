"""Chat-completion provider abstraction. The default implementation streams from OpenAI."""

from __future__ import annotations

import threading
from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol

import openai
from openai import AsyncOpenAI

from app.core.config import get_settings
from app.core.exceptions import ProviderError
from app.services.embedding_service import classify_openai_error


class LLMProvider(Protocol):
    model: str

    def stream(self, messages: Sequence[dict[str, str]]) -> AsyncIterator[str]: ...


class OpenAIChat:
    def __init__(self) -> None:
        s = get_settings()
        if not s.openai_api_key:
            raise ProviderError("openai", "OPENAI_API_KEY is not configured")
        self.model = s.openai_chat_model
        self._s = s
        # The SDK retries connection errors, 429s and 5xx before the first token (bounded).
        self._client = AsyncOpenAI(api_key=s.openai_api_key, timeout=s.openai_timeout_seconds,
                                   max_retries=s.openai_max_retries)

    async def stream(self, messages: Sequence[dict[str, str]]) -> AsyncIterator[str]:
        kwargs: dict[str, Any] = {
            "model": self.model, "messages": list(messages), "stream": True,
            "max_completion_tokens": self._s.chat_max_output_tokens,
        }
        if self._s.openai_temperature is not None:
            kwargs["temperature"] = self._s.openai_temperature
        try:
            response = await self._client.chat.completions.create(**kwargs)
            async for event in response:
                if event.choices and event.choices[0].delta.content:
                    yield event.choices[0].delta.content
        except openai.OpenAIError as exc:
            retryable, message = classify_openai_error(exc)
            raise ProviderError("openai", message, retryable=retryable) from exc


_llm: LLMProvider | None = None
_lock = threading.Lock()


def get_llm() -> LLMProvider:
    global _llm
    if _llm is None:
        with _lock:
            if _llm is None:
                _llm = OpenAIChat()
    return _llm


def set_llm(llm: LLMProvider | None) -> None:
    """Override the provider (used by tests; production code never calls this)."""
    global _llm
    _llm = llm
