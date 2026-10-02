"""Control and domain-index domain values (spec 5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True, slots=True)
class Control:
    run_id: str
    catalog_id: str
    control_id: str
    title: str
    text: str
    domain: str
    family: str
    path: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DomainIndex:
    index_id: str
    content_sha256: str
    model_id: str
    prompt_hash: str
    domains: Mapping[str, list[str]] = field(default_factory=dict)
