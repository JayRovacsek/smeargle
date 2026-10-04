"""Stage 4: JEV `noul` verification of candidate pairs (spec 10)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from smeargle.clients.ports import CallMeta, JevClient
from smeargle.domain.jev import JevQuestion


def relation_state(requirement_text: str, control_text: str) -> str:
    return f"Requirement: {requirement_text}\nControl: {control_text}"


@dataclass(frozen=True, slots=True)
class VerifyOutcome:
    verify_status: str
    noul_prob: Optional[float]
    low_confidence: bool = False


def noul_question() -> JevQuestion:
    return JevQuestion(
        question="Does the requirement relate to the control? Answer 'yes' or 'no'.",
        kind="noul",
    )


def outcome_for(
    probability: float, *, threshold: float, min_confidence: Optional[float] = None
) -> VerifyOutcome:
    if min_confidence is not None and probability < min_confidence:
        return VerifyOutcome("rejected", probability, low_confidence=True)
    return VerifyOutcome("passed" if probability >= threshold else "rejected", probability)


def verify_pair(
    jev: JevClient,
    requirement_text: str,
    control_text: str,
    *,
    threshold: float,
    min_confidence: Optional[float] = None,
    meta: Optional[CallMeta] = None,
) -> VerifyOutcome:
    result = jev.systemone(relation_state(requirement_text, control_text), [noul_question()], meta=meta)
    probability = result.answers[0].answer_confidence if result.answers else 0.0
    return outcome_for(probability, threshold=threshold, min_confidence=min_confidence)


def verify_batch(
    jev: JevClient,
    items: Sequence[tuple[str, str, str]],
    *,
    threshold: float,
    min_confidence: Optional[float] = None,
    meta: Optional[CallMeta] = None,
) -> list[VerifyOutcome]:
    states = [relation_state(requirement, control) for _pair_id, requirement, control in items]
    questions = [[noul_question()] for _ in items]
    return [
        outcome_for(
            result.answers[0].answer_confidence if result.answers else 0.0,
            threshold=threshold,
            min_confidence=min_confidence,
        )
        for result in jev.systemone_batch(states, questions, meta=meta)
    ]
