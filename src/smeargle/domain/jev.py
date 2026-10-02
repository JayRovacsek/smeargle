"""Frozen JEV request/response values (spec 5, 8.2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


@dataclass(frozen=True, slots=True)
class JevQuestion:
    question: str
    kind: str
    options: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class JevAnswer:
    question: str
    answer: str
    answer_confidence: float
    confidence: Optional[float] = None


@dataclass(frozen=True, slots=True)
class JevResult:
    answers: tuple[JevAnswer, ...]
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False)
