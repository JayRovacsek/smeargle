from datetime import datetime, timezone

import pytest

from smeargle.domain.clock import FrozenClock
from smeargle.domain.ids import UuidIdFactory
from smeargle.errors import InputError
from smeargle.pipeline import load
from smeargle.store.run_store import RunStore


@pytest.fixture
def store(tmp_path):
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    with RunStore.open(tmp_path, clock=clock, id_factory=UuidIdFactory()) as opened:
        opened.create_run("run-1", "fp", "cfg")
        yield opened


def test_load_persists_documents_in_canonical_order(store, tmp_path):
    first = tmp_path / "a.txt"
    first.write_text("alpha", encoding="utf-8")
    second = tmp_path / "b.md"
    second.write_text("beta", encoding="utf-8")

    documents = load.run_load(store, "run-1", [first, second])

    assert [doc.ordinal for doc in documents] == [0, 1]
    assert documents[0].content_sha256 == sorted(
        d.content_sha256 for d in documents
    )[0]
    assert len(store.list_documents("run-1")) == 2


def test_load_deduplicates_identical_content(store, tmp_path):
    first = tmp_path / "a.txt"
    first.write_text("same", encoding="utf-8")
    duplicate = tmp_path / "b.txt"
    duplicate.write_text("same", encoding="utf-8")

    documents = load.run_load(store, "run-1", [first, duplicate])

    assert len(documents) == 1
    assert len(store.list_documents("run-1")) == 1


def test_load_rejects_unsupported_input(store, tmp_path):
    bad = tmp_path / "a.xyz"
    bad.write_text("x", encoding="utf-8")
    with pytest.raises(InputError):
        load.run_load(store, "run-1", [bad])


def test_load_marks_stage_complete(store, tmp_path):
    doc = tmp_path / "a.txt"
    doc.write_text("alpha", encoding="utf-8")
    load.run_load(store, "run-1", [doc])
    assert store.get_stage("run-1", "load")["status"] == "complete"
