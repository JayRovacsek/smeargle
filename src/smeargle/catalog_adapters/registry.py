"""Catalog-format detection and adapter dispatch (spec 9.2)."""

from __future__ import annotations

import json
from pathlib import Path

from smeargle.catalog_adapters.types import ParsedCatalog
from smeargle.errors import CatalogError

VENDOR_KIND = "vendor-security-controls"
OSCAL_KIND = "oscal"


def _load_json(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CatalogError(f"'{path}' is not valid JSON: {exc}") from exc


def detect_kind(path: Path, document: dict) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in {".xml", ".yaml", ".yml"}:
        return OSCAL_KIND
    catalog = document.get("catalog") if isinstance(document, dict) else None
    if isinstance(catalog, dict) and "securityControls" in catalog:
        return VENDOR_KIND
    return OSCAL_KIND


def parse_catalog(path: Path, catalog_format: str = "auto") -> tuple[str, ParsedCatalog]:
    import smeargle.catalog_adapters.oscal as oscal_adapter
    import smeargle.catalog_adapters.vendor_security_controls as vendor_adapter
    from smeargle.oscal_build import facade

    path = Path(path)
    suffix = path.suffix.lower()
    if catalog_format == "oscal":
        return OSCAL_KIND, oscal_adapter.parse_standard(facade.load_document(path))
    if catalog_format != "auto":
        raise CatalogError(f"unsupported catalog format '{catalog_format}'")

    if suffix in {".xml", ".yaml", ".yml"}:
        return OSCAL_KIND, oscal_adapter.parse_standard(facade.load_document(path))

    document = _load_json(path)
    kind = detect_kind(path, document)
    if kind == VENDOR_KIND:
        return kind, vendor_adapter.parse_vendor(document)
    return OSCAL_KIND, oscal_adapter.parse_standard(facade.load_document(path))
