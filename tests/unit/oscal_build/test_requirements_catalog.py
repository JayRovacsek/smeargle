from support.ledger import CLOCK, IDS, document, ledger, requirement

from smeargle.errors import IntegrityError
from smeargle.oscal_build import requirements_catalog


def _build(**overrides):
    return requirements_catalog.build(ledger(**overrides), clock=CLOCK, id_factory=IDS)


def test_groups_by_document_with_props_and_statement():
    catalog = _build()["catalog"]
    assert catalog["metadata"]["oscal-version"] == "1.2.3"
    assert catalog["metadata"]["last-modified"] == "2026-01-01T00:00:00Z"
    (group,) = catalog["groups"]
    assert group["id"] == "doc-d1"
    (control,) = group["controls"]
    assert control["id"] == "req-1"
    props = {prop["name"]: prop["value"] for prop in control["props"]}
    assert props["keyword"] == "MUST"
    assert props["requirement-source"] == "d1"
    assert control["parts"][0]["name"] == "statement"
    assert control["parts"][0]["prose"] == "The system MUST encrypt data at rest."


def test_control_link_resolves_to_document_back_matter_resource():
    catalog = _build()["catalog"]
    resource_uuid = catalog["back-matter"]["resources"][0]["uuid"]
    href = catalog["groups"][0]["controls"][0]["links"][0]["href"]
    assert href == f"#{resource_uuid}"
    assert catalog["back-matter"]["resources"][0]["rlinks"][0]["href"] == "file:///in/spec.txt"


def test_only_accepted_requirements_are_emitted():
    assert len(_build()["catalog"]["groups"][0]["controls"]) == 1

    # A run with no accepted requirement still emits one group per source document (with no
    # "controls" key) plus a back-matter resource per document, so §11.1 "links each source
    # document" holds and the catalog stays schema-valid (groups/controls minItems 1).
    zero_source = ledger(
        requirements=(requirement(gate="rejected", retrieve=None),), mappings=(), pairs=(),
    )
    rejected = requirements_catalog.build(zero_source, clock=CLOCK, id_factory=IDS)["catalog"]
    (group,) = rejected["groups"]
    assert "controls" not in group
    assert rejected["back-matter"]["resources"]


def test_documents_are_content_sorted_and_req_id_collision_fails_fast():
    first = document("d2", content_sha256="0" * 64, path="/in/a.txt", uri="file:///in/a.txt")
    second = document("d1", content_sha256="f" * 64, path="/in/b.txt", uri="file:///in/b.txt")
    catalog = _build(
        documents=(first, second),
        requirements=(
            requirement("req-b", doc_id="d2", text="B MUST be."),
            requirement("req-a", doc_id="d1", text="A MUST be."),
        ),
    )["catalog"]
    # §11.7 orders by ascending content_sha256, so "0"*64 (doc-d2) precedes "f"*64 (doc-d1).
    assert [group["id"] for group in catalog["groups"]] == ["doc-d2", "doc-d1"]

    with_dupe = ledger(requirements=(requirement("req-1"), requirement("req-1", ordinal=1)))
    try:
        requirements_catalog.build(with_dupe, clock=CLOCK, id_factory=IDS)
    except IntegrityError:
        pass
    else:
        raise AssertionError("expected IntegrityError for colliding req_id")
