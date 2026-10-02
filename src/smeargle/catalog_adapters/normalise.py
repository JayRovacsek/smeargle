"""Build a normalised OSCAL catalog as a plain dict (spec 9.2, 11.2)."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Callable

from smeargle.catalog_adapters.ids import sanitize_control_id
from smeargle.catalog_adapters.types import ParsedCatalog, ParsedControl


def _control_dict(control: ParsedControl, source_uri: str) -> dict[str, Any]:
    props: list[dict[str, str]] = [
        {"name": "original-id", "value": control.original_id},
        {"name": "source-document", "value": source_uri},
    ]
    control_dict: dict[str, Any] = {
        "id": control.control_id,
        "title": control.title or control.control_id,
        "props": props,
    }
    if control.text:
        control_dict["parts"] = [
            {
                "id": f"{control.control_id}-statement",
                "name": "statement",
                "prose": control.text,
            }
        ]
    return control_dict


def build_normalised_catalog(
    *,
    catalog_id: str,
    parsed: ParsedCatalog,
    source_uri: str,
    last_modified: str,
    uuid_for: Callable[[str, str], str],
) -> dict[str, Any]:
    groups: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    for control in parsed.controls:
        label = control.family or control.domain or "controls"
        group_id = sanitize_control_id(label)
        if group_id not in groups:
            groups[group_id] = {"id": group_id, "title": label, "controls": []}
        groups[group_id]["controls"].append(_control_dict(control, source_uri))

    catalog: dict[str, Any] = {
        "uuid": uuid_for("catalog", catalog_id),
        "metadata": {
            "title": parsed.title or "catalog",
            "last-modified": last_modified,
            "version": parsed.version or "1.0.0",
            "oscal-version": "1.2.3",
        },
    }
    if groups:
        catalog["groups"] = list(groups.values())
    return {"catalog": catalog}
