import json
from datetime import datetime, timezone

import pytest
from support.schemas import validate_against_schema

from smeargle.domain.clock import FrozenClock
from smeargle.domain.ids import UuidIdFactory
from smeargle.errors import CatalogError
from smeargle.pipeline import index
from smeargle.store.run_store import RunStore


@pytest.fixture
def store(tmp_path):
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    with RunStore.open(tmp_path, clock=clock, id_factory=UuidIdFactory()) as opened:
        opened.create_run("run-1", "fp", "cfg")
        yield opened


def _vendor(path, controls):
    path.write_text(
        json.dumps({"catalog": {"name": "V", "securityControls": controls}}),
        encoding="utf-8",
    )
    return path


def test_ingest_persists_catalogs_and_controls_and_emits(store, tmp_path):
    catalog = _vendor(
        tmp_path / "vendor.json",
        [{"controlId": "1.1", "title": "Policy", "family": "Access", "description": "d"}],
    )
    output = tmp_path / "out"
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    result = index.ingest_catalogs(
        store,
        "run-1",
        [catalog],
        output,
        catalog_format="auto",
        clock=clock,
        id_factory=UuidIdFactory(),
    )
    assert len(result) == 1
    assert store.counts("run-1")["catalogs"] == 1
    assert store.counts("run-1")["controls"] == 1
    emitted = json.loads((output / "catalogs" / "vendor.json").read_text(encoding="utf-8"))
    validate_against_schema("catalog", emitted)


def test_ingest_fails_fast_on_duplicate_control_ids(store, tmp_path):
    one = _vendor(tmp_path / "one.json", [{"controlId": "1.1", "title": "A"}])
    two = _vendor(tmp_path / "two.json", [{"controlId": "1.1", "title": "B"}])
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    with pytest.raises(CatalogError) as excinfo:
        index.ingest_catalogs(
            store,
            "run-1",
            [one, two],
            tmp_path / "out",
            catalog_format="auto",
            clock=clock,
            id_factory=UuidIdFactory(),
        )
    message = str(excinfo.value)
    assert "duplicate control id '1.1'" in message
    assert "sanitised 'c-1.1'" in message
    assert "one.json" in message
    assert "two.json" in message


def test_forced_oscal_rejects_vendor_shape(store, tmp_path):
    vendor = _vendor(tmp_path / "vendor.json", [{"controlId": "1.1", "title": "A"}])
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    with pytest.raises(CatalogError):
        index.ingest_catalogs(
            store,
            "run-1",
            [vendor],
            tmp_path / "out",
            catalog_format="oscal",
            clock=clock,
            id_factory=UuidIdFactory(),
        )


def test_ingest_fails_fast_on_stem_collision(store, tmp_path):
    one = _vendor(tmp_path / "same.json", [{"controlId": "1.1", "title": "A"}])
    two = tmp_path / "same.yaml"
    two.write_text("catalog:\n  metadata:\n    title: T\n", encoding="utf-8")
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    with pytest.raises(CatalogError, match="stem"):
        index.ingest_catalogs(
            store,
            "run-1",
            [one, two],
            tmp_path / "out",
            catalog_format="auto",
            clock=clock,
            id_factory=UuidIdFactory(),
        )
