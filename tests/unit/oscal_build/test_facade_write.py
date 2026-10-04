import json
from datetime import datetime, timezone

import pytest

from smeargle.domain.clock import FrozenClock
from smeargle.oscal_build import common, facade

GOOD = {
    "catalog": {
        "uuid": "11111111-1111-4111-8111-111111111111",
        "metadata": {
            "title": "t", "last-modified": "2026-01-01T00:00:00Z",
            "version": "1.0.0", "oscal-version": "1.2.3",
        },
    }
}


def test_write_document_validates_and_writes_meta_helpers(tmp_path):
    facade.configure_support_file(tmp_path / "support.db")
    target = tmp_path / "out" / "catalog.json"
    facade.write_document(target, "catalog", GOOD)
    assert json.loads(target.read_text(encoding="utf-8"))["catalog"]["uuid"] == (
        "11111111-1111-4111-8111-111111111111"
    )
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert common.metadata("t", clock=clock)["last-modified"] == "2026-01-01T00:00:00Z"
    assert common.truncate("a\nb\tc") == "a b c"


def test_write_document_rejects_invalid_and_leaves_no_file(tmp_path):
    from smeargle.errors import CatalogError

    facade.configure_support_file(tmp_path / "support.db")
    target = tmp_path / "bad.json"
    with pytest.raises(CatalogError):
        facade.write_document(target, "catalog", {"catalog": {"uuid": "nope"}})
    assert not target.exists()
