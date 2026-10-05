"""OpenAI-compatible chat-completions client with structured-output fallbacks (spec 8.1, 8.3)."""

from __future__ import annotations

import json
import time
from typing import Any, Mapping, Optional, Sequence, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from smeargle.clients.dto import loads_strict
from smeargle.clients.ports import CallMeta, CallRecorder
from smeargle.clients.retry import Attempt, RetryPolicy, request_with_retry
from smeargle.errors import FatalServiceError, ServiceError

_MODES = ("json_schema", "json_object", "plain")
_MAX_REPAIRS = 2

ModelT = TypeVar("ModelT", bound=BaseModel)


class _StructuredRejected(Exception):
    pass


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
        client: httpx.Client,
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
        self._policy = RetryPolicy(retries, sleep=sleep or time.sleep, rng=rng)
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
        schema: type[ModelT],
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
            if response.status_code >= 400:
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

    def _post(self, body: dict[str, Any], meta: Optional[CallMeta]) -> httpx.Response:
        if self._recorder is not None and meta is not None:
            self._recorder.request(
                stage=meta.stage, item_ref=meta.item_ref, call_type=meta.call_type,
                request={"url": "/v1/chat/completions", "body": body},
                prompt_hash=meta.prompt_hash,
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
            lambda: self._client.post("/v1/chat/completions", json=body),
            policy=self._policy,
            on_attempt=on_attempt,
        )
        self.call_count += 1
        if self._recorder is not None and meta is not None:
            self._recorder.response(
                stage=meta.stage, item_ref=meta.item_ref, call_type=meta.call_type,
                request={"url": "/v1/chat/completions", "body": body},
                response=self._safe_json(response), http_status=response.status_code,
                attempt_no=last_attempt.attempt_no if last_attempt else None,
                prompt_hash=meta.prompt_hash,
            )
        return response

    @staticmethod
    def _safe_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except (json.JSONDecodeError, ValueError):
            return {"text": response.text}

    @staticmethod
    def _content(response: httpx.Response) -> str:
        try:
            return str(response.json()["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ServiceError(f"LLM response missing choices[0].message.content: {exc}") from exc
