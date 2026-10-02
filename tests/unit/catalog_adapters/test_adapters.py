from smeargle.catalog_adapters import normalise, oscal, vendor_security_controls
from smeargle.catalog_adapters.ids import sanitize_control_id

STANDARD = {
    "catalog": {
        "uuid": "11111111-1111-4111-8111-111111111111",
        "metadata": {
            "title": "Standard Catalog",
            "last-modified": "2026-01-01T00:00:00Z",
            "version": "2.0.0",
            "oscal-version": "1.2.3",
        },
        "groups": [
            {
                "id": "ac",
                "title": "Access Control",
                "controls": [
                    {
                        "id": "ac-2",
                        "title": "Account Management",
                        "parts": [
                            {
                                "id": "ac-2_smt",
                                "name": "statement",
                                "prose": "Manage accounts.",
                            },
                            {
                                "id": "ac-2_smt.a",
                                "name": "item",
                                "prose": "Define account types.",
                            },
                        ],
                    }
                ],
            }
        ],
    }
}

VENDOR = {
    "catalog": {
        "name": "Vendor Controls",
        "securityControls": [
            {
                "controlId": "1.1",
                "title": "Policy",
                "family": "Access Control",
                "description": "Establish a policy.",
            }
        ],
    }
}


def test_standard_adapter_extracts_controls():
    parsed = oscal.parse_standard(STANDARD)
    assert parsed.title == "Standard Catalog"
    assert parsed.version == "2.0.0"
    assert parsed.source_kind == "oscal"
    control = parsed.controls[0]
    assert control.control_id == "ac-2"
    assert control.original_id == "ac-2"
    assert control.domain == "ac"
    assert control.family == "Access Control"
    assert control.path == ("ac",)
    assert "Manage accounts." in control.text
    assert "Define account types." in control.text


def test_vendor_adapter_sanitises_and_preserves_original():
    parsed = vendor_security_controls.parse_vendor(VENDOR)
    assert parsed.title == "Vendor Controls"
    assert parsed.source_kind == "vendor-security-controls"
    control = parsed.controls[0]
    assert control.control_id == "c-1.1"
    assert control.original_id == "1.1"
    assert control.family == "Access Control"
    assert control.text == "Establish a policy."


def test_normalise_builds_valid_shape():
    parsed = vendor_security_controls.parse_vendor(VENDOR)
    document = normalise.build_normalised_catalog(
        catalog_id="cat-1",
        parsed=parsed,
        source_uri="file:///vendor.json",
        last_modified="2026-01-01T00:00:00Z",
        uuid_for=lambda kind, key: "22222222-2222-4222-8222-222222222222",
    )
    catalog = document["catalog"]
    assert catalog["metadata"]["oscal-version"] == "1.2.3"
    assert catalog["metadata"]["title"] == "Vendor Controls"
    group = catalog["groups"][0]
    assert group["title"] == "Access Control"
    control = group["controls"][0]
    assert control["id"] == sanitize_control_id("1.1")
    props = {prop["name"]: prop["value"] for prop in control["props"]}
    assert props["original-id"] == "1.1"
    assert props["source-document"] == "file:///vendor.json"


def test_normalise_omits_empty_parts():
    parsed = vendor_security_controls.parse_vendor(
        {
            "catalog": {
                "name": "V",
                "securityControls": [{"controlId": "1.1", "title": "Empty", "family": "A"}],
            }
        }
    )
    document = normalise.build_normalised_catalog(
        catalog_id="cat-1",
        parsed=parsed,
        source_uri="file:///vendor.json",
        last_modified="2026-01-01T00:00:00Z",
        uuid_for=lambda kind, key: "22222222-2222-4222-8222-222222222222",
    )
    control = document["catalog"]["groups"][0]["controls"][0]
    assert "parts" not in control
