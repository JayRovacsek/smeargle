import json
from dataclasses import dataclass
from datetime import datetime, timezone

from smeargle.config import Settings
from smeargle.domain.clock import FrozenClock
from smeargle.domain.ids import UuidIdFactory
from smeargle.pipeline import run
from smeargle.store.run_store import RunStore


class StubIdFactory(UuidIdFactory):
    def __init__(self, run_uuid):
        self._run_uuid = run_uuid

    def run_uuid(self):
        return self._run_uuid


@dataclass
class Fixtures:
    document_path: object
    catalog_path: object


def _fixtures(tmp_path):
    document = tmp_path / "spec.txt"
    document.write_text("The system MUST encrypt data at rest.", encoding="utf-8")
    catalog = tmp_path / "vendor.json"
    catalog.write_text(
        json.dumps(
            {
                "catalog": {
                    "name": "V",
                    "securityControls": [
                        {"controlId": "1.1", "title": "Policy", "family": "Access"}
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    return Fixtures(document, catalog)


def test_run_ingestion_records_run_and_counts(tmp_path):
    fixtures = _fixtures(tmp_path)
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    result = run.run_ingestion(
        state_dir=tmp_path / "state",
        output=tmp_path / "out",
        input_paths=[fixtures.document_path],
        catalog_paths=[fixtures.catalog_path],
        settings=Settings.load(),
        clock=clock,
        id_factory=StubIdFactory("run-fixed"),
    )
    assert result.run_id == "run-fixed"
    assert result.document_count == 1
    assert result.control_count == 1
    with RunStore.open(tmp_path / "state") as store:
        row = store.get_run("run-fixed")
    assert row["fingerprint"] == result.fingerprint
    assert row["config_hash"] == result.config_hash
    assert row["status"] == "ingested"


def test_fingerprint_is_content_sensitive_and_config_hash_is_setting_sensitive(tmp_path):
    fixtures = _fixtures(tmp_path)
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    base = run.run_ingestion(
        state_dir=tmp_path / "state",
        output=tmp_path / "out",
        input_paths=[fixtures.document_path],
        catalog_paths=[fixtures.catalog_path],
        settings=Settings.load(),
        clock=clock,
        id_factory=StubIdFactory("run-a"),
    )
    other_config = run.run_ingestion(
        state_dir=tmp_path / "state",
        output=tmp_path / "out",
        input_paths=[fixtures.document_path],
        catalog_paths=[fixtures.catalog_path],
        settings=Settings.load(overrides={"mapping": {"mapped_threshold": 0.9}}),
        clock=clock,
        id_factory=StubIdFactory("run-b"),
    )
    assert other_config.fingerprint == base.fingerprint
    assert other_config.config_hash != base.config_hash

    fixtures.document_path.write_text("The system MUST log access.", encoding="utf-8")
    changed = run.run_ingestion(
        state_dir=tmp_path / "state2",
        output=tmp_path / "out2",
        input_paths=[fixtures.document_path],
        catalog_paths=[fixtures.catalog_path],
        settings=Settings.load(),
        clock=clock,
        id_factory=StubIdFactory("run-c"),
    )
    assert changed.fingerprint != base.fingerprint
