"""Stage 1: chunk documents, propose requirements with the LLM, gate with JEV (spec 10)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

from smeargle.clients.dto import ExtractionResponseModel, extraction_to_candidates
from smeargle.clients.ports import CallMeta, JevClient, LLMClient
from smeargle.domain.jev import JevQuestion, JevResult
from smeargle.domain.requirements import Keyword, Requirement
from smeargle.prompts import extraction as extraction_prompt

_WHITESPACE = re.compile(r"\s+")
AUTHENTICITY_QUESTION = (
    "Is the following text a genuine, actionable normative requirement? "
    "Answer 'yes' or 'no'."
)
KEYWORD_QUESTION = "Which RFC 2119 keyword does this requirement use?"


def normalise_text(text: str) -> str:
    normalised = unicodedata.normalize("NFKC", text)
    normalised = normalised.replace("\r\n", "\n").replace("\r", "\n")
    normalised = _WHITESPACE.sub(" ", normalised)
    return normalised.strip()


def chunk_text(text: str, *, chunk_size: int, overlap: int) -> list[str]:
    if chunk_size < 1:
        raise ValueError("chunk_size must be >= 1")
    overlap = max(0, min(overlap, chunk_size - 1))
    if len(text) <= chunk_size:
        return [text] if text.strip() else []
    step = chunk_size - overlap
    chunks: list[str] = []
    for start in range(0, len(text), step):
        chunk = text[start : start + chunk_size]
        if chunk.strip():
            chunks.append(chunk)
        if start + chunk_size >= len(text):
            break
    return chunks


def propose_chunk(
    llm: LLMClient, chunk: str, *, meta: Optional[CallMeta] = None
) -> list[tuple[str, Keyword, str]]:
    messages = [{"role": "user", "content": extraction_prompt.render_extraction(chunk)}]
    response = llm.complete_json(ExtractionResponseModel, messages, meta=meta)
    return extraction_to_candidates(response)


@dataclass(frozen=True, slots=True)
class GateOutcome:
    gate_status: str
    extract_status: str
    gate_noul_prob: Optional[float]
    gate_choice: Optional[str]
    keyword: Optional[Keyword]
    low_confidence: bool = False


def _rejected(probability: Optional[float], choice: Optional[str], *, low: bool = False) -> GateOutcome:
    return GateOutcome("rejected", "rejected", probability, choice, None, low)


def _gate_meta(meta: Optional[CallMeta], suffix: str) -> Optional[CallMeta]:
    if meta is None:
        return None
    return CallMeta(
        stage=meta.stage,
        item_ref=meta.item_ref,
        call_type=f"{meta.call_type}_{suffix}",
        prompt_hash=None,
    )


def gate_requirement(
    jev: JevClient,
    requirement: Requirement,
    *,
    threshold: float,
    min_confidence: Optional[float] = None,
    meta: Optional[CallMeta] = None,
) -> GateOutcome:
    noul = JevQuestion(question=AUTHENTICITY_QUESTION, kind="noul")
    result: JevResult = jev.systemone(requirement.text, [noul], meta=_gate_meta(meta, "noul"))
    probability = result.answers[0].answer_confidence if result.answers else 0.0
    if probability < threshold:
        return _rejected(probability, None)
    if min_confidence is not None and probability < min_confidence:
        return _rejected(probability, None, low=True)
    options = tuple(keyword.value for keyword in Keyword)
    choice = JevQuestion(question=KEYWORD_QUESTION, kind="choice", options=options)
    choice_result = jev.systemone(requirement.text, [choice], meta=_gate_meta(meta, "choice"))
    if not choice_result.answers:
        return _rejected(probability, None)
    answer = choice_result.answers[0]
    try:
        keyword = Keyword(answer.answer)
    except ValueError:
        return _rejected(probability, answer.answer)
    if min_confidence is not None and answer.answer_confidence < min_confidence:
        return _rejected(probability, answer.answer, low=True)
    return GateOutcome("passed", "passed", probability, answer.answer, keyword)
