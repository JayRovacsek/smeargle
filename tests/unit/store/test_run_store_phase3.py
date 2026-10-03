from smeargle.domain.requirements import Keyword, Requirement
from smeargle.store.run_store import RunStore


def _store(tmp_path):
    return RunStore.open(tmp_path)


def _requirement(req_id="req-1", ordinal=0, keyword=Keyword.MUST):
    return Requirement(
        run_id="run-1",
        req_id=req_id,
        doc_id="doc-1",
        ordinal=ordinal,
        text=f"The system MUST encrypt {req_id}.",
        normalized_text=f"The system MUST encrypt {req_id}.",
        keyword=keyword,
        extract_status="proposed",
        gate_status=None,
        gate_noul_prob=None,
        gate_choice=None,
        retrieve_status=None,
    )


def test_add_requirement_if_absent_is_idempotent(tmp_path):
    with _store(tmp_path) as store:
        store.create_run("run-1", "fp", "ch")
        store.add_requirement_if_absent(_requirement())
        store.add_requirement_if_absent(_requirement())
        assert len(store.list_requirements("run-1")) == 1


def test_list_candidate_pairs_returns_typed_values(tmp_path):
    with _store(tmp_path) as store:
        store.create_run("run-1", "fp", "ch")
        from smeargle.domain.mapping import CandidatePair

        store.add_candidate_pair(
            CandidatePair("run-1", "pair-b", "req-a", "cat-1", "c-2", "pending")
        )
        store.add_candidate_pair(
            CandidatePair("run-1", "pair-a", "req-a", "cat-1", "c-1", "passed", 0.9)
        )
        pairs = store.list_candidate_pairs("run-1")
        assert [p.pair_id for p in pairs] == ["pair-a", "pair-b"]
        assert pairs[0].noul_prob == 0.9


def test_record_attempt_is_idempotent_on_same_key(tmp_path):
    with _store(tmp_path) as store:
        store.create_run("run-1", "fp", "ch")
        first = store.record_attempt(
            run_id="run-1", stage="extract", item_ref="gate:req-1",
            call_type="jev_gate_noul", attempt_no=1, http_status=200, duration_ms=5,
        )
        second = store.record_attempt(
            run_id="run-1", stage="extract", item_ref="gate:req-1",
            call_type="jev_gate_noul", attempt_no=1, http_status=200, duration_ms=9,
        )
        assert first == second
        assert store.counts("run-1")["attempts"] == 1


def test_list_requirements_returns_typed_values_in_order(tmp_path):
    with _store(tmp_path) as store:
        store.create_run("run-1", "fp", "ch")
        store.add_requirement_if_absent(_requirement("req-b", ordinal=1, keyword=Keyword.SHOULD))
        store.add_requirement_if_absent(_requirement("req-a", ordinal=0))
        requirements = store.list_requirements("run-1")
        assert [r.req_id for r in requirements] == ["req-a", "req-b"]
        assert requirements[0].keyword is Keyword.MUST
