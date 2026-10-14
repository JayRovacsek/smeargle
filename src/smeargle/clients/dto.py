"""Pydantic v2 wire models and ingress conversion to domain values (spec 8)."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Mapping, Sequence, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class JevNoulAnswerModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: Literal["noul"]
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    noul: float | None = Field(default=None, ge=0.0, le=1.0)


class JevChoiceAnswerModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: Literal["choice"]
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    choice: str = Field(min_length=1)
    probabilities: dict[str, float] = Field(default_factory=dict)


JevSingleAnswer = Annotated[
    Union[JevNoulAnswerModel, JevChoiceAnswerModel], Field(discriminator="type")
]


class JevSystemOneResponseModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    answers: dict[str, JevSingleAnswer] = Field(default_factory=dict)


def question_to_keyed_wire(question: JevQuestion) -> dict[str, Any]:
    # The Laya server reads `instructions` for the question text (questions.cpp
    # question_from_json); `question` would be silently ignored.
    wire: dict[str, Any] = {"type": question.kind, "instructions": question.question}
    if question.kind == "choice":
        wire["criteria"] = {option: option for option in question.options}
    return wire


def single_result_to_domain(
    questions: Sequence[JevQuestion], answers: Mapping[str, JevSingleAnswer]
) -> JevResult:
    domain_answers: list[JevAnswer] = []
    for index, question in enumerate(questions):
        answer = answers.get(f"q{index}")
        if answer is None:
            continue
        if answer.type == "noul":
            probability = answer.noul if answer.noul is not None else (answer.confidence or 0.0)
            domain_answers.append(
                JevAnswer(
                    question=question.question,
                    answer="yes" if probability >= 0.5 else "no",
                    answer_confidence=probability,
                    confidence=answer.confidence,
                )
            )
        else:
            domain_answers.append(
                JevAnswer(
                    question=question.question,
                    answer=answer.choice,
                    answer_confidence=answer.probabilities.get(
                        answer.choice, answer.confidence or 0.0
                    ),
                    confidence=answer.confidence,
                )
            )
    return JevResult(answers=tuple(domain_answers))
