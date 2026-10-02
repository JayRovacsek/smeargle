"""Pydantic v2 wire models and ingress conversion to domain values (spec 8)."""

from __future__ import annotations

import json
from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from smeargle.domain.jev import JevAnswer, JevQuestion, JevResult
from smeargle.domain.requirements import Keyword


def to_keyword(raw: str) -> Keyword:
    cleaned = " ".join(raw.strip().upper().replace("_", " ").split())
    try:
        return Keyword(cleaned)
    except ValueError as exc:
        raise ValueError(f"unknown RFC 2119 keyword: {raw!r}") from exc


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def loads_strict(text: str) -> Any:
    return json.loads(text, object_pairs_hook=_no_duplicate_keys)


class ExtractionCandidateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    keyword: str
    rationale: str = ""

    @field_validator("keyword")
    @classmethod
    def _known_keyword(cls, value: str) -> str:
        to_keyword(value)
        return value


class ExtractionResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirements: list[ExtractionCandidateModel] = Field(default_factory=list)


def extraction_to_candidates(
    response: ExtractionResponseModel,
) -> list[tuple[str, Keyword, str]]:
    return [(item.text, to_keyword(item.keyword), item.rationale) for item in response.requirements]


class ControlLabelModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    control_id: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    family: str = ""


class IndexResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    labels: list[ControlLabelModel] = Field(default_factory=list)


class DomainSelectionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domains: list[str] = Field(default_factory=list)


class NominationResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    control_ids: list[str] = Field(default_factory=list)


class JevQuestionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["noul", "choice"]
    question: str = Field(min_length=1)
    options: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _choice_requires_options(self) -> "JevQuestionModel":
        if self.kind == "choice" and not self.options:
            raise ValueError("choice questions require options")
        return self


def question_to_wire(question: JevQuestion) -> JevQuestionModel:
    return JevQuestionModel(
        kind=question.kind,  # type: ignore[arg-type]
        question=question.question,
        options=list(question.options),
    )


class JevRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    state: str
    questions: list[JevQuestionModel]
    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class JevBatchRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    states: list[str]
    questions: list[list[JevQuestionModel]]
    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class JevAnswerModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = ""
    answer: str
    answer_confidence: float = Field(ge=0.0, le=1.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class JevResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answers: list[JevAnswerModel] = Field(default_factory=list)


class JevBatchResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: list[list[JevAnswerModel]] = Field(default_factory=list)


def jev_result_to_domain(question: JevQuestion, answers: Sequence[JevAnswerModel]) -> JevResult:
    domain_answers = tuple(
        JevAnswer(
            question=answer.question or question.question,
            answer=answer.answer,
            answer_confidence=answer.answer_confidence,
            confidence=answer.confidence,
        )
        for answer in answers
    )
    return JevResult(answers=domain_answers)
