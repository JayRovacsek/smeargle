"""Client Protocols shared by the pipeline (spec 8)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol, Sequence, TypeVar, runtime_checkable

from pydantic import BaseModel

from smeargle.domain.jev import JevQuestion, JevResult

ModelT = TypeVar("ModelT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class CallMeta:
    stage: str
    item_ref: str
    call_type: str
    prompt_hash: Optional[str] = None


@runtime_checkable
class CallRecorder(Protocol):
    def request(
        self, *, stage: str, item_ref: str, call_type: str, request: Any,
        prompt_hash: Optional[str] = None,
    ) -> None: ...

    def response(
        self, *, stage: str, item_ref: str, call_type: str, request: Any, response: Any,
        http_status: Optional[int] = None, attempt_no: Optional[int] = None,
        prompt_hash: Optional[str] = None,
    ) -> None: ...

    def attempt(
        self, *, stage: str, item_ref: str, call_type: str, attempt_no: int,
        http_status: Optional[int] = None, error_class: Optional[str] = None,
        error: Optional[str] = None, duration_ms: Optional[int] = None,
    ) -> None: ...


@runtime_checkable
class LLMClient(Protocol):
    def complete_json(
        self,
        schema: type[ModelT],
        messages: Sequence[Mapping[str, str]],
        *,
        meta: Optional[CallMeta] = None,
    ) -> ModelT: ...


@runtime_checkable
class JevClient(Protocol):
    def systemone(
        self, state: str, questions: Sequence[JevQuestion], *, meta: Optional[CallMeta] = None
    ) -> JevResult: ...

    def systemone_batch(
        self,
        states: Sequence[str],
        questions: Sequence[JevQuestion],
        *,
        meta: Optional[CallMeta] = None,
    ) -> list[JevResult]: ...
