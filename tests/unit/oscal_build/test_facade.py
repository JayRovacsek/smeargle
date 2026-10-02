import json

import pytest

from smeargle.errors import CatalogError
from smeargle.oscal_build import facade


def _write_catalog(tmp_path, controls):
    document = {
        "catalog": {
            "uuid": "11111111-1111-4111-8111-111111111111",
            "metadata": {
                "title": "Test Catalog",
                "last-modified": "2026-01-01T00:00:00Z",
                "version": "1.0.0",
                "oscal-version": "1.2.3",
            },
            "controls": controls,
        }
    }
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path, document


@pytest.fixture(autouse=True)
def _support(tmp_path_factory):
    support = tmp_path_factory.mktemp("support") / "oscal_support.db"
    facade.configure_support_file(support)


def test_load_document_returns_plain_dict(tmp_path):
    path, document = _write_catalog(tmp_path, [{"id": "ac-1", "title": "Policy"}])
    assert facade.load_document(path) == document


def test_validate_accepts_valid_catalog():
    document = {
        "catalog": {
            "uuid": "11111111-1111-4111-8111-111111111111",
            "metadata": {
                "title": "T",
                "last-modified": "2026-01-01T00:00:00Z",
                "version": "1.0.0",
                "oscal-version": "1.2.3",
            },
        }
    }
    facade.validate("catalog", document)


def test_validate_rejects_invalid_catalog():
    document = {
        "catalog": {
            "uuid": "not-a-uuid",
            "metadata": {"title": "T"},
        }
    }
    with pytest.raises(CatalogError):
        facade.validate("catalog", document)


def test_serialise_json_round_trips():
    document = {
        "catalog": {
            "uuid": "11111111-1111-4111-8111-111111111111",
            "metadata": {
                "title": "T",
                "last-modified": "2026-01-01T00:00:00Z",
                "version": "1.0.0",
                "oscal-version": "1.2.3",
            },
        }
    }
    text = facade.serialise_json("catalog", document)
    assert json.loads(text)["catalog"]["metadata"]["oscal-version"] == "1.2.3"


def test_validate_wraps_raw_oscal_errors():
    document = {"catalog": {"unserialisable": object()}}
    with pytest.raises(CatalogError):
        facade.validate("catalog", document)


def test_serialise_wraps_raw_oscal_errors():
    document = {"catalog": {"unserialisable": object()}}
    with pytest.raises(CatalogError):
        facade.serialise_json("catalog", document)


def test_load_document_wraps_read_errors(tmp_path):
    with pytest.raises(CatalogError):
        facade.load_document(tmp_path / "missing.json")
