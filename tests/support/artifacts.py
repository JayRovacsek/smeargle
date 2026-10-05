"""Write-and-validate helpers for emitted artifacts (spec 11.6)."""

from __future__ import annotations

import json
from pathlib import Path

from smeargle.oscal_build import facade
from support.schemas import validate_against_schema

MODELS = {
    "requirements-catalog.json": "catalog",
    "profile.json": "profile",
    "mapping-collection.json": "mapping-collection",
}


def validate_output(output: Path) -> list[str]:
    names: list[str] = []
    for name, model in MODELS.items():
        path = Path(output) / name
        if not path.exists():
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        facade.validate(model, document)
        validate_against_schema(model, document)
        names.append(name)
    rationale = Path(output) / "rationale.json"
    if rationale.exists():
        json.loads(rationale.read_text(encoding="utf-8"))
        names.append("rationale.json")
    return names
