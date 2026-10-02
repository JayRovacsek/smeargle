"""Offline OSCAL JSON Schema validation via jsonschema-rs (spec 14)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import jsonschema_rs

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas" / "oscal-1.2.3"

SCHEMA_FILES = {
    "catalog": "oscal_catalog_schema.json",
    "profile": "oscal_profile_schema.json",
    "mapping-collection": "oscal_mapping_schema.json",
}


@lru_cache(maxsize=None)
def _validator(model: str) -> jsonschema_rs.Draft7Validator:
    schema = json.loads((SCHEMA_DIR / SCHEMA_FILES[model]).read_text(encoding="utf-8"))
    return jsonschema_rs.Draft7Validator(schema)


def validate_against_schema(model: str, document: Mapping[str, Any]) -> None:
    """Raise jsonschema_rs.ValidationError when document fails the vendored schema."""
    _validator(model).validate(dict(document))
