"""Shared frozen-clock helpers for OSCAL artifact builders (spec 11)."""

from __future__ import annotations

from typing import Any

from smeargle.domain.clock import Clock

OSCAL_VERSION = "1.2.3"
CUSTOM_NS = "urn:smeargle:oscal:ns"


def oscal_timestamp(clock: Clock) -> str:
    return clock.now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")


def metadata(title: str, *, clock: Clock) -> dict[str, Any]:
    return {
        "title": title,
        "last-modified": oscal_timestamp(clock),
        "version": "1.0.0",
        "oscal-version": OSCAL_VERSION,
    }


def truncate(text: str, limit: int = 80) -> str:
    flat = " ".join(text.split())
    if not flat:
        return "requirement"
    if len(flat) <= limit:
        return flat
    return flat[: limit - 3].rstrip() + "..."
