from fakes.clients import FakeLLMClient

from smeargle.domain.controls import Control, DomainIndex
from smeargle.domain.requirements import Keyword, Requirement
from smeargle.pipeline import retrieve


def _control(control_id, catalog_id="cat-1"):
    return Control("run-1", catalog_id, control_id, "T", "text", "access", "Access", ())


def _index(domains):
    return DomainIndex("idx", "sum", "model", "prompt", domains)


def _requirement(text="The system MUST encrypt."):
    return Requirement(
        "run-1", "req-1", "doc-1", 0, text, text, Keyword.MUST, "proposed", "passed",
        0.9, "MUST", None
    )


def test_relevant_domains_filters_unknown():
    llm = FakeLLMClient(default={"domains": ["access", "made-up"]})
    assert retrieve.relevant_domains(llm, "text", ["access", "audit"]) == ["access"]


def test_nominate_controls_filters_unknown_and_dedups():
    llm = FakeLLMClient(default={"control_ids": ["ac-2", "ac-2", "nope"]})
    controls = [_control("ac-2"), _control("ac-3")]
    assert retrieve.nominate_controls(llm, "text", controls) == ["ac-2"]


def test_merge_domain_indexes_and_domain_controls():
    merged = retrieve.merge_domain_indexes(
        [_index({"access": ["ac-2"]}), _index({"access": ["ac-3"], "audit": ["au-1"]})]
    )
    assert merged.domains == {"access": ["ac-2", "ac-3"], "audit": ["au-1"]}
    mapping = retrieve.domain_controls(merged, [_control("ac-2"), _control("ac-3")])
    assert [c.control_id for c in mapping["access"]] == ["ac-2", "ac-3"]


def test_retrieve_requirement_returns_catalog_control_pairs():
    llm = FakeLLMClient(
        responses=[
            {"domains": ["access"]},
            {"control_ids": ["ac-2"]},
        ]
    )
    controls = [_control("ac-2")]
    pairs = retrieve.retrieve_requirement(
        llm, _requirement(), retrieve.merge_domain_indexes([_index({"access": ["ac-2"]})]),
        controls, meta_prefix="x",
    )
    assert pairs == [("cat-1", "ac-2")]

    empty = FakeLLMClient(responses=[{"domains": []}])
    assert retrieve.retrieve_requirement(
        empty, _requirement(), _index({"access": ["ac-2"]}), controls, meta_prefix="x"
    ) == []
