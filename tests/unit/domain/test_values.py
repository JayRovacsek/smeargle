from smeargle.domain.controls import Control, DomainIndex
from smeargle.domain.documents import Document
from smeargle.domain.mapping import (
    POSITIVE_RELATIONSHIPS,
    CandidatePair,
    MappingRecord,
    Relationship,
)
from smeargle.domain.requirements import Keyword, Requirement
from smeargle.domain.run import RunConfig, RunFingerprint


def test_keyword_excludes_may_and_optional():
    values = {k.value for k in Keyword}
    assert "MAY" not in values
    assert "OPTIONAL" not in values
    assert Keyword.MUST.value == "MUST"


def test_relationship_has_exactly_six_values():
    assert {r.value for r in Relationship} == {
        "equivalent-to",
        "equal-to",
        "subset-of",
        "superset-of",
        "intersects-with",
        "no-relationship",
    }
    assert len(POSITIVE_RELATIONSHIPS) == 5
    assert Relationship.NO_RELATIONSHIP not in POSITIVE_RELATIONSHIPS


def test_document_is_frozen_and_hashable():
    doc = Document("run", "doc", 0, "p", "u", None, "text/plain", "sha", 1, "x")
    assert doc == Document("run", "doc", 0, "p", "u", None, "text/plain", "sha", 1, "x")
    hash(doc)


def test_requirement_holds_keyword_and_status():
    req = Requirement(
        run_id="run",
        req_id="req-1",
        doc_id="doc",
        ordinal=0,
        text="MUST x",
        normalized_text="MUST x",
        keyword=Keyword.MUST,
        extract_status="proposed",
        gate_status=None,
        gate_noul_prob=None,
        gate_choice=None,
        retrieve_status=None,
    )
    assert req.keyword is Keyword.MUST
    hash(req)


def test_control_and_domain_index_values():
    control = Control("run", "cat", "c1", "title", "text", "d", "f", ("a", "b"))
    assert control == Control("run", "cat", "c1", "title", "text", "d", "f", ("a", "b"))
    hash(control)
    index = DomainIndex("idx", "sum", "model", "prompt", {"d": ["c1"]})
    assert index == DomainIndex("idx", "sum", "model", "prompt", {"d": ["c1"]})


def test_candidate_pair_and_mapping_record_values():
    pair = CandidatePair("run", "pair", "req", "cat", "c1", "pending", 0.9)
    assert pair == CandidatePair("run", "pair", "req", "cat", "c1", "pending", 0.9)
    hash(pair)
    record = MappingRecord("run", "req", "cat", "c1", Relationship.SUBSET_OF, 0.9, "high")
    assert record == MappingRecord(
        "run", "req", "cat", "c1", Relationship.SUBSET_OF, 0.9, "high"
    )
    hash(record)


def test_run_values_are_frozen():
    fp = RunFingerprint(fingerprint="f", config_hash="c")
    rc = RunConfig(values={"a": 1})
    assert fp.fingerprint == "f"
    assert rc.values["a"] == 1
