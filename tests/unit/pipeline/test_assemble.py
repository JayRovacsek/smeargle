import json
import zlib

import pytest
from support.ledger import CLOCK, IDS

from smeargle.domain.controls import Control
from smeargle.domain.mapping import CandidatePair, MappingRecord, Relationship
from smeargle.domain.requirements import Keyword, Requirement
from smeargle.errors import IntegrityError
from smeargle.pipeline import assemble
from smeargle.store.run_store import CatalogRow, RunStore


def _settings(tmp_path):
    from smeargle.config import Settings

    settings = Settings.load()
    settings.state_dir = tmp_path / "state"
    settings.output = tmp_path / "out"
    settings.llm.model = "test-model"
    return settings


def _seed(store):
    store.create_run("run-1", "fp", "ch")
    store.add_document(
        type("D", (), {
            "run_id": "run-1", "doc_id": "d1", "ordinal": 0, "path": "/in/spec.txt",
            "uri": "file:///in/spec.txt", "external_id": None, "media_type": "text/plain",
            "content_sha256": "a" * 64, "size_bytes": 3, "text": "x",
        })()
    )
    store.add_requirement_if_absent(
        Requirement("run-1", "req-1", "d1", 0, "MUST x", "MUST x", Keyword.MUST,
                    "proposed", "passed", 0.9, "MUST", "nominated")
    )
    store.add_catalog(CatalogRow(
        run_id="run-1", catalog_id="cat-1", ordinal=0, uri="file:///in/vendor.json",
        path="/in/vendor.json", external_id=None, content_sha256="b" * 64,
        oscal_version="1.2.3", status="loaded",
    ))
    store.add_control(Control("run-1", "cat-1", "c-1.1", "Policy", "text", "access", "Access"))
    store.add_candidate_pair(
        CandidatePair("run-1", "pair-1", "req-1", "cat-1", "c-1.1", "passed", 0.9),
        mapped_threshold=0.5,
    )
    store.set_pair_classify(
        "run-1", "pair-1", classify_status="done", relation="subset-of",
        confidence_percentage=0.85, confidence_category="high",
    )
    store.add_mapping(
        MappingRecord("run-1", "req-1", "cat-1", "c-1.1", Relationship.SUBSET_OF, 0.85, "high")
    )
    store.record_evidence(
        run_id="run-1", stage="classify", item_ref="pair:pair-1", call_type="jev_choice",
        request={"api_key": "secret"}, response={"answers": []}, attempt_no=1,
    )


def test_run_assemble_reads_ledger_writes_layout_and_exports_evidence(tmp_path):
    settings = _settings(tmp_path)
    with RunStore.open(settings.state_dir, clock=CLOCK, id_factory=IDS) as store:
        _seed(store)
        result = assemble.run_assemble(
            store, "run-1", settings.output, clock=CLOCK, id_factory=IDS,
            settings=settings, config={"llm": {"model": "test-model"}},
        )
    assert result.gaps == 0
    assert (settings.output / "requirements-catalog.json").exists()
    assert (settings.output / "rationale.json").exists()
    assert list((settings.output / "evidence").glob("*.json"))


def test_run_assemble_partial_stops_at_the_requirements_catalog(tmp_path):
    settings = _settings(tmp_path)
    with RunStore.open(settings.state_dir, clock=CLOCK, id_factory=IDS) as store:
        _seed(store)
        result = assemble.run_assemble(
            store, "run-1", settings.output, clock=CLOCK, id_factory=IDS,
            settings=settings, config={}, partial=True,
        )
    assert result.profile is None
    assert (settings.output / "requirements-catalog.json").exists()
    assert not (settings.output / "rationale.json").exists()


def test_run_assemble_counts_per_item_failure_attempts_as_gaps(tmp_path):
    settings = _settings(tmp_path)
    with RunStore.open(settings.state_dir, clock=CLOCK, id_factory=IDS) as store:
        _seed(store)
        store.record_attempt(
            run_id="run-1", stage="verify", item_ref="pair-1", call_type="jev_noul",
            attempt_no=0, error_class="per_item_failure", error="boom",
        )
        result = assemble.run_assemble(
            store, "run-1", settings.output, clock=CLOCK, id_factory=IDS,
            settings=settings, config={},
        )
    assert result.failures == 1
    assert result.gaps == 1


def test_run_assemble_checks_integrity_before_writing_any_assemble_artifact(tmp_path, monkeypatch):
    # This covers the real §3 write-ordering invariant: assemble-owned artifacts and
    # evidence (requirements-catalog/profile/mapping-collection/rationale + evidence/) are
    # written only after the gate passes. Stage 2 catalogs are written by `ingest_catalogs`
    # earlier and are outside this invariant.
    settings = _settings(tmp_path)
    with RunStore.open(settings.state_dir, clock=CLOCK, id_factory=IDS) as store:
        _seed(store)
        checked: list[str] = []

        def boom(assembly, ledger, *, partial=False, output=None):
            checked.append("gate")
            raise IntegrityError("broken output")

        monkeypatch.setattr(assemble.emit, "integrity_gate", boom)
        with pytest.raises(IntegrityError):
            assemble.run_assemble(
                store, "run-1", settings.output, clock=CLOCK, id_factory=IDS,
                settings=settings, config={},
            )
    assert checked == ["gate"]
    assert not (settings.output / "requirements-catalog.json").exists()
    assert not (settings.output / "rationale.json").exists()
    assert not (settings.output / "evidence").exists()


def test_decompress_round_trips_compressed_evidence():
    blob = zlib.compress(json.dumps({"answers": [{"answer": "yes"}]}).encode())
    decoded = assemble._decompress(
        {"request_json": zlib.compress(b"{}"), "response_json": blob}
    )
    assert decoded["response"] == {"answers": [{"answer": "yes"}]}
    assert decoded["request"] == {}
