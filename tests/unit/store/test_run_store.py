import json
import zlib
from datetime import datetime, timezone

import pytest

from smeargle.domain.clock import FrozenClock
from smeargle.domain.controls import Control, DomainIndex
from smeargle.domain.documents import Document
from smeargle.domain.ids import UuidIdFactory
from smeargle.domain.mapping import CandidatePair, MappingRecord, Relationship
from smeargle.domain.requirements import Keyword, Requirement
from smeargle.store import run_store as rs
from smeargle.store.run_store import CatalogRow


@pytest.fixture
def store(tmp_path):
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    with rs.RunStore.open(tmp_path, clock=clock, id_factory=UuidIdFactory()) as opened:
        yield opened


def test_create_and_read_run(store):
    store.create_run("run-1", "fp", "cfg")
    row = store.get_run("run-1")
    assert row["fingerprint"] == "fp"
    assert row["status"] == "started"
    assert store.find_runs_by_fingerprint("fp")[0]["run_id"] == "run-1"


def test_set_run_status_marks_finished_at(store):
    store.create_run("run-1", "fp", "cfg")
    store.set_run_status("run-1", "ingested", finished=True)
    row = store.get_run("run-1")
    assert row["status"] == "ingested"
    assert row["finished_at"] is not None


def test_stage_lifecycle(store):
    store.create_run("run-1", "fp", "cfg")
    store.start_stage("run-1", "load")
    assert store.get_stage("run-1", "load")["status"] == "running"
    store.complete_stage("run-1", "load")
    assert store.get_stage("run-1", "load")["status"] == "complete"
    store.start_stage("run-1", "load")
    assert store.get_stage("run-1", "load")["status"] == "running"


def test_add_and_list_documents(store):
    store.create_run("run-1", "fp", "cfg")
    doc = Document(
        run_id="run-1",
        doc_id="d1",
        ordinal=0,
        path="/x/a.txt",
        uri="file:///x/a.txt",
        external_id=None,
        media_type="text/plain",
        content_sha256="d1",
        size_bytes=10,
        text="hello",
    )
    store.add_document(doc)
    assert store.document_content_exists("run-1", "d1")
    assert not store.document_content_exists("run-1", "other")
    rows = store.list_documents("run-1")
    assert [row["doc_id"] for row in rows] == ["d1"]
    assert rows[0]["path"] == "/x/a.txt"


def test_document_content_is_unique_per_run(store):
    store.create_run("run-1", "fp", "cfg")
    doc = Document("run-1", "d1", 0, "a", "u", None, "text/plain", "d1", 1, "x")
    store.add_document(doc)
    duplicate = Document("run-1", "d1", 1, "b", "u2", None, "text/plain", "d1", 1, "x")
    with pytest.raises(Exception):
        store.add_document(duplicate)


def _catalog(store, catalog_id="cat-1"):
    store.create_run("run-1", "fp", "cfg")
    store.add_catalog(
        CatalogRow(
            run_id="run-1",
            catalog_id=catalog_id,
            ordinal=0,
            uri="file:///c.json",
            path="/c.json",
            external_id=None,
            content_sha256=catalog_id,
            oscal_version="1.2.3",
            status="loaded",
        )
    )


def test_add_and_list_controls(store):
    _catalog(store)
    store.add_control(
        Control("run-1", "cat-1", "ac-1", "Policy", "text", "ac", "Access", ("ac",))
    )
    controls = store.list_controls("run-1", "cat-1")
    assert controls[0].control_id == "ac-1"
    assert controls[0].path == ("ac",)
    assert store.list_catalogs("run-1")[0]["catalog_id"] == "cat-1"


def _requirement(req_id, *, gate=None, retrieve=None):
    text = f"The system MUST satisfy {req_id}"
    return Requirement(
        run_id="run-1",
        req_id=req_id,
        doc_id="d1",
        ordinal=0,
        text=text,
        normalized_text=text,
        keyword=Keyword.MUST,
        extract_status="proposed",
        gate_status=gate,
        gate_noul_prob=None,
        gate_choice=None,
        retrieve_status=retrieve,
    )


def test_work_is_derived_with_is_null_predicates(store):
    store.create_run("run-1", "fp", "cfg")
    store.add_requirement(_requirement("req-a"))
    store.add_requirement(_requirement("req-b", gate="passed"))
    store.add_requirement(_requirement("req-c", gate="passed", retrieve="none"))
    store.add_requirement(_requirement("req-d", gate="rejected"))

    gate_work = {r.req_id for r in store.requirements_for_gate("run-1")}
    assert gate_work == {"req-a"}

    retrieval_work = {r.req_id for r in store.requirements_for_retrieval("run-1")}
    assert retrieval_work == {"req-b"}


def test_set_requirement_gate_and_retrieve(store):
    store.create_run("run-1", "fp", "cfg")
    store.add_requirement(_requirement("req-a"))
    store.set_requirement_gate(
        "run-1",
        "req-a",
        gate_status="passed",
        gate_noul_prob=0.9,
        gate_choice="MUST",
        keyword="MUST",
        extract_status="proposed",
    )
    assert {r.req_id for r in store.requirements_for_gate("run-1")} == set()
    assert {r.req_id for r in store.requirements_for_retrieval("run-1")} == {"req-a"}
    store.set_requirement_retrieve_status("run-1", "req-a", "none")
    assert {r.req_id for r in store.requirements_for_retrieval("run-1")} == set()


