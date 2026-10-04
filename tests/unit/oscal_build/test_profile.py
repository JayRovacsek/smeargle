from support.ledger import CLOCK, IDS, catalog, ledger, mapping_row

from smeargle.oscal_build import profile


def _build(**overrides):
    mapping_present = overrides.pop("mapping_present", True)
    return profile.build(
        ledger(**overrides), mapping_present=mapping_present, clock=CLOCK, id_factory=IDS
    )


def test_imports_one_include_all_per_catalog():
    assert _build()["profile"]["imports"] == [{"href": "catalogs/vendor.json", "include-all": {}}]


def test_alters_keyed_by_control_id_with_one_add_per_requirement():
    body = _build(
        mappings=(mapping_row("req-2"), mapping_row("req-1", control_id="c-1.1")),
    )["profile"]
    (alter,) = body["modify"]["alters"]
    assert alter["control-id"] == "c-1.1"
    assert [add["props"][0]["value"] for add in alter["adds"]] == ["req-1", "req-2"]
    first = alter["adds"][0]
    assert first["props"][1] == {
        "name": "confidence-category", "value": "high", "group": "req-1",
    }
    resource_uuid = IDS.uuid_for("artifact-resource", "run-1:requirements-catalog.json")
    assert first["links"][0] == {
        "rel": "reference", "href": f"#{resource_uuid}", "resource-fragment": "req-1",
    }


def test_modify_omitted_when_nothing_is_mapped_but_imports_remain():
    body = _build(mappings=())["profile"]
    assert "modify" not in body
    assert body["imports"]


def test_mapping_resource_only_when_collection_is_emitted():
    titles = [r["title"] for r in _build()["profile"]["back-matter"]["resources"]]
    assert titles == ["requirements-catalog.json", "rationale.json", "mapping-collection.json"]
    without = profile.build(
        ledger(mappings=(), catalogs=(catalog(),)), mapping_present=False,
        clock=CLOCK, id_factory=IDS,
    )["profile"]
    assert [r["title"] for r in without["back-matter"]["resources"]] == [
        "requirements-catalog.json", "rationale.json",
    ]
