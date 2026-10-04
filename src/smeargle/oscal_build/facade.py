"""The only module that imports `oscal`; a thin, typed boundary (spec 4, 16)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from oscal import OSCAL, Catalog, Profile
from oscal import Mapping as OscalMapping

from smeargle.errors import CatalogError

_MODELS = {
    "catalog": Catalog,
    "profile": Profile,
    "mapping-collection": OscalMapping,
}


def configure_support_file(path: Path) -> None:
    from oscal.oscal_support import configure_support

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    configure_support(support_file=str(path))


def _summary(instance: Any) -> str:
    status = getattr(instance, "validation_status", {}) or {}
    failed = ", ".join(name for name, ok in status.items() if ok is False)
    errors = getattr(instance, "validation_errors", []) or []
    detail = failed or "unknown phase"
    if errors:
        first = errors[0]
        detail = f"{detail}: {first.get('error-type')} at {first.get('location')}"
    return detail


def _safe_loads(cls: Any, content: Any, *, href: str | None = None) -> Any:
    try:
        return cls.loads(content, href=href)
    except CatalogError:
        raise
    except Exception as exc:
        raise CatalogError(f"could not parse OSCAL content: {exc}") from exc


def validate(model: str, document: Mapping[str, Any]) -> None:
    cls = _MODELS.get(model)
    if cls is None:
        raise CatalogError(f"unsupported OSCAL model '{model}'")
    instance = _safe_loads(cls, dict(document))
    if not instance.is_valid:
        raise CatalogError(f"invalid OSCAL {model}: {_summary(instance)}")


def load_document(path: Path) -> dict[str, Any]:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CatalogError(f"could not read OSCAL document '{path}': {exc}") from exc
    instance = _safe_loads(OSCAL, text, href=str(path))
    if not instance.is_valid:
        raise CatalogError(f"'{path}' is not valid OSCAL: {_summary(instance)}")
    return json.loads(instance.json)


def serialise_json(model: str, document: Mapping[str, Any]) -> str:
    cls = _MODELS.get(model)
    if cls is None:
        raise CatalogError(f"unsupported OSCAL model '{model}'")
    instance = _safe_loads(cls, dict(document))
    if not instance.is_valid:
        raise CatalogError(f"cannot serialise invalid OSCAL {model}: {_summary(instance)}")
    return instance.dumps(format="json", pretty_print=True)


def write_document(path: Path, model: str, document: Mapping[str, Any]) -> None:
    """Validate then write an OSCAL model as pretty JSON (spec 11)."""
    text = serialise_json(model, document)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
