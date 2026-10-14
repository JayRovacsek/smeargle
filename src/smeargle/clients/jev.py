"""Laya SystemOne JEV client (spec 8.2, 8.3)."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional, Sequence

import httpx

from smeargle.clients.dto import (
    JevBatchRequestModel,
    JevBatchResponseModel,
    JevSystemOneResponseModel,
    jev_result_to_domain,
    question_to_keyed_wire,
    question_to_wire,
    single_result_to_domain,
)
from smeargle.clients.ports import CallMeta, CallRecorder
from smeargle.clients.retry import Attempt, RetryPolicy, request_with_retry
from smeargle.domain.jev import JevQuestion, JevResult
from smeargle.errors import FatalServiceError, ServiceError

_BATCH_LIMIT = 64

_logger = logging.getLogger(__name__)


def _batches(items: list[Any], size: int) -> list[list[Any]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


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
        self._batch = batch
        self._batch_size = min(_BATCH_LIMIT, max(1, batch_size))
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
        if self._min_confidence is not None:
            payload["min_confidence"] = self._min_confidence
        response = self._post("/v1/systemone", payload, meta)
        parsed = JevSystemOneResponseModel.model_validate(self._safe_json(response))
        return single_result_to_domain(questions, parsed.answers)

    # The reference server does not implement /v1/systemone/batch; this wire
    # shape follows the spec and remains unverified against a live endpoint.
    def systemone_batch(
        self,
        states: Sequence[str],
        questions: Sequence[Sequence[JevQuestion]],
        *,
        meta: Optional[CallMeta] = None,
    ) -> list[JevResult]:
        pairs = list(zip(states, questions))
        if not self._batch:
            return [self.systemone(state, qs, meta=meta) for state, qs in pairs]
        results: list[JevResult] = []
        for group in _batches(pairs, self._batch_size):
            payload = JevBatchRequestModel(
                model=self._model,
                states=[state for state, _qs in group],
                questions=[[question_to_wire(q) for q in qs] for _state, qs in group],
                min_confidence=self._min_confidence,
            ).model_dump(exclude_none=True)
            response = self._post("/v1/systemone/batch", payload, meta)
            parsed = JevBatchResponseModel.model_validate(self._safe_json(response))
            if len(parsed.results) != len(group):
                raise ServiceError(
                    f"JEV batch returned {len(parsed.results)} result(s) "
                    f"for {len(group)} submitted state(s)"
                )
            for (_state, qs), answers in zip(group, parsed.results):
                results.append(jev_result_to_domain(qs[0], answers))
        return results

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
