import threading

import pytest

from smeargle.pipeline.executor import EvidenceBus, Writer, persist_sorted


def _writer(tmp_path):
    writer = Writer(tmp_path)
    writer.start()
    writer.call(lambda store: store.create_run("run-1", "fp", "ch"))
    return writer


def test_writer_runs_calls_on_one_thread_and_surfaces_open_failure(tmp_path):
    writer = _writer(tmp_path)
    try:
        names = set()
        results = []

        def op(store):
            names.add(threading.current_thread().name)
            return "ok"

        threads = [threading.Thread(target=lambda: results.append(writer.call(op))) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert results == ["ok", "ok", "ok", "ok"]
        assert names == {"smeargle-writer"}
    finally:
        writer.stop()

    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    failing = Writer(blocked)
    with pytest.raises(OSError):
        failing.start()
    with pytest.raises(OSError):
        failing.call(lambda store: None)


def test_evidence_bus_persists_pending_then_response(tmp_path):
    writer = _writer(tmp_path)
    try:
        bus = EvidenceBus(writer, "run-1")
        bus.request(
            stage="extract", item_ref="doc:doc-1", call_type="llm_extract", request={"a": 1}
        )
        assert not writer.call(
            lambda store: store.has_evidence_response(
                "run-1", "extract", "doc:doc-1", "llm_extract"
            )
        )
        bus.response(
            stage="extract", item_ref="doc:doc-1", call_type="llm_extract",
            request={"a": 1}, response={"b": 2}, http_status=200,
        )
        assert writer.call(
            lambda store: store.has_evidence_response(
                "run-1", "extract", "doc:doc-1", "llm_extract"
            )
        )
    finally:
        writer.stop()


def test_evidence_bus_records_attempts(tmp_path):
    writer = _writer(tmp_path)
    try:
        bus = EvidenceBus(writer, "run-1")
        bus.attempt(
            stage="verify", item_ref="pair:x", call_type="jev_noul", attempt_no=1,
            http_status=503, error_class=None, error=None, duration_ms=12,
        )
        attempts = writer.call(lambda store: store.counts("run-1"))["attempts"]
        assert attempts == 1
    finally:
        writer.stop()


def test_persist_sorted_applies_in_key_order(tmp_path):
    writer = _writer(tmp_path)
    try:
        applied = []
        persist_sorted(
            writer,
            [("c", 3), ("a", 1), ("b", 2)],
            lambda store, item: applied.append(item),
            batch_size=2,
        )
        assert applied == [1, 2, 3]
    finally:
        writer.stop()
