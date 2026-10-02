"""Standard OSCAL catalog adapter (spec 9.2)."""

from __future__ import annotations

from typing import Any

from smeargle.catalog_adapters.ids import sanitize_control_id
from smeargle.catalog_adapters.types import ParsedCatalog, ParsedControl


def _parts_text(parts: Any) -> str:
    if not isinstance(parts, list):
        return ""
    chunks: list[str] = []
    for part in parts:
        if isinstance(part, dict):
            prose = part.get("prose")
            if prose:
                chunks.append(str(prose))
            nested = _parts_text(part.get("parts", []))
            if nested:
                chunks.append(nested)
    return "\n".join(chunks)


def _parsed(control: dict, domain: str, family: str, path: tuple[str, ...]) -> ParsedControl:
    original = str(control.get("id", ""))
    return ParsedControl(
        control_id=sanitize_control_id(original),
        original_id=original,
        title=str(control.get("title", "")),
        text=_parts_text(control.get("parts", [])),
        domain=domain,
        family=family,
        path=path,
    )


def parse_standard(document: dict) -> ParsedCatalog:
    catalog = document.get("catalog")
    if not isinstance(catalog, dict):
        raise ValueError("document does not contain a catalog object")
    metadata = catalog.get("metadata", {})
    controls: list[ParsedControl] = []

    def walk_group(group: dict, path: tuple[str, ...]) -> None:
        group_id = str(group.get("id", ""))
        group_title = str(group.get("title", "")) or group_id
        current = path + (group_id,) if group_id else path
        domain = current[0] if current else ""
        for control in group.get("controls", []) or []:
            controls.append(_parsed(control, domain, group_title, current))
        for child in group.get("groups", []) or []:
            walk_group(child, current)

    for control in catalog.get("controls", []) or []:
        controls.append(_parsed(control, "", "", ()))
    for group in catalog.get("groups", []) or []:
        walk_group(group, ())

    return ParsedCatalog(
        title=str(metadata.get("title", "")) or "catalog",
        version=str(metadata.get("version", "")) or "1.0.0",
        oscal_version=str(metadata.get("oscal-version", "")) or "1.2.3",
        source_kind="oscal",
        controls=tuple(controls),
    )
