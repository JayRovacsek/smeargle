"""Single-writer DB executor and marshalling evidence bus (spec 3, 7)."""

from __future__ import annotations

import queue
import threading
from concurrent.futures import Future
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from smeargle.domain.clock import Clock
from smeargle.domain.ids import IdFactory
from smeargle.store.run_store import RunStore

BATCH_SIZE = 25


class Writer:
    def __init__(
        self,
        state_dir: Path,
        *,
        clock: Optional[Clock] = None,
        id_factory: Optional[IdFactory] = None,
    ) -> None:
        self._state_dir = Path(state_dir)
        self._clock = clock
        self._id_factory = id_factory
        self._queue: "queue.Queue[Optional[tuple]]" = queue.Queue()
        self._ready = threading.Event()
        self._error: Optional[BaseException] = None
        self._thread = threading.Thread(target=self._run, name="smeargle-writer", daemon=True)

    def start(self) -> None:
        self._thread.start()
        self._ready.wait()
        if self._error is not None:
            raise self._error

    def _run(self) -> None:
        try:
            with RunStore.open(
                self._state_dir, clock=self._clock, id_factory=self._id_factory
            ) as store:
                self._ready.set()
                while True:
                    item = self._queue.get()
                    if item is None:
                        break
                    fn, future = item
                    if future.set_running_or_notify_cancel():
                        try:
                            future.set_result(fn(store))
                        except BaseException as exc:  # noqa: BLE001 - propagated to caller
                            future.set_exception(exc)
        except BaseException as exc:  # noqa: BLE001 - store open/close failure is fatal
            self._error = exc
        finally:
            self._ready.set()

    def submit(self, fn: Callable[[RunStore], Any]) -> "Future[Any]":
        future: "Future[Any]" = Future()
        if self._error is not None:
            future.set_exception(self._error)
            return future
        self._queue.put((fn, future))
        return future

    def call(self, fn: Callable[[RunStore], Any]) -> Any:
        return self.submit(fn).result()

    def stop(self) -> None:
        self._queue.put(None)
        self._thread.join()


class EvidenceBus:
    def __init__(self, writer: Writer, run_id: str) -> None:
        self._writer = writer
        self._run_id = run_id

    def request(
        self, *, stage: str, item_ref: str, call_type: str, request: Any,
        prompt_hash: Optional[str] = None,
    ) -> None:
        self._writer.call(
            lambda store: store.record_evidence(
                run_id=self._run_id, stage=stage, item_ref=item_ref, call_type=call_type,
                request=request, prompt_hash=prompt_hash,
            )
        )

    def response(
        self, *, stage: str, item_ref: str, call_type: str, request: Any, response: Any,
        http_status: Optional[int] = None, attempt_no: Optional[int] = None,
        prompt_hash: Optional[str] = None,
    ) -> None:
        self._writer.call(
            lambda store: store.record_evidence(
                run_id=self._run_id, stage=stage, item_ref=item_ref, call_type=call_type,
                request=request, response=response, http_status=http_status,
                attempt_no=attempt_no, prompt_hash=prompt_hash,
            )
        )

    def attempt(
        self, *, stage: str, item_ref: str, call_type: str, attempt_no: int,
        http_status: Optional[int] = None, error_class: Optional[str] = None,
        error: Optional[str] = None, duration_ms: Optional[int] = None,
    ) -> None:
        self._writer.call(
            lambda store: store.record_attempt(
                run_id=self._run_id, stage=stage, item_ref=item_ref, call_type=call_type,
                attempt_no=attempt_no, http_status=http_status, error_class=error_class,
                error=error, duration_ms=duration_ms,
            )
        )


def persist_sorted(
    writer: Writer,
    items: Iterable[tuple[Any, Any]],
    apply: Callable[[RunStore, Any], None],
    *,
    batch_size: int = BATCH_SIZE,
) -> None:
    ordered = sorted(items, key=lambda pair: pair[0])

    def op(store: RunStore) -> None:
        for start in range(0, len(ordered), batch_size):
            with store.transaction():
                for _key, item in ordered[start : start + batch_size]:
                    apply(store, item)

    writer.call(op)
