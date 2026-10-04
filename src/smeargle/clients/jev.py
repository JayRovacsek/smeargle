"""Laya SystemOne JEV client (spec 8.2, 8.3)."""

from __future__ import annotations

import time
from typing import Any, Optional, Sequence

import httpx

from smeargle.clients.dto import (
    JevBatchRequestModel,
    JevBatchResponseModel,
    JevRequestModel,
    JevResponseModel,
    jev_result_to_domain,
    question_to_wire,
)
from smeargle.clients.ports import CallMeta, CallRecorder
from smeargle.clients.retry import Attempt, RetryPolicy, request_with_retry
from smeargle.domain.jev import JevQuestion, JevResult
from smeargle.errors import FatalServiceError, ServiceError

_BATCH_LIMIT = 64


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
        payload = JevRequestModel(
            model=self._model,
            state=state,
            questions=[question_to_wire(question) for question in questions],
            min_confidence=self._min_confidence,
        ).model_dump(exclude_none=True)
        response = self._post("/v1/systemone", payload, meta)
        parsed = JevResponseModel.model_validate(self._safe_json(response))
        return jev_result_to_domain(questions[0], parsed.answers)

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
            if self._recorder is not None and meta is not None:
                self._recorder.attempt(
                    stage=meta.stage, item_ref=meta.item_ref, call_type=meta.call_type,
                    attempt_no=attempt.attempt_no, http_status=attempt.http_status,
                    error_class=attempt.error_class, error=attempt.error,
                    duration_ms=int((time.perf_counter() - start) * 1000),
                )

        response = request_with_retry(
            lambda: self._client.post(path, json=payload),
            policy=self._policy,
            on_attempt=on_attempt,
        )
        if self._recorder is not None and meta is not None:
            self._recorder.response(
                stage=meta.stage, item_ref=meta.item_ref, call_type=meta.call_type,
                request={"url": path, "body": payload}, response=self._safe_json(response),
                http_status=response.status_code,
                attempt_no=last_attempt.attempt_no if last_attempt else None,
                prompt_hash=meta.prompt_hash,
            )
        if response.status_code in (401, 403):
            raise FatalServiceError(f"JEV authentication rejected: HTTP {response.status_code}")
        if response.status_code >= 400:
            raise ServiceError(f"JEV returned HTTP {response.status_code}")
        return response

    @staticmethod
    def _safe_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except (ValueError,):
            return {"text": response.text}
