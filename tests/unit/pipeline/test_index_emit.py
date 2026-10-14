import json

from support.ledger import CLOCK, IDS

from smeargle.pipeline import index

_CATALOG = {
    "catalog": {
        "uuid": "11111111-1111-4111-8111-111111111111",
        "metadata": {
            "title": "Imported",
            "last-modified": "2026-01-01T00:00:00Z",
            "version": "1.0.0",
            "oscal-version": "1.2.3",
        },
        "controls": [{"id": "c-1.1", "title": "Policy"}],
    }
}


def _write_catalog(tmp_path):
    path = tmp_path / "vendor.json"
    path.write_text(json.dumps(_CATALOG), encoding="utf-8")
    return path


def test_emit_catalog_files_writes_a_missing_catalog(tmp_path):
    path = _write_catalog(tmp_path)
    output = tmp_path / "out"

    index.emit_catalog_files(
        [path], output, catalog_format="oscal", clock=CLOCK, id_factory=IDS
    )

    assert (output / "catalogs" / "vendor.json").exists()


def test_emit_catalog_files_is_idempotent(tmp_path):
    path = _write_catalog(tmp_path)
    output = tmp_path / "out"
    args = {"catalog_format": "oscal", "clock": CLOCK, "id_factory": IDS}

    index.emit_catalog_files([path], output, **args)
    first = (output / "catalogs" / "vendor.json").read_text(encoding="utf-8")
    index.emit_catalog_files([path], output, **args)

    assert (output / "catalogs" / "vendor.json").read_text(encoding="utf-8") == first
