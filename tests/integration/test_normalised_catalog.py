from support.schemas import validate_against_schema

from smeargle.catalog_adapters import normalise, vendor_security_controls
from smeargle.domain.ids import UuidIdFactory

VENDOR = {
    "catalog": {
        "name": "Vendor Controls",
        "securityControls": [
            {
                "controlId": "1.1",
                "title": "Policy",
                "family": "Access Control",
                "description": "Establish a policy.",
            },
            {
                "controlId": "2.1",
                "title": "Review",
                "family": "Audit",
                "description": "Review logs.",
            },
            {
                "controlId": "2.2",
                "title": "Review II",
                "family": "Audit",
            },
        ],
    }
}


def test_normalised_catalog_validates_against_vendored_schema():
    parsed = vendor_security_controls.parse_vendor(VENDOR)
    document = normalise.build_normalised_catalog(
        catalog_id="cat-1",
        parsed=parsed,
        source_uri="file:///vendor.json",
        last_modified="2026-01-01T00:00:00Z",
        uuid_for=UuidIdFactory().uuid_for,
    )
    validate_against_schema("catalog", document)
    assert {group["title"] for group in document["catalog"]["groups"]} == {
        "Access Control",
        "Audit",
    }
