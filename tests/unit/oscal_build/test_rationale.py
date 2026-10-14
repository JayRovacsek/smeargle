from support.ledger import CLOCK, IDS, ledger, pair_row, requirement, run_block

from smeargle.oscal_build import rationale


def _build(**overrides):
    return rationale.build(ledger(**overrides), clock=CLOCK, id_factory=IDS)


def test_run_block_carries_identity_and_redacted_config():
    document = _build(run=run_block(config={"llm": {"base_url": "https://llm"}}))
    assert document["run"]["run_id"] == "run-1"
    assert document["run"]["config"]["llm"]["base_url"] == "https://llm"
    assert document["summary"]["generated_at"] == "2026-01-01T00:00:00Z"


def test_per_requirement_reports_mapped_and_unmapped_reasons():
    document = _build(
        requirements=(
            requirement("req-1"),
            requirement("req-2", text="The system MUST log.", retrieve="none"),
        ),
        pairs=(pair_row(),),
    )
    by_id = {item["req_id"]: item for item in document["requirements"]}
    assert by_id["req-1"]["status"] == "mapped"
    assert by_id["req-2"]["status"] == "unmapped"
    assert by_id["req-2"]["reason"] == "no nominated candidates"
    assert document["unmapped_requirements"] == [
        {"req_id": "req-2", "doc_id": "d1", "reason": "no nominated candidates"}
    ]


def test_rejected_candidates_are_retained_separately():
    document = _build(
        requirements=(
            requirement("req-1"),
            requirement("req-9", text="Bad", gate="rejected", retrieve=None,
                        gate_noul_prob=0.1),
        ),
    )
    assert all(item["req_id"] != "req-9" for item in document["requirements"])
    (rejected,) = document["rejected_candidates"]
    assert rejected["req_id"] == "req-9"
    assert rejected["gate_noul_prob"] == 0.1


def test_all_skipped_classifications_report_the_suppression_reason():
    document = _build(
        pairs=(pair_row(classify="skipped", relation=None, percentage=None, category=None),),
        mappings=(),
    )
    assert document["unmapped_requirements"][0]["reason"] == (
        "all candidate classifications suppressed by jev-min-confidence"
    )


def test_pair_evidence_holds_noul_and_choice_numbers_and_counts():
    evidence = (
        {"stage": "classify", "item_ref": "pair:pair-1", "call_type": "jev_choice",
         "response": {"answers": [{"answer": "subset-of", "answer_confidence": 0.85,
                                   "confidence": 0.42}]}},
    )
    document = _build(evidence=evidence)
    (pair,) = document["pairs"]
    assert pair["noul_prob"] == 0.9
    assert pair["choice"] == {"answer": "subset-of", "answer_confidence": 0.85,
                              "confidence": 0.42}
    assert pair["evidence"] == {"stage": "classify", "item_ref": "pair:pair-1",
                                "call_type": "jev_choice"}
    assert document["summary"]["mapped"] == 1
