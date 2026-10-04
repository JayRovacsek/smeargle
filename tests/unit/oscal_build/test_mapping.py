from support.ledger import CLOCK, IDS, catalog, ledger, mapping_row, requirement

from smeargle.oscal_build import mapping


def _build(**overrides):
    return mapping.build(ledger(**overrides), clock=CLOCK, id_factory=IDS)


def test_one_mapping_per_catalog_with_normalised_target():
    document = _build()["mapping-collection"]
    (entry,) = document["mappings"]
    assert entry["target-resource"] == {"type": "catalog", "href": "catalogs/vendor.json"}
    assert entry["source-resource"] == {"type": "catalog", "href": "requirements-catalog.json"}
    assert document["provenance"]["method"] == "automation"
    assert document["provenance"]["mapping-description"]


def test_map_entry_uses_percentage_and_positive_relationship():
    (map_entry,) = _build()["mapping-collection"]["mappings"][0]["maps"]
    assert map_entry["relationship"] == "subset-of"
    assert map_entry["confidence-score"] == {"percentage": 0.85}
    assert map_entry["sources"] == [{"type": "control", "id-ref": "req-1"}]
    assert map_entry["targets"] == [{"type": "control", "id-ref": "c-1.1"}]
    assert map_entry["uuid"] == mapping_row()["map_uuid"]


def test_zero_relation_run_omits_the_collection():
    assert _build(mappings=()) is None


def test_catalog_without_relations_emits_no_mapping_object():
    second = catalog("c2", content_sha256="c" * 64, path="/in/other.json")
    document = _build(catalogs=(catalog(), second))["mapping-collection"]
    assert [e["target-resource"]["href"] for e in document["mappings"]] == [
        "catalogs/vendor.json"
    ]


def test_source_gap_summary_lists_unmapped_accepted_requirements():
    document = _build(
        requirements=(requirement("req-1"), requirement("req-2", text="The system MUST log.")),
    )["mapping-collection"]
    gap = document["mappings"][0]["source-gap-summary"]
    assert gap["unmapped-controls"] == [{"with-ids": ["req-2"]}]
