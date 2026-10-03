import threading

import pytest

from smeargle.pipeline.executor import EvidenceBus, Writer, persist_sorted
from smeargle.store.run_store import RunStore


class Boom(BaseException):
    pass


def _run_with_timeout(fn, timeout=5.0):
    outcome = {}

    def target():
        try:
            outcome["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - captured for the calling thread
            outcome["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise AssertionError("operation did not complete")
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


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


def test_call_and_submit_after_stop_raise_runtime_error(tmp_path):
    writer = _writer(tmp_path)
    writer.stop()

    with pytest.raises(RuntimeError, match="stopped"):
        _run_with_timeout(lambda: writer.call(lambda store: None))

    with pytest.raises(RuntimeError, match="stopped"):
        _run_with_timeout(lambda: writer.submit(lambda store: None).result())


def test_call_propagates_exception_and_writer_stays_usable(tmp_path):
    writer = _writer(tmp_path)
    try:
        def boom(store):
            raise ValueError("boom")


        with pytest.raises(ValueError, match="boom"):
            writer.call(boom)
        assert writer.call(lambda store: "still works") == "still works"
    finally:
        writer.stop()


def test_fatal_writer_exit_drains_queued_futures(tmp_path, monkeypatch):
    close_gate = threading.Event()
    entered_close = threading.Event()

    class FailingCloseStore:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            entered_close.set()
            close_gate.wait(5)
            raise Boom()

    monkeypatch.setattr(RunStore, "open", classmethod(lambda cls, *a, **k: FailingCloseStore()))

    writer = Writer(tmp_path)
    writer.start()

    stopper = threading.Thread(target=writer.stop)
    stopper.start()
    assert entered_close.wait(5)

    future = writer.submit(lambda store: "never processed")
    close_gate.set()
    stopper.join(5)

    with pytest.raises(Boom):
        future.result(timeout=5)


def test_submit_before_start_returns_failed_future(tmp_path):
    writer = Writer(tmp_path)
    with pytest.raises(RuntimeError, match="not been started"):
        _run_with_timeout(lambda: writer.submit(lambda store: None).result())


def test_persist_sorted_rolls_back_batch_on_base_exception(tmp_path):
    writer = _writer(tmp_path)
    try:
        items = [(1, "a"), (2, "b"), (3, "c"), (4, "d")]

        def apply(store, item):
            if item == "d":
                raise Boom()
            store.create_run(item, "fp", "ch")

        with pytest.raises(Boom):
            persist_sorted(writer, items, apply, batch_size=2)

        assert writer.call(lambda store: store.get_run("a")) is not None
        assert writer.call(lambda store: store.get_run("b")) is not None
        assert writer.call(lambda store: store.get_run("c")) is None
        assert writer.call(lambda store: store.get_run("d")) is None
    finally:
        writer.stop()
