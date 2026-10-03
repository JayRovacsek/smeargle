from smeargle.domain.documents import Document
from smeargle.domain.requirements import Keyword, Requirement
from smeargle.pipeline import work
from smeargle.store.run_store import RunStore


def _store(tmp_path):
    store = RunStore.open(tmp_path)
    store.create_run("run-1", "fp", "ch")
    return store


def _requirement(req_id, *, gate=None, retrieve=None):
    return Requirement(
        run_id="run-1",
        req_id=req_id,
        doc_id="doc-1",
        ordinal=0,
        text=req_id,
        normalized_text=req_id,
        keyword=Keyword.MUST,
        extract_status="proposed",
        gate_status=gate,
        gate_noul_prob=None,
        gate_choice=None,
        retrieve_status=retrieve,
    )


def test_pending_gate_and_retrieval_use_is_null_predicates(tmp_path):
    with _store(tmp_path) as store:
        store.add_requirement_if_absent(_requirement("req-a", gate=None))
        store.add_requirement_if_absent(_requirement("req-b", gate="passed", retrieve=None))
        store.add_requirement_if_absent(_requirement("req-c", gate="passed", retrieve="none"))
        assert [r.req_id for r in work.pending_gate(store, "run-1")] == ["req-a"]
        assert [r.req_id for r in work.pending_retrieval(store, "run-1")] == ["req-b"]


def test_pending_documents_lists_loaded_documents_in_order(tmp_path):
    with _store(tmp_path) as store:
        store.add_document(
            Document("run-1", "doc-1", 0, "/p", "file:///p", None, "text/plain", "doc-1", 1, "body")
        )
        assert [row["doc_id"] for row in work.pending_documents(store, "run-1")] == ["doc-1"]


def test_stage_lifecycle_and_completion_flag(tmp_path):
    with _store(tmp_path) as store:
        assert not work.stage_complete(store, "run-1", "extract")
        work.claim_stage(store, "run-1", "extract")
        assert not work.stage_complete(store, "run-1", "extract")
        work.complete_stage(store, "run-1", "extract")
        assert work.stage_complete(store, "run-1", "extract")


def test_evidence_item_refs_are_stable():
    assert work.chunk_ref("doc-1", 2) == "doc:doc-1:chunk:2"
    assert work.pair_ref("req-a", "cat", "c-1") == "pair:req-a:cat:c-1"
