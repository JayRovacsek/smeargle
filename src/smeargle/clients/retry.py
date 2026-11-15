"""Idempotent HTTP retry policy with per-attempt recording (spec 8.3)."""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Callable, Optional

import httpx

from smeargle.errors import FatalServiceError, ServiceError

if TYPE_CHECKING:
    import openai

RETRY_STATUSES = frozenset({408, 429, *range(500, 600)})
RETRY_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
)
MAX_BACKOFF_SECONDS = 60.0
RETRYABLE_STATUSES = RETRY_STATUSES


def retry_after_seconds(exc: "openai.APIStatusError") -> Optional[float]:
    """Extract a retry delay from an SDK status error's response headers.

    Mirrors the openai SDK's own header precedence: ``retry-after-ms``
    (milliseconds), then ``retry-after`` (seconds, allowing nonstandard
    floats), then ``retry-after`` as an HTTP-date. Returns ``None`` when no
    usable header is present.
    """
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    ms = headers.get("retry-after-ms")
    if ms is not None:
        try:
            return max(0.0, float(ms) / 1000.0)
        except ValueError:
            pass
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


@dataclass(frozen=True, slots=True)
class Attempt:
    attempt_no: int
    http_status: Optional[int]
    error_class: Optional[str]
    error: Optional[str]


def _retry_after(response: Optional[httpx.Response]) -> Optional[float]:
    if response is None:
        return None
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    if not math.isfinite(parsed):
        return None
    return max(0.0, parsed)


class RetryPolicy:
    def __init__(
        self,
        retries: int = 3,
        *,
        base: float = 0.5,
        cap: float = 8.0,
        rng: Optional[random.Random] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.retries = max(0, retries)
        self.base = base
        self.cap = cap
        self._rng = rng or random.Random()
        self._sleep = sleep

    def delay(self, attempt_no: int, response: Optional[httpx.Response] = None) -> float:
        retry_after = _retry_after(response)
        if retry_after is not None:
            return min(self.cap, retry_after)
        ceiling = min(self.cap, self.base * (2 ** (attempt_no - 1)))
        return self._rng.uniform(0.0, ceiling)

    def sleep(self, seconds: float) -> None:
        self._sleep(seconds)


def request_with_retry(
    send: Callable[[], httpx.Response],
    *,
    policy: RetryPolicy,
    on_attempt: Optional[Callable[[Attempt], None]] = None,
    idempotent: bool = True,
) -> httpx.Response:
    max_attempts = policy.retries + 1 if idempotent else 1
    last_error: Optional[ServiceError] = None
    for attempt_no in range(1, max_attempts + 1):
        try:
            response = send()
        except RETRY_EXCEPTIONS as exc:
            if on_attempt is not None:
                on_attempt(Attempt(attempt_no, None, type(exc).__name__, str(exc)))
            error_class = FatalServiceError if isinstance(exc, httpx.ConnectError) else ServiceError
            last_error = error_class(f"{type(exc).__name__}: {exc}")
            if attempt_no < max_attempts:
                policy.sleep(policy.delay(attempt_no))
                continue
            raise last_error from exc
        if on_attempt is not None:
            on_attempt(Attempt(attempt_no, response.status_code, None, None))
        if response.status_code in RETRY_STATUSES:
            if attempt_no < max_attempts:
                policy.sleep(policy.delay(attempt_no, response))
                continue
            raise ServiceError(
                f"service returned {response.status_code} after {attempt_no} attempt(s)"
            )
        return response
    raise last_error or ServiceError("retry loop exhausted")
