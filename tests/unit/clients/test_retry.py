import httpx
import pytest

from smeargle.clients.retry import Attempt, RetryPolicy, request_with_retry
from smeargle.errors import ServiceError


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
