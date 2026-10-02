"""Client Protocols shared by the pipeline (spec 8)."""

from __future__ import annotations

from typing import Mapping, Protocol, Sequence, runtime_checkable

from pydantic import BaseModel

from smeargle.domain.jev import JevQuestion, JevResult


@runtime_checkable
class LLMClient(Protocol):
    def complete_json(
        self, schema: type[BaseModel], messages: Sequence[Mapping[str, str]]
    ) -> BaseModel: ...


@runtime_checkable
class JevClient(Protocol):
    def systemone(self, state: str, questions: Sequence[JevQuestion]) -> JevResult: ...

    def systemone_batch(
        self, states: Sequence[str], questions: Sequence[Sequence[JevQuestion]]
    ) -> list[JevResult]: ...
