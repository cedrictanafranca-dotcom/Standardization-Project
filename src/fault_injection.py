r"""Demo-only fault injection for Step 4.

There's no live API to actually fail against yet, so this wraps a real client
(mock or live) and injects REAL anthropic exception types on a schedule you
control — proving the retry/backoff logic in retry.py actually recovers (or
correctly gives up) before any money is spent on the real API.

Not used by the app in normal operation — only by --simulate-* flags in the
Step 4 demo script.
"""

from __future__ import annotations

import httpx
from anthropic import InternalServerError, RateLimitError

_FAKE_REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def rate_limit_error() -> RateLimitError:
    response = httpx.Response(status_code=429, request=_FAKE_REQUEST)
    return RateLimitError("simulated: rate limit exceeded", response=response, body=None)


def server_error() -> InternalServerError:
    response = httpx.Response(status_code=500, request=_FAKE_REQUEST)
    return InternalServerError("simulated: internal server error", response=response, body=None)


class FlakyClient:
    """Wraps a client; the first `fail_times` calls raise a transient error.

    After the budget is exhausted, every call passes through to the real
    client normally. Set fail_times higher than max_attempts on the retry
    call to demonstrate a batch that permanently fails.
    """

    def __init__(self, inner, fail_times: int, error_factory=rate_limit_error):
        self.inner = inner
        self.fail_times = fail_times
        self.error_factory = error_factory
        self.name = f"{inner.name} + FlakyClient(fail_times={fail_times})"
        self._calls = 0

    def complete(self, system_prompt: str, user_message: str) -> str:
        self._calls += 1
        if self._calls <= self.fail_times:
            raise self.error_factory()
        return self.inner.complete(system_prompt, user_message)
