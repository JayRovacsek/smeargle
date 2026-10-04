"""Run-scoped domain values and the frozen assembly ledger (spec 5, 11)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from smeargle.domain.controls import Control
from smeargle.domain.requirements import Requirement


@dataclass(frozen=True, slots=True)
class RunFingerprint:
    fingerprint: str
    config_hash: str


@dataclass(frozen=True, slots=True)
class RunConfig:
    values: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True, eq=False)
class Ledger:
    run_id: str
    documents: tuple[Mapping[str, Any], ...]
    requirements: tuple[Requirement, ...]
    catalogs: tuple[Mapping[str, Any], ...]
    controls: tuple[Control, ...]
    pairs: tuple[Mapping[str, Any], ...]
    mappings: tuple[Mapping[str, Any], ...]
    evidence: tuple[Mapping[str, Any], ...]
    domains: Mapping[str, str] = field(default_factory=dict)
    failures: tuple[Mapping[str, Any], ...] = ()
    run: Mapping[str, Any] = field(default_factory=dict)

    def __hash__(self) -> int:
        return hash(self.run_id)
