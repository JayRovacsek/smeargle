import json

import pytest

from smeargle.catalog_adapters.registry import parse_catalog
from smeargle.errors import CatalogError


def test_missing_json_catalog_raises_catalog_error(tmp_path):
    missing = (tmp_path / "missing").with_suffix(".json")
    with pytest.raises(CatalogError):
        parse_catalog(missing)


def test_vendor_shaped_bad_input_raises_catalog_error(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"catalog": {"securityControls": "nope"}}), encoding="utf-8")
    with pytest.raises(CatalogError):
        parse_catalog(path)


def test_adapter_value_error_raises_catalog_error(tmp_path, monkeypatch):
    path = tmp_path / "vendor.json"
    path.write_text(
        json.dumps({"catalog": {"securityControls": [{"controlId": "1.1"}]}}),
        encoding="utf-8",
    )

    def _boom(document):
        raise ValueError("document does not contain a catalog object")

    monkeypatch.setattr(
        "smeargle.catalog_adapters.vendor_security_controls.parse_vendor", _boom
    )
    with pytest.raises(CatalogError):
        parse_catalog(path)
