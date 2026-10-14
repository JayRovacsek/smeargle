"""OpenAI-compatible chat-completions client backed by the official openai SDK (spec 8.1, 8.3)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Mapping, Optional, Sequence, TypeVar

import httpx
import openai
from pydantic import BaseModel, ValidationError

from smeargle.clients.dto import loads_strict
from smeargle.clients.ports import CallMeta, CallRecorder
from smeargle.errors import FatalServiceError, ServiceError

_logger = logging.getLogger(__name__)

_MODES = ("json_schema", "json_object", "plain")
_MAX_REPAIRS = 2
_RETRYABLE_STATUSES = frozenset({408, 429, *range(500, 600)})

ModelT = TypeVar("ModelT", bound=BaseModel)


class _StructuredRejected(Exception):
    pass


class _SdkResponse:
    """Wrapper to unify SDK response with httpx-like interface for recording."""

    def __init__(self, response: Any, status_code: int = 200) -> None:
        self._response = response
        self.status_code = status_code


def _transport_error(exc: openai.APIConnectionError) -> ServiceError:
    """Map an SDK connection failure to a fatal or per-call service error."""
    if isinstance(exc.__cause__, httpx.ConnectError):
        return FatalServiceError(f"{type(exc).__name__}: {exc}")
    return ServiceError(f"{type(exc).__name__}: {exc}")


def _dump_response(response: Any) -> dict[str, Any]:
    """Full parsed response body when available, else a minimal content shape."""
    try:
        return response.model_dump()
    except Exception:
        try:
            content = response.choices[0].message.content
        except Exception:
            content = None
        return {"choices": [{"message": {"content": content}}]}


def extract_first_json_object(text: str) -> str:
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object found in model output")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ValueError("unbalanced JSON object in model output")


class OpenAiCompatibleLLM:
    def __init__(
        self,
        client: openai.OpenAI,
        *,
        model: str,
        retries: int = 3,
        temperature: float = 0.0,
        structured_output: bool = True,
        recorder: Optional[CallRecorder] = None,
        sleep=None,
        rng=None,
    ) -> None:
        self._client = client
        self._model = model
        self._structured_output = structured_output
        self._temperature = temperature
        self._recorder = recorder
        self._retries = retries
        self._sleep = sleep or time.sleep
        self._rng = rng
        self.call_count = 0

    def complete_json(
        self,
        schema: type[ModelT],
        messages: Sequence[Mapping[str, str]],
        *,
        meta: Optional[CallMeta] = None,
    ) -> ModelT:
        last_error: Optional[Exception] = None
        modes = _MODES if self._structured_output else ("plain",)
        for mode in modes:
            try:
                return self._complete_mode(mode, schema, list(messages), meta)
            except _StructuredRejected as exc:
                last_error = exc
        raise ServiceError(f"LLM structured output failed: {last_error}")

    def _complete_mode(
        self,
        mode: str,
        schema: type[BaseModel],
        messages: list[Mapping[str, str]],
        meta: Optional[CallMeta],
    ) -> ModelT:
        schema_prompt = json.dumps(schema.model_json_schema(), sort_keys=True)
        working = list(messages)
        last_error: Optional[Exception] = None
        for repair in range(_MAX_REPAIRS + 1):
            body = self._payload(mode, schema, schema_prompt, working)
            response = self._post(body, meta)
            if response.status_code == 400 and mode != "plain":
                raise _StructuredRejected(f"endpoint rejected {mode}")
            if response.status_code in (401, 403):
                raise FatalServiceError(
                    f"LLM authentication rejected: HTTP {response.status_code}"
                )
            if response.status_code is not None and response.status_code >= 400:
                raise ServiceError(f"LLM returned HTTP {response.status_code}")
            content = self._content(response)
            try:
                payload = loads_strict(extract_first_json_object(content))
                return schema.model_validate(payload)
            except (ValueError, ValidationError) as exc:
                last_error = exc
                if repair >= _MAX_REPAIRS:
                    break
                working = list(messages) + [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": (
                            f"Your previous reply was invalid: {last_error}. "
                            "Reply with JSON only, matching the required schema exactly."
                        ),
                    },
                ]
        raise _StructuredRejected(f"{mode} validation failed: {last_error}")

    def _payload(
        self,
        mode: str,
        schema: type[BaseModel],
        schema_prompt: str,
        messages: list[Mapping[str, str]],
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self._model,
            "temperature": self._temperature,
            "messages": list(messages),
        }
        if mode == "json_schema":
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "strict": True,
                    "schema": schema.model_json_schema(),
                },
            }
        elif mode == "json_object":
            body["response_format"] = {"type": "json_object"}
            body["messages"] = [
                {"role": "system", "content": f"Respond with JSON matching this schema: {schema_prompt}"}
            ] + list(messages)
        else:
            body["messages"] = [
                {"role": "system", "content": f"Respond with one JSON object matching this schema: {schema_prompt}"}
            ] + list(messages)
        return body

    def _post(self, body: dict[str, Any], meta: Optional[CallMeta]) -> _SdkResponse:
        stage = meta.stage if meta is not None else "llm"
        item_ref = meta.item_ref if meta is not None else "-"
        call_type = meta.call_type if meta is not None else "llm"
        if self._recorder is not None and meta is not None:
            self._recorder.request(
                stage=meta.stage, item_ref=meta.item_ref, call_type=meta.call_type,
                request={"url": "/v1/chat/completions", "body": body},
                prompt_hash=meta.prompt_hash,
            )
        start = time.perf_counter()
        last_attempt_no = 0

        def on_attempt(status_code: Optional[int], error_class: Optional[str], error: Optional[str]) -> None:
            nonlocal last_attempt_no
            last_attempt_no += 1
            if self._recorder is not None and meta is not None:
                self._recorder.attempt(
                    stage=meta.stage, item_ref=meta.item_ref, call_type=meta.call_type,
                    attempt_no=last_attempt_no, http_status=status_code,
                    error_class=error_class, error=error,
                    duration_ms=int((time.perf_counter() - start) * 1000),
                )

        def record_failure(status_code: Optional[int]) -> None:
            if self._recorder is not None and meta is not None:
                self._recorder.response(
                    stage=meta.stage, item_ref=meta.item_ref, call_type=meta.call_type,
                    request={"url": "/v1/chat/completions", "body": body},
                    response={},
                    http_status=status_code,
                    attempt_no=last_attempt_no,
                    prompt_hash=meta.prompt_hash,
                )

        def backoff(attempt_no: int) -> None:
            delay = 0.5 * (2 ** (attempt_no - 1))
            _logger.warning(
                "llm retry %s %s attempt %s",
                call_type, item_ref, attempt_no + 1,
                extra={"smeargle": {
                    "stage": stage, "item_ref": item_ref, "call_type": call_type,
                    "model": self._model, "attempt_no": attempt_no + 1,
                }},
            )
            self._sleep(self._rng.uniform(0.0, min(8.0, delay)) if self._rng else delay)

        for attempt_no in range(1, self._retries + 2):
            try:
                response = self._client.chat.completions.create(**body)
            except openai.RateLimitError as exc:
                on_attempt(429, "RateLimitError", str(exc))
                if attempt_no <= self._retries:
                    backoff(attempt_no)
                    continue
                _logger.error(
                    "llm %s %s failed: rate limited",
                    call_type, item_ref,
                    extra={"smeargle": {
                        "stage": stage, "item_ref": item_ref, "call_type": call_type,
                        "model": self._model, "http_status": 429,
                    }},
                )
                record_failure(429)
                return _SdkResponse(None, 429)
            except openai.APIStatusError as exc:
                on_attempt(exc.status_code, "APIStatusError", str(exc))
                if exc.status_code in (401, 403):
                    record_failure(exc.status_code)
                    raise FatalServiceError(
                        f"LLM authentication rejected: HTTP {exc.status_code}"
                    ) from exc
                if exc.status_code in _RETRYABLE_STATUSES and attempt_no <= self._retries:
                    backoff(attempt_no)
                    continue
                _logger.error(
                    "llm %s %s failed: HTTP %s",
                    call_type, item_ref, exc.status_code,
                    extra={"smeargle": {
                        "stage": stage, "item_ref": item_ref, "call_type": call_type,
                        "model": self._model, "http_status": exc.status_code,
                    }},
                )
                record_failure(exc.status_code)
                return _SdkResponse(None, exc.status_code)
            except openai.APIConnectionError as exc:
                on_attempt(None, type(exc).__name__, str(exc))
                if attempt_no <= self._retries:
                    backoff(attempt_no)
                    continue
                _logger.error(
                    "llm %s %s failed: %s",
                    call_type, item_ref, type(exc).__name__,
                    extra={"smeargle": {
                        "stage": stage, "item_ref": item_ref, "call_type": call_type,
                        "model": self._model, "error_class": type(exc).__name__,
                    }},
                )
                record_failure(None)
                raise _transport_error(exc) from exc
            except Exception as exc:
                on_attempt(None, type(exc).__name__, str(exc))
                _logger.error(
                    "llm %s %s failed: %s",
                    call_type, item_ref, type(exc).__name__,
                    extra={"smeargle": {
                        "stage": stage, "item_ref": item_ref, "call_type": call_type,
                        "model": self._model, "error_class": type(exc).__name__,
                    }},
                )
                record_failure(None)
                raise ServiceError(f"LLM request failed: {exc}") from exc

            last_attempt_no = attempt_no
            self.call_count += 1
            _logger.info(
                "llm %s %s ok (%sms)",
                call_type, item_ref, int((time.perf_counter() - start) * 1000),
                extra={"smeargle": {
                    "stage": stage, "item_ref": item_ref, "call_type": call_type,
                    "model": self._model, "http_status": 200,
                    "attempt_no": last_attempt_no,
                    "duration_ms": int((time.perf_counter() - start) * 1000),
                }},
            )
            if self._recorder is not None and meta is not None:
                self._recorder.response(
                    stage=meta.stage, item_ref=meta.item_ref, call_type=meta.call_type,
                    request={"url": "/v1/chat/completions", "body": body},
                    response=_dump_response(response),
                    http_status=200,
                    attempt_no=last_attempt_no,
                    prompt_hash=meta.prompt_hash,
                )
                self._recorder.attempt(
                    stage=meta.stage, item_ref=meta.item_ref, call_type=meta.call_type,
                    attempt_no=last_attempt_no, http_status=200,
                    duration_ms=int((time.perf_counter() - start) * 1000),
                )
            return _SdkResponse(response, 200)

        raise ServiceError(f"LLM request failed after {self._retries + 1} attempts")

    @staticmethod
    def _content(response: _SdkResponse) -> str:
        if response is None or response._response is None:
            raise ServiceError("LLM response is empty")
        try:
            return str(response._response.choices[0].message.content)
        except (AttributeError, IndexError, TypeError, ValueError) as exc:
            raise ServiceError(f"LLM response missing choices[0].message.content: {exc}") from exc