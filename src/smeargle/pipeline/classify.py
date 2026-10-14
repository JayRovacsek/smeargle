"""Stage 5: JEV `choice` OSCAL relationship classification (spec 10)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from smeargle.clients.ports import CallMeta, JevClient
from smeargle.domain.jev import JevAnswer, JevQuestion
from smeargle.domain.mapping import POSITIVE_RELATIONSHIPS, MappingRecord, Relationship
from smeargle.pipeline.verify import relation_state


@dataclass(frozen=True, slots=True)
class ClassifyOutcome:
    classify_status: str
    relation: Optional[Relationship]
    confidence_percentage: Optional[float]
    raw_choice: Optional[str] = None
    low_confidence: bool = False


def category_for(confidence: float, *, high: float, medium: float) -> str:
    if confidence >= high:
        return "high"
    if confidence >= medium:
        return "medium"
    return "low"


def choice_question() -> JevQuestion:
    options = tuple(relation.value for relation in POSITIVE_RELATIONSHIPS)
    return JevQuestion(
        question="Which OSCAL relationship best describes how the requirement maps to the control?",
        kind="choice",
        options=options,
    )


def outcome_for(
    answer: Optional[JevAnswer], *, min_confidence: Optional[float] = None
) -> ClassifyOutcome:
    if answer is None:
        return ClassifyOutcome("unmapped", None, None)
    if min_confidence is not None and answer.answer_confidence < min_confidence:
        return ClassifyOutcome("skipped", None, None, answer.answer, low_confidence=True)
    try:
        relation = Relationship(answer.answer)
    except ValueError:
        return ClassifyOutcome("unmapped", None, None, answer.answer)
    if relation not in POSITIVE_RELATIONSHIPS:
        return ClassifyOutcome("unmapped", None, None, answer.answer)
    return ClassifyOutcome("done", relation, answer.answer_confidence, answer.answer)


def classify_pair(
    jev: JevClient,
    requirement_text: str,
    control_text: str,
    *,
    min_confidence: Optional[float] = None,
    meta: Optional[CallMeta] = None,
) -> ClassifyOutcome:
    result = jev.systemone(
        relation_state(requirement_text, control_text), [choice_question()], meta=meta
    )
    return outcome_for(result.answers[0] if result.answers else None, min_confidence=min_confidence)


def classify_batch(
    jev: JevClient,
    items: Sequence[tuple[str, str, str]],
    *,
    min_confidence: Optional[float] = None,
    meta: Optional[CallMeta] = None,
) -> list[ClassifyOutcome]:
    states = [relation_state(requirement, control) for _pair_id, requirement, control in items]
    questions = [choice_question()]
    return [
        outcome_for(result.answers[0] if result.answers else None, min_confidence=min_confidence)
        for result in jev.systemone_batch(states, questions, meta=meta)
    ]


def build_mapping_record(
    *,
    run_id: str,
    req_id: str,
    catalog_id: str,
    control_id: str,
    outcome: ClassifyOutcome,
    category_high: float,
    category_medium: float,
) -> MappingRecord:
    assert outcome.relation is not None and outcome.confidence_percentage is not None
    return MappingRecord(
        run_id=run_id,
        req_id=req_id,
        catalog_id=catalog_id,
        control_id=control_id,
        relation=outcome.relation,
        confidence_percentage=outcome.confidence_percentage,
        confidence_category=category_for(
            outcome.confidence_percentage, high=category_high, medium=category_medium
        ),
    )
