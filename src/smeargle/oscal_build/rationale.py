"""Build the §11.4 non-OSCAL rationale process record (pure)."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from smeargle.domain.clock import Clock
from smeargle.domain.ids import IdFactory
from smeargle.domain.requirements import Requirement
from smeargle.domain.run import Ledger
from smeargle.oscal_build.common import oscal_timestamp


def _choice_evidence(
    evidence: tuple[Mapping[str, Any], ...], pair_id: str
) -> Optional[Mapping[str, Any]]:
    for row in evidence:
        if (
            row.get("stage") == "classify"
            and row.get("call_type") == "jev_choice"
            and row.get("item_ref") == f"pair:{pair_id}"
        ):
            return row
    return None


def _choice_numbers(
    evidence: tuple[Mapping[str, Any], ...], pair_row: Mapping[str, Any]
) -> dict[str, Any]:
    row = _choice_evidence(evidence, pair_row["pair_id"])
    answer: Mapping[str, Any] = {}
    if row is not None:
        answers = (row.get("response") or {}).get("answers") or []
        answer = answers[0] if answers else {}
    return {
        "answer": answer.get("answer", pair_row["relation"]),
        "answer_confidence": answer.get("answer_confidence",
                                        pair_row["confidence_percentage"]),
        "confidence": answer.get("confidence"),
    }


def _reason(requirement: Requirement, pairs: list[Mapping[str, Any]]) -> str:
    if not pairs:
        return "no nominated candidates"
    verify = {pair["verify_status"] for pair in pairs}
    classify = {pair["classify_status"] for pair in pairs}
    if verify and verify <= {"rejected"}:
        return "all candidates rejected by JEV verification"
    if classify and classify <= {"skipped"}:
        return "all candidate classifications suppressed by jev-min-confidence"
    if classify and classify <= {"unmapped"}:
        return "all passed candidates classified no-relationship or unparseable"
    return "no mapping produced"


def _pair_rationale(pair: Mapping[str, Any]) -> str:
    if pair["classify_status"] == "done":
        return (
            f"JEV 'noul' probability {pair['noul_prob']} cleared the mapped threshold; "
            f"JEV classified the pair as '{pair['relation']}' with answer confidence "
            f"{pair['confidence_percentage']} ({pair['confidence_category']})."
        )
    return (
        f"JEV 'noul' probability {pair['noul_prob']}; pair ended "
        f"'{pair['classify_status']}'."
    )


def build(ledger: Ledger, *, clock: Clock, id_factory: IdFactory) -> dict[str, Any]:
    del id_factory
    mapped_ids = {mapping["req_id"] for mapping in ledger.mappings}
    pairs_by_req: dict[str, list[Mapping[str, Any]]] = {}
    for pair in ledger.pairs:
        pairs_by_req.setdefault(pair["req_id"], []).append(pair)

    accepted = [r for r in ledger.requirements if r.gate_status == "passed"]
    rejected = [r for r in ledger.requirements if r.gate_status != "passed"]

    requirements: list[dict[str, Any]] = []
    unmapped: list[dict[str, Any]] = []
    for requirement in sorted(accepted, key=lambda r: (r.ordinal, r.req_id)):
        mapped = requirement.req_id in mapped_ids
        reason = "at least one mapping emitted" if mapped else _reason(
            requirement, pairs_by_req.get(requirement.req_id, [])
        )
        requirements.append(
            {
                "req_id": requirement.req_id, "doc_id": requirement.doc_id,
                "text": requirement.text,
                "keyword": requirement.keyword.value if requirement.keyword else None,
                "gate_status": requirement.gate_status,
                "gate_noul_prob": requirement.gate_noul_prob,
                "gate_choice": requirement.gate_choice,
                "status": "mapped" if mapped else "unmapped",
                "reason": reason,
            }
        )
        if not mapped:
            unmapped.append({"req_id": requirement.req_id, "doc_id": requirement.doc_id,
                             "reason": reason})

    rejected_candidates = [
        {"req_id": item.req_id, "doc_id": item.doc_id, "text": item.text,
         "gate_noul_prob": item.gate_noul_prob, "gate_choice": item.gate_choice}
        for item in sorted(rejected, key=lambda r: (r.ordinal, r.req_id))
    ]

    pairs: list[dict[str, Any]] = []
    for pair in sorted(ledger.pairs, key=lambda p: p["pair_id"]):
        pairs.append(
            {
                "pair_id": pair["pair_id"], "req_id": pair["req_id"],
                "catalog_id": pair["catalog_id"], "control_id": pair["control_id"],
                "domain": ledger.domains.get(pair["control_id"]),
                "verify_status": pair["verify_status"], "noul_prob": pair["noul_prob"],
                "classify_status": pair["classify_status"], "relation": pair["relation"],
                "confidence_percentage": pair["confidence_percentage"],
                "confidence_category": pair["confidence_category"],
                "choice": _choice_numbers(ledger.evidence, pair),
                "rationale": _pair_rationale(pair),
                # Stage 3 persists the nominated pairs but not the LLM domain-selection /
                # nomination rationale, so the retrieval rationale is recorded as an
                # explicit null (a documented omission) rather than invented. The pair's
                # `domain` label and the classify evidence pointer carry what is known.
                "retrieval_rationale": None,
                "evidence": {"stage": "classify", "item_ref": f"pair:{pair['pair_id']}",
                             "call_type": "jev_choice"},
            }
        )

    failures = [dict(row) for row in ledger.failures]
    return {
        "run": dict(ledger.run),
        "requirements": requirements,
        "unmapped_requirements": unmapped,
        "rejected_candidates": rejected_candidates,
        "pairs": pairs,
        "failures": failures,
        "summary": {
            "requirements": len(ledger.requirements), "accepted": len(accepted),
            "rejected": len(rejected), "mapped": len(mapped_ids),
            "unmapped": len(unmapped), "pairs": len(ledger.pairs),
            "mappings": len(ledger.mappings), "failures": len(failures),
            "generated_at": oscal_timestamp(clock),
        },
    }
