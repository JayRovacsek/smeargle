from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from types import SimpleNamespace

import httpx
import openai
import pytest

from smeargle.clients.retry import (
    Attempt,
    RetryPolicy,
    request_with_retry,
    retry_after_seconds,
)
from smeargle.errors import ServiceError


def _status_error(headers: dict[str, str], status_code: int = 429) -> openai.APIStatusError:
    request = httpx.Request("POST", "http://test/v1/chat/completions")
    response = httpx.Response(status_code, headers=headers, request=request)
    return openai.APIStatusError("rate limited", response=response, body=None)


class RecordingPolicy(RetryPolicy):
    def __init__(self, **kwargs):
        self.slept: list[float] = []
        super().__init__(**kwargs)

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)


def test_retries_5xx_then_succeeds_and_records_attempts():
    responses = [httpx.Response(503), httpx.Response(200, json={"ok": True})]
    attempts: list[Attempt] = []
    response = request_with_retry(
        lambda: responses.pop(0),
        policy=RecordingPolicy(retries=3, base=0.0),
        on_attempt=attempts.append,
    )
    assert response.status_code == 200
    assert [a.attempt_no for a in attempts] == [1, 2]
    assert attempts[0].http_status == 503


def test_does_not_retry_other_4xx():
    calls = 0

    def send():
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"error": "bad"})

    response = request_with_retry(send, policy=RecordingPolicy(retries=3), on_attempt=lambda _a: None)
    assert response.status_code == 400
    assert calls == 1


def test_respects_retry_after():
    responses = [httpx.Response(429, headers={"Retry-After": "2"}), httpx.Response(200)]
    policy = RecordingPolicy(retries=3)
    request_with_retry(lambda: responses.pop(0), policy=policy, on_attempt=lambda _a: None)
    assert policy.slept == [2.0]


def test_retry_after_is_clamped_to_cap():
    responses = [httpx.Response(429, headers={"Retry-After": "999999"}), httpx.Response(200)]
    policy = RecordingPolicy(retries=3, cap=8.0)
    request_with_retry(lambda: responses.pop(0), policy=policy, on_attempt=lambda _a: None)
    assert policy.slept == [8.0]


def test_non_finite_retry_after_falls_back_to_bounded_backoff():
    responses = [httpx.Response(429, headers={"Retry-After": "inf"}), httpx.Response(200)]
    policy = RecordingPolicy(retries=3, cap=8.0, base=0.0)
    request_with_retry(lambda: responses.pop(0), policy=policy, on_attempt=lambda _a: None)
    assert policy.slept == [0.0]


def test_gives_up_after_retries_with_service_error():
    calls = 0

    def send():
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    with pytest.raises(ServiceError):
        request_with_retry(send, policy=RecordingPolicy(retries=2), on_attempt=lambda _a: None)
    assert calls == 3


def test_non_idempotent_call_is_not_retried():
    calls = 0

    def send():
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    with pytest.raises(ServiceError):
        request_with_retry(
            send, policy=RecordingPolicy(retries=3), idempotent=False, on_attempt=lambda _a: None
        )
    assert calls == 1


def test_retry_after_seconds_parses_seconds_header():
    assert retry_after_seconds(_status_error({"retry-after": "30"})) == 30.0


def test_retry_after_seconds_prefers_ms_over_seconds():
    headers = {"retry-after-ms": "1500", "retry-after": "30"}
    assert retry_after_seconds(_status_error(headers)) == 1.5


def test_retry_after_seconds_parses_http_date_header():
    when = datetime.now(timezone.utc) + timedelta(seconds=120)
    value = retry_after_seconds(_status_error({"retry-after": format_datetime(when)}))
    assert value is not None
    assert 115 <= value <= 121


def test_retry_after_seconds_missing_response_returns_none():
    assert retry_after_seconds(SimpleNamespace()) is None


def test_retry_after_seconds_garbage_value_returns_none():
    assert retry_after_seconds(_status_error({"retry-after": "not-a-number-or-date"})) is None
