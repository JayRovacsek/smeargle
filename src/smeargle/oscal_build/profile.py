"""Build the §11.2 tailoring profile from the ledger (pure)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from smeargle.domain.clock import Clock
from smeargle.domain.ids import IdFactory
from smeargle.domain.run import Ledger
from smeargle.oscal_build.common import metadata


def _resource(id_factory: IdFactory, run_id: str, name: str) -> dict[str, Any]:
    return {
        "uuid": id_factory.uuid_for("artifact-resource", f"{run_id}:{name}"),
        "title": name,
        "rlinks": [{"href": name}],
    }


def build(ledger: Ledger, *, mapping_present: bool, clock: Clock,
          id_factory: IdFactory) -> dict[str, Any]:
    catalogs = sorted(ledger.catalogs, key=lambda c: (c["content_sha256"], c["catalog_id"]))
    imports = [
        {"href": f"catalogs/{Path(catalog['path']).stem}.json", "include-all": {}}
        for catalog in catalogs
    ]

    requirements_resource = id_factory.uuid_for(
        "artifact-resource", f"{ledger.run_id}:requirements-catalog.json"
    )
    resources = [
        _resource(id_factory, ledger.run_id, "requirements-catalog.json"),
        _resource(id_factory, ledger.run_id, "rationale.json"),
    ]
    if mapping_present:
        resources.append(_resource(id_factory, ledger.run_id, "mapping-collection.json"))

    by_control: dict[str, list[Mapping[str, Any]]] = {}
    for mapping in ledger.mappings:
        by_control.setdefault(mapping["control_id"], []).append(mapping)

    alters: list[dict[str, Any]] = []
    for control_id in sorted(by_control):
        rows = sorted(by_control[control_id], key=lambda m: (m["req_id"], m["control_id"]))
        adds = [
            {
                "props": [
                    {"name": "mapped-requirement", "value": row["req_id"]},
                    {"name": "confidence-category", "value": row["confidence_category"],
                     "group": row["req_id"]},
                ],
                "links": [
                    {"rel": "reference", "href": f"#{requirements_resource}",
                     "resource-fragment": row["req_id"]}
                ],
            }
            for row in rows
        ]
        alters.append({"control-id": control_id, "adds": adds})

    document: dict[str, Any] = {
        "uuid": id_factory.uuid_for("profile", ledger.run_id),
        "metadata": metadata(f"smeargle profile ({ledger.run_id})", clock=clock),
        "imports": imports,
        "back-matter": {"resources": resources},
    }
    if alters:
        document["modify"] = {"alters": alters}
    return {"profile": document}
