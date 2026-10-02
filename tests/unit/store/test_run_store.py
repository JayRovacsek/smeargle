from datetime import datetime, timezone

import pytest

from smeargle.domain.clock import FrozenClock
from smeargle.domain.documents import Document
from smeargle.domain.ids import UuidIdFactory
from smeargle.store import run_store as rs


@pytest.fixture
def store(tmp_path):
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    with rs.RunStore.open(tmp_path, clock=clock, id_factory=UuidIdFactory()) as opened:
        yield opened


def test_create_and_read_run(store):
    store.create_run("run-1", "fp", "cfg")
    row = store.get_run("run-1")
    assert row["fingerprint"] == "fp"
    assert row["status"] == "started"
    assert store.find_runs_by_fingerprint("fp")[0]["run_id"] == "run-1"


def test_set_run_status_marks_finished_at(store):
    store.create_run("run-1", "fp", "cfg")
    store.set_run_status("run-1", "ingested", finished=True)
    row = store.get_run("run-1")
    assert row["status"] == "ingested"
    assert row["finished_at"] is not None


def test_stage_lifecycle(store):
    store.create_run("run-1", "fp", "cfg")
    store.start_stage("run-1", "load")
    assert store.get_stage("run-1", "load")["status"] == "running"
    store.complete_stage("run-1", "load")
    assert store.get_stage("run-1", "load")["status"] == "complete"
    store.start_stage("run-1", "load")
    assert store.get_stage("run-1", "load")["status"] == "running"


def test_add_and_list_documents(store):
    store.create_run("run-1", "fp", "cfg")
    doc = Document(
        run_id="run-1",
        doc_id="d1",
        ordinal=0,
        path="/x/a.txt",
        uri="file:///x/a.txt",
        external_id=None,
        media_type="text/plain",
        content_sha256="d1",
        size_bytes=10,
        text="hello",
    )
    store.add_document(doc)
    assert store.document_content_exists("run-1", "d1")
    assert not store.document_content_exists("run-1", "other")
    rows = store.list_documents("run-1")
    assert [row["doc_id"] for row in rows] == ["d1"]
    assert rows[0]["path"] == "/x/a.txt"


def test_document_content_is_unique_per_run(store):
    store.create_run("run-1", "fp", "cfg")
    doc = Document("run-1", "d1", 0, "a", "u", None, "text/plain", "d1", 1, "x")
    store.add_document(doc)
    duplicate = Document("run-1", "d1", 1, "b", "u2", None, "text/plain", "d1", 1, "x")
    with pytest.raises(Exception):
        store.add_document(duplicate)
