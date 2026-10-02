"""Vendor `securityControls` catalog adapter (spec 9.2)."""

from __future__ import annotations

from smeargle.catalog_adapters.ids import sanitize_control_id
from smeargle.catalog_adapters.types import ParsedCatalog, ParsedControl


def parse_vendor(document: dict) -> ParsedCatalog:
    catalog = document.get("catalog")
    if not isinstance(catalog, dict):
        raise ValueError("document does not contain a catalog object")
    controls: list[ParsedControl] = []
    for item in catalog.get("securityControls", []) or []:
        original = str(item.get("controlId") or item.get("id") or "")
        family = str(item.get("family", ""))
        controls.append(
            ParsedControl(
                control_id=sanitize_control_id(original),
                original_id=original,
                title=str(item.get("title", "")),
                text=str(item.get("description", "")),
                domain=family,
                family=family,
                path=(family,) if family else (),
            )
        )
    return ParsedCatalog(
        title=str(catalog.get("name") or catalog.get("title") or ""),
        version=str(catalog.get("version", "")) or "1.0.0",
        oscal_version="1.2.3",
        source_kind="vendor-security-controls",
        controls=tuple(controls),
    )
