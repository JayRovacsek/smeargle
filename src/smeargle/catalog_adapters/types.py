"""Neutral intermediate values shared by catalog adapters (spec 9.2)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ParsedControl:
    control_id: str
    original_id: str
    title: str
    text: str
    domain: str
    family: str
    path: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ParsedCatalog:
    title: str
    version: str
    oscal_version: str
    source_kind: str
    controls: tuple[ParsedControl, ...]
