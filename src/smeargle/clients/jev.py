"""Laya SystemOne JEV client (spec 8.2, 8.3)."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional, Sequence

import httpx

from smeargle.clients.dto import (
    JevSystemOneResponseModel,
    question_to_keyed_wire,
    single_result_to_domain,
)
from smeargle.clients.ports import CallMeta, CallRecorder
from smeargle.clients.retry import Attempt, RetryPolicy, request_with_retry
from smeargle.domain.jev import JevQuestion, JevResult
from smeargle.errors import FatalServiceError, ServiceError

_logger = logging.getLogger(__name__)


class LayaJevClient:
    def __init__(
        self,
        client: httpx.Client,
        *,
        model: str,
        retries: int = 3,
        batch: bool = False,
        batch_size: int = 64,
        min_confidence: Optional[float] = None,
        recorder: Optional[CallRecorder] = None,
        sleep=None,
        rng=None,
    ) -> None:
        self._client = client
        self._model = model
        # batch/batch_size are accepted for CLI compatibility; the target
        # server does not support batching, so calls always loop per state.
        self._min_confidence = min_confidence
        self._recorder = recorder
        self._policy = RetryPolicy(retries, sleep=sleep or time.sleep, rng=rng)

    def systemone(
        self, state: str, questions: Sequence[JevQuestion], *, meta: Optional[CallMeta] = None
    ) -> JevResult:
        payload: dict[str, Any] = {
            "model": self._model,
            "state": state,
            "questions": {f"q{i}": question_to_keyed_wire(q) for i, q in enumerate(questions)},
        }
        # client-side gate only; not part of the wire request
        response = self._post("/v1/systemone", payload, meta)
        parsed = JevSystemOneResponseModel.model_validate(self._safe_json(response))
        return single_result_to_domain(questions, parsed.answers)

    # The target server has no batch route; batching falls back to per-state
    # calls regardless of the batch flag.
    def systemone_batch(
        self,
        states: Sequence[str],
        questions: Sequence[JevQuestion],
        *,
        meta: Optional[CallMeta] = None,
    ) -> list[JevResult]:
        return [self.systemone(state, questions, meta=meta) for state in states]

    def _post(
        self, path: str, payload: dict[str, Any], meta: Optional[CallMeta]
    ) -> httpx.Response:
        if self._recorder is not None and meta is None:
            meta = CallMeta(stage="", item_ref="", call_type="")
        stage = meta.stage if meta is not None else "jev"
        item_ref = meta.item_ref if meta is not None else "-"
        call_type = meta.call_type if meta is not None else "jev"
        if self._recorder is not None and meta is not None:
            self._recorder.request(
                stage=meta.stage, item_ref=meta.item_ref, call_type=meta.call_type,
                request={"url": path, "body": payload}, prompt_hash=meta.prompt_hash,
            )
        start = time.perf_counter()
        last_attempt: Optional[Attempt] = None

        def on_attempt(attempt: Attempt) -> None:
            nonlocal last_attempt
            last_attempt = attempt
            if attempt.attempt_no > 1 or attempt.error_class is not None:
                _logger.warning(
                    "jev retry %s %s attempt %s",
                    call_type, item_ref, attempt.attempt_no,
                    extra={"smeargle": {
                        "stage": stage, "item_ref": item_ref, "call_type": call_type,
                        "model": self._model, "attempt_no": attempt.attempt_no,
                        "http_status": attempt.http_status,
                        "error_class": attempt.error_class,
                    }},
                )
            if self._recorder is not None and meta is not None:
                self._recorder.attempt(
                    stage=meta.stage, item_ref=meta.item_ref, call_type=meta.call_type,
                    attempt_no=attempt.attempt_no, http_status=attempt.http_status,
                    error_class=attempt.error_class, error=attempt.error,
                    duration_ms=int((time.perf_counter() - start) * 1000),
                )

        try:
            response = request_with_retry(
                lambda: self._client.post(path, json=payload),
                policy=self._policy,
                on_attempt=on_attempt,
            )
        except ServiceError as exc:
            _logger.error(
                "jev %s %s failed: %s", call_type, item_ref, exc,
                extra={"smeargle": {
                    "stage": stage, "item_ref": item_ref, "call_type": call_type,
                    "model": self._model, "error_class": type(exc).__name__,
                    "attempt_no": last_attempt.attempt_no if last_attempt else None,
                    "duration_ms": int((time.perf_counter() - start) * 1000),
                }},
            )
            raise
        duration_ms = int((time.perf_counter() - start) * 1000)
        if self._recorder is not None and meta is not None:
            self._recorder.response(
                stage=meta.stage, item_ref=meta.item_ref, call_type=meta.call_type,
                request={"url": path, "body": payload}, response=self._safe_json(response),
                http_status=response.status_code,
                attempt_no=last_attempt.attempt_no if last_attempt else None,
                prompt_hash=meta.prompt_hash,
            )
        if response.status_code in (401, 403):
            _logger.error(
                "jev %s %s failed: HTTP %s", call_type, item_ref, response.status_code,
                extra={"smeargle": {
                    "stage": stage, "item_ref": item_ref, "call_type": call_type,
                    "model": self._model, "http_status": response.status_code,
                    "attempt_no": last_attempt.attempt_no if last_attempt else None,
                    "duration_ms": duration_ms,
                }},
            )
            raise FatalServiceError(f"JEV authentication rejected: HTTP {response.status_code}")
        if response.status_code >= 400:
            _logger.error(
                "jev %s %s failed: HTTP %s", call_type, item_ref, response.status_code,
                extra={"smeargle": {
                    "stage": stage, "item_ref": item_ref, "call_type": call_type,
                    "model": self._model, "http_status": response.status_code,
                    "attempt_no": last_attempt.attempt_no if last_attempt else None,
                    "duration_ms": duration_ms,
                }},
            )
            raise ServiceError(f"JEV returned HTTP {response.status_code}")
        _logger.info(
            "jev %s %s ok (%sms)", call_type, item_ref, duration_ms,
            extra={"smeargle": {
                "stage": stage, "item_ref": item_ref, "call_type": call_type,
                "model": self._model, "http_status": response.status_code,
                "attempt_no": last_attempt.attempt_no if last_attempt else None,
                "duration_ms": duration_ms,
            }},
        )
        return response

    @staticmethod
    def _safe_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except (ValueError,):
            return {"text": response.text}
