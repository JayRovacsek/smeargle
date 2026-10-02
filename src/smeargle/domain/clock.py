"""Injected clocks for deterministic timestamps (spec 5)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    def now_utc(self) -> datetime: ...


class SystemClock:
    def now_utc(self) -> datetime:
        return datetime.now(timezone.utc)


class FrozenClock:
    def __init__(self, moment: datetime) -> None:
        if moment.tzinfo is None:
            raise ValueError("FrozenClock requires a timezone-aware datetime")
        self._moment = moment.astimezone(timezone.utc)

    def now_utc(self) -> datetime:
        return self._moment
