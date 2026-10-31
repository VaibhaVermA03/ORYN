"""Bounded retry with exponential backoff for external provider calls."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import TypeVar

from app.core.exceptions import ProviderError

T = TypeVar("T")
logger = logging.getLogger("oryn.retry")


def call_with_retries(
    fn: Callable[[], T],
    *,
    provider: str,
    classify: Callable[[Exception], tuple[bool, str]],
    max_retries: int = 2,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run `fn`, retrying only errors that `classify` marks retryable.

    `classify(exc)` returns (retryable, safe_message). The safe message is what we surface to
    clients; raw provider errors (which may contain request details) are never exposed.
    Raises ProviderError when attempts are exhausted or the error is not retryable.
    """
    attempt = 0
    while True:
        try:
            return fn()
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - provider SDKs raise many exception types
            retryable, message = classify(exc)
            if not retryable or attempt >= max_retries:
                logger.warning(
                    "provider_call_failed",
                    extra={"provider": provider, "exc_type": type(exc).__name__, "attempts": attempt + 1,
                           "retryable": retryable},
                )
                raise ProviderError(provider, message, retryable=retryable) from exc
            delay = min(max_delay, base_delay * (2**attempt)) * (0.5 + random.random() / 2)  # noqa: S311 - backoff jitter, not security
            logger.info("provider_retry", extra={"provider": provider, "attempt": attempt + 1,
                                                  "delay_s": round(delay, 2)})
            sleep(delay)
            attempt += 1
