from datetime import datetime, timezone

import pytest

from smeargle.domain.clock import FrozenClock, SystemClock


def test_frozen_clock_returns_fixed_time():
    moment = datetime(2026, 1, 1, tzinfo=timezone.utc)
    clock = FrozenClock(moment)
    assert clock.now_utc() == moment
    assert clock.now_utc() is clock.now_utc()


def test_frozen_clock_requires_timezone():
    with pytest.raises(ValueError):
        FrozenClock(datetime(2026, 1, 1))


def test_system_clock_is_timezone_aware():
    assert SystemClock().now_utc().tzinfo is not None
