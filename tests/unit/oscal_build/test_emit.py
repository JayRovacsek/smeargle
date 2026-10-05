import json

import pytest
from support.ledger import CLOCK, IDS, catalog, ledger, mapping_row, requirement

from smeargle.errors import IntegrityError
from smeargle.oscal_build import emit, facade


@pytest.fixture(autouse=True)
def _support(tmp_path):
    facade.configure_support_file(tmp_path / "support.db")


def _assemble(**overrides):
    return emit.assemble(ledger(**overrides), clock=CLOCK, id_factory=IDS)


def test_assembly_contains_every_document_and_gate_passes(tmp_path):
    assembly = _assemble()
    emit.integrity_gate(assembly, ledger())
    written = emit.write_assembly(assembly, tmp_path)
    assert sorted(path.name for path in written) == [
        "mapping-collection.json", "profile.json", "rationale.json",
        "requirements-catalog.json",
    ]


def test_zero_accepted_run_emits_empty_groups_and_passes_gate(tmp_path):
    # No accepted requirement: the requirements catalog still has one (control-less) group
    # per source document and a back-matter resource per document; write_assembly and the
    # integrity gate both accept it, and mapping-collection.json is omitted.
    source = ledger(
        requirements=(requirement(gate="rejected", retrieve=None),), mappings=(), pairs=(),
    )
    assembly = emit.assemble(source, clock=CLOCK, id_factory=IDS)
    assert assembly.mapping_collection is None
    (group,) = assembly.requirements_catalog["catalog"]["groups"]
    assert "controls" not in group
    emit.integrity_gate(assembly, source)
    written = emit.write_assembly(assembly, tmp_path)
    assert "mapping-collection.json" not in {path.name for path in written}


def test_gate_rejects_accepted_requirement_missing_from_every_artifact():
    source = ledger(
        requirements=(requirement("req-1"), requirement("req-2", text="MUST log.")),
        mappings=(mapping_row("req-1"),), catalogs=(catalog(),),
    )
    assembly = emit.assemble(source, clock=CLOCK, id_factory=IDS)
    # Strip req-2 from BOTH the per-catalog gap summary and the run-level list so it is
    # genuinely absent from every artifact before the gate runs.
    mapping_collection = json.loads(json.dumps(assembly.mapping_collection))
    for entry in mapping_collection["mapping-collection"]["mappings"]:
        entry.pop("source-gap-summary", None)
    assembly = emit.Assembly(
        requirements_catalog=assembly.requirements_catalog, profile=assembly.profile,
        mapping_collection=mapping_collection,
        rationale=dict(assembly.rationale, unmapped_requirements=[]),
        unmapped_requirements=(), failures=0,
    )
    with pytest.raises(IntegrityError):
        emit.integrity_gate(assembly, source)


def test_gate_rejects_unresolved_fragment_reference():
    assembly = _assemble()
    broken = json.loads(json.dumps(assembly.requirements_catalog))
    broken["catalog"]["groups"][0]["controls"][0]["links"][0]["href"] = "#deadbeef"
    broken = emit.Assembly(
        requirements_catalog=broken, profile=assembly.profile,
        mapping_collection=assembly.mapping_collection, rationale=assembly.rationale,
        unmapped_requirements=assembly.unmapped_requirements, failures=0,
    )
    with pytest.raises(IntegrityError):
        emit.integrity_gate(broken, ledger())


def test_gate_rejects_relative_reference_link_not_absolute():
    assembly = _assemble()
    broken = json.loads(json.dumps(assembly.profile))
    broken["profile"]["modify"]["alters"][0]["adds"][0]["links"][0]["href"] = "not-a-uri"
    broken = emit.Assembly(
        requirements_catalog=assembly.requirements_catalog, profile=broken,
        mapping_collection=assembly.mapping_collection, rationale=assembly.rationale,
        unmapped_requirements=assembly.unmapped_requirements, failures=0,
    )
    with pytest.raises(IntegrityError):
        emit.integrity_gate(broken, ledger())


def test_gate_rejects_duplicate_control_ids():
    from smeargle.domain.controls import Control

    source = ledger(
        catalogs=(catalog(), catalog("c2", content_sha256="c" * 64)),
        controls=(Control("run-1", "c1", "c-1", "t", "x", "", ""),
                  Control("run-1", "c2", "c-1", "t", "x", "", "")),
    )
    assembly = emit.assemble(source, clock=CLOCK, id_factory=IDS)
    with pytest.raises(IntegrityError):
        emit.integrity_gate(assembly, source)


def test_partial_assembly_emits_only_the_requirements_catalog(tmp_path):
    assembly = emit.assemble(
        ledger(mappings=(), pairs=(), requirements=(requirement(),)),
        clock=CLOCK, id_factory=IDS, partial=True,
    )
    assert assembly.profile is None and assembly.mapping_collection is None
    assert assembly.rationale == {}
    emit.integrity_gate(assembly, ledger(), partial=True)
    assert [path.name for path in emit.write_assembly(assembly, tmp_path)] == [
        "requirements-catalog.json"
    ]
