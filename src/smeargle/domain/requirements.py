"""Requirement domain value and RFC 2119 keyword enum (spec 5)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Keyword(str, Enum):
    MUST = "MUST"
    MUST_NOT = "MUST NOT"
    SHALL = "SHALL"
    SHALL_NOT = "SHALL NOT"
    REQUIRED = "REQUIRED"
    SHOULD = "SHOULD"
    SHOULD_NOT = "SHOULD NOT"
    RECOMMENDED = "RECOMMENDED"
    NOT_RECOMMENDED = "NOT RECOMMENDED"


@dataclass(frozen=True, slots=True)
class Requirement:
    run_id: str
    req_id: str
    doc_id: str
    ordinal: int
    text: str
    normalized_text: str
    keyword: Optional[Keyword]
    extract_status: str
    gate_status: Optional[str]
    gate_noul_prob: Optional[float]
    gate_choice: Optional[str]
    retrieve_status: Optional[str]