def test_retrieve_status_terminal_markers(store):
    store.create_run("run-1", "fp", "cfg")
    store.add_requirement(_requirement("req-a", gate="passed"))
    store.add_requirement(_requirement("req-b", gate="passed"))
    store.set_requirement_retrieve_status("run-1", "req-a", "nominated")
    store.set_requirement_retrieve_status("run-1", "req-b", "none")
    assert {r.req_id for r in store.requirements_for_retrieval("run-1")} == set()
    assert store.get_requirement("run-1", "req-a")["retrieve_status"] == "nominated"
    assert store.get_requirement("run-1", "req-b")["retrieve_status"] == "none"


def test_candidates_persisted_pre_gate_and_work_queries(store):
    store.create_run("run-1", "fp", "cfg")
    store.add_candidate_pair(
        CandidatePair("run-1", "pair-a", "req-a", "cat-1", "ac-1", "pending", None)
    )
    store.add_candidate_pair(
        CandidatePair("run-1", "pair-b", "req-a", "cat-1", "ac-2", "passed", 0.9)
    )
    pending = {p.pair_id for p in store.candidate_pairs_for_verify("run-1")}
    assert pending == {"pair-a"}
    classify = {p.pair_id for p in store.candidate_pairs_for_classify("run-1")}
    assert classify == {"pair-b"}
    store.set_pair_verify("run-1", "pair-a", verify_status="rejected", noul_prob=0.1)
    assert {p.pair_id for p in store.candidate_pairs_for_verify("run-1")} == set()


def test_set_pair_classify_terminal(store):
    store.create_run("run-1", "fp", "cfg")
    store.add_candidate_pair(
        CandidatePair("run-1", "pair-b", "req-a", "cat-1", "ac-2", "passed", 0.9)
    )
    store.set_pair_classify(
        "run-1",
        "pair-b",
        classify_status="done",
        relation="subset-of",
        confidence_percentage=0.8,
        confidence_category="high",
    )
    pair = store.get_candidate_pair("run-1", "pair-b")
    assert pair["classify_status"] == "done"
    assert pair["relation"] == "subset-of"


def test_classify_status_terminal_unmapped_and_skipped(store):
    store.create_run("run-1", "fp", "cfg")
    store.add_candidate_pair(
        CandidatePair("run-1", "pair-u", "req-a", "cat-1", "ac-1", "passed", 0.9)
    )
    store.add_candidate_pair(
        CandidatePair("run-1", "pair-s", "req-a", "cat-1", "ac-2", "passed", 0.9)
    )
    store.set_pair_classify("run-1", "pair-u", classify_status="unmapped")
    store.set_pair_classify("run-1", "pair-s", classify_status="skipped")
    assert store.get_candidate_pair("run-1", "pair-u")["classify_status"] == "unmapped"
    assert store.get_candidate_pair("run-1", "pair-s")["classify_status"] == "skipped"
    assert {p.pair_id for p in store.candidate_pairs_for_classify("run-1")} == set()


def test_add_mapping(store):
    store.create_run("run-1", "fp", "cfg")
    store.add_mapping(
        MappingRecord("run-1", "req-a", "cat-1", "ac-2", Relationship.SUBSET_OF, 0.8, "high"),
        rationale="because",
    )
    rows = store.list_mappings("run-1")
    assert rows[0]["relation"] == "subset-of"
    assert rows[0]["rationale"] == "because"


def test_evidence_is_compressed_redacted_and_at_least_once(store):
    store.create_run("run-1", "fp", "cfg")
    store.record_evidence(
        run_id="run-1",
        stage="extract",
        item_ref="doc:d1",
        call_type="llm",
        request={"api_key": "secret", "prompt": "hi"},
    )
    rows = store.list_evidence("run-1")
    assert len(rows) == 1
    request = json.loads(zlib.decompress(rows[0]["request_json"]))
    assert request == {"api_key": "[REDACTED]", "prompt": "hi"}

    store.record_evidence(
        run_id="run-1",
        stage="extract",
        item_ref="doc:d1",
        call_type="llm",
        request={"api_key": "secret", "prompt": "hi"},
        response={"answer": "ok", "authorization": "Bearer x"},
        http_status=200,
        attempt_no=1,
    )
    rows = store.list_evidence("run-1")
    assert len(rows) == 1
    response = json.loads(zlib.decompress(rows[0]["response_json"]))
    assert response == {"answer": "ok", "authorization": "[REDACTED]"}
    assert rows[0]["http_status"] == 200


def test_record_attempt(store):
    store.create_run("run-1", "fp", "cfg")
    store.record_attempt(
        run_id="run-1",
        stage="verify",
        item_ref="pair-a",
        call_type="jev",
        attempt_no=1,
        http_status=503,
        error_class="ServiceUnavailable",
        error="retry",
        duration_ms=12,
    )
    assert store.counts("run-1")["attempts"] == 1


def test_domain_index_round_trip(store):
    store.create_run("run-1", "fp", "cfg")
    index = DomainIndex("idx-1", "content", "model", "prompt", {"access": ["ac-1"]})
    store.add_domain_index(index)
    loaded = store.get_domain_index("content", "model", "prompt")
    assert loaded["index_id"] == "idx-1"
    assert json.loads(loaded["index_json"]) == {"access": ["ac-1"]}
    assert store.get_domain_index("other", "model", "prompt") is None
