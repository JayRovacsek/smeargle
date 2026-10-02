"""Document domain value (spec 5)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True, slots=True)
class Document:
    run_id: str
    doc_id: str
    ordinal: int
    path: str
    uri: str
    external_id: Optional[str]
    media_type: str
    content_sha256: str
    size_bytes: int
    text: str
