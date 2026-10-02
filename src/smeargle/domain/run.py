"""Run-scoped domain values (spec 5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class RunFingerprint:
    fingerprint: str
    config_hash: str


@dataclass(frozen=True, slots=True)
class RunConfig:
    values: Mapping[str, Any] = field(default_factory=dict)
