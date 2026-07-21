r"""Step 4.2 — retry with backoff for transient API errors.

Wraps a single call (e.g. one batch's classify_values call) so a transient
failure — rate limit, timeout, dropped connection, 5xx — doesn't abort the
whole run. It retries with exponential backoff (+ jitter) up to a max number
of attempts, then gives up and raises RetryExhaustedError so the caller can
log the batch as failed and move on to the next one instead of crashing.

Uses the REAL anthropic SDK exception classes to decide what's retryable, so
this logic needs zero changes when moving from the mock to --live:

  retryable (transient, worth retrying):
    RateLimitError, APIConnectionError/APITimeoutError, InternalServerError,
    OverloadedError
  NOT retryable (retrying won't help — fail fast with a clear message):
    AuthenticationError, PermissionDeniedError, BadRequestError,
    NotFoundError, UnprocessableEntityError, RequestTooLargeError
"""

from __future__ import annotations

import random
import time
from typing import Callable, TypeVar

import anthropic

T = TypeVar("T")

# Anthropic error types worth retrying — the request itself was probably fine,
# something transient on the network/server side failed.
_RETRYABLE_TYPES = (
    anthropic.RateLimitError,
    anthropic.APIConnectionError,  # covers APITimeoutError (subclass)
    anthropic.InternalServerError,
    anthropic.OverloadedError,
)


class RetryExhaustedError(RuntimeError):
    """Raised when every retry attempt failed. Wraps the last underlying error."""

    def __init__(self, attempts: int, last_error: Exception):
        super().__init__(f"gave up after {attempts} attempt(s): {last_error}")
        self.attempts = attempts
        self.last_error = last_error


def is_retryable(exc: Exception) -> bool:
    return isinstance(exc, _RETRYABLE_TYPES)


def call_with_retry(
    fn: Callable[..., T],
    *args,
    max_attempts: int = 4,
    base_delay: float = 1.0,
    max_delay: float = 20.0,
    sleep: Callable[[float], None] = time.sleep,
    on_retry: Callable[[int, Exception, float], None] | None = None,
    **kwargs,
) -> T:
    """Call fn(*args, **kwargs), retrying transient anthropic errors.

    Non-retryable errors (bad auth, bad request, etc.) and non-anthropic
    exceptions (bugs) are raised immediately on the first attempt — retrying
    those would just waste time and hide the real problem.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - deliberately broad, re-raised below
            if not is_retryable(exc):
                raise
            if attempt >= max_attempts:
                raise RetryExhaustedError(attempt, exc) from exc
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay += random.uniform(0, delay * 0.25)  # jitter, avoids thundering herd
            if on_retry:
                on_retry(attempt, exc, delay)
            sleep(delay)
