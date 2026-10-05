import jsonschema_rs
import pytest
from support.artifacts import validate_output
from support.ledger import CLOCK, IDS, ledger, mapping_row, requirement
from support.schemas import validate_against_schema

from smeargle.oscal_build import emit, facade


@pytest.fixture(autouse=True)
def _support(tmp_path):
    facade.configure_support_file(tmp_path / "support.db")


def test_every_artifact_validates_against_metaschema_and_vendored_schema(tmp_path):
    assembly = emit.assemble(ledger(), clock=CLOCK, id_factory=IDS)
    emit.write_assembly(assembly, tmp_path)
    assert sorted(validate_output(tmp_path)) == [
        "mapping-collection.json", "profile.json", "rationale.json",
        "requirements-catalog.json",
    ]


def test_zero_relation_run_omits_mapping_collection_and_still_validates(tmp_path):
    source = ledger(mappings=(), pairs=(), requirements=(requirement(retrieve="none"),))
    assembly = emit.assemble(source, clock=CLOCK, id_factory=IDS)
    emit.write_assembly(assembly, tmp_path)
    names = validate_output(tmp_path)
    assert "mapping-collection.json" not in names
    assert "requirements-catalog.json" in names


def test_adversarial_documents_are_rejected_not_coerced():
    bad_mapping = {
        "mapping-collection": {
            "uuid": "not-a-uuid", "metadata": {}, "provenance": {}, "mappings": [],
        }
    }
    with pytest.raises(jsonschema_rs.ValidationError):
        validate_against_schema("mapping-collection", bad_mapping)
    with pytest.raises(Exception):
        emit.assemble(
            ledger(mappings=(mapping_row(relation="definitely-related"),)),
            clock=CLOCK, id_factory=IDS,
        )


def test_reassembling_the_same_ledger_is_byte_identical(tmp_path):
    source = ledger()
    first = emit.write_assembly(emit.assemble(source, clock=CLOCK, id_factory=IDS),
                                tmp_path / "a")
    second = emit.write_assembly(emit.assemble(source, clock=CLOCK, id_factory=IDS),
                                 tmp_path / "b")
    for left, right in zip(sorted(first, key=lambda p: p.name),
                           sorted(second, key=lambda p: p.name)):
        assert left.read_bytes() == right.read_bytes()
