from smeargle.domain.mapping import CandidatePair
from smeargle.domain.requirements import Keyword, Requirement
from smeargle.store.run_store import RunStore


def test_list_pair_rows_returns_classify_columns(tmp_path):
    with RunStore.open(tmp_path) as store:
        store.create_run("run-1", "fp", "ch")
        store.add_candidate_pair(
            CandidatePair("run-1", "pair-1", "req-1", "c-1", "c-1.1", "passed", 0.9)
        )
        store.set_pair_classify(
            "run-1", "pair-1", classify_status="done", relation="subset-of",
            confidence_percentage=0.85, confidence_category="high",
        )
        (row,) = store.list_pair_rows("run-1")
        assert row["classify_status"] == "done"
        assert row["relation"] == "subset-of"
        assert row["confidence_percentage"] == 0.85
        assert row["confidence_category"] == "high"


def test_list_attempts_returns_rows_in_stable_order(tmp_path):
    with RunStore.open(tmp_path) as store:
        store.create_run("run-1", "fp", "ch")
        for ref in ("pair-2", "pair-1"):
            store.record_attempt(
                run_id="run-1", stage="verify", item_ref=ref, call_type="jev_noul",
                attempt_no=0, error_class="per_item_failure", error="boom",
            )
        assert [row["item_ref"] for row in store.list_attempts("run-1")] == [
            "pair-1", "pair-2"
        ]


def test_add_requirement_still_typed_for_ledger(tmp_path):
    with RunStore.open(tmp_path) as store:
        store.create_run("run-1", "fp", "ch")
        store.add_requirement_if_absent(
            Requirement("run-1", "req-1", "d1", 0, "MUST x", "MUST x", Keyword.MUST,
                        "proposed", "passed", 0.9, "MUST", "nominated")
        )
        (requirement,) = store.list_requirements("run-1")
        assert requirement.req_id == "req-1"
