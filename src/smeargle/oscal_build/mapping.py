"""Build the §11.3 mapping collection from the ledger (pure)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional

from smeargle.domain.clock import Clock
from smeargle.domain.ids import IdFactory
from smeargle.domain.mapping import POSITIVE_RELATIONSHIPS
from smeargle.domain.run import Ledger
from smeargle.errors import IntegrityError
from smeargle.oscal_build.common import metadata


def _map_entry(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "uuid": row["map_uuid"],
        "relationship": row["relation"],
        "confidence-score": {"percentage": row["confidence_percentage"]},
        "sources": [{"type": "control", "id-ref": row["req_id"]}],
        "targets": [{"type": "control", "id-ref": row["control_id"]}],
    }


def _description(ledger: Ledger, mappings: list[dict[str, Any]]) -> str:
    relations = sum(len(entry["maps"]) for entry in mappings)
    controls = {mapping["control_id"] for mapping in ledger.mappings}
    requirements = {mapping["req_id"] for mapping in ledger.mappings}
    return (
        f"Automated semantic mapping of {len(requirements)} requirement(s) to "
        f"{len(controls)} control(s) across {len(mappings)} catalog(s); "
        f"{relations} relationship(s) asserted by LLM retrieval and JEV verification."
    )


def build(ledger: Ledger, *, clock: Clock,
          id_factory: IdFactory) -> Optional[dict[str, Any]]:
    if not ledger.mappings:
        return None

    valid = {relation.value for relation in POSITIVE_RELATIONSHIPS}
    for row in ledger.mappings:
        if row["relation"] not in valid:
            raise IntegrityError(
                f"relation '{row['relation']}' is not one of the five positive OSCAL values"
            )

    by_catalog: dict[str, list[Mapping[str, Any]]] = {}
    for row in ledger.mappings:
        by_catalog.setdefault(row["catalog_id"], []).append(row)

    accepted = sorted({r.req_id for r in ledger.requirements if r.gate_status == "passed"})
    mappings: list[dict[str, Any]] = []
    for catalog in sorted(ledger.catalogs, key=lambda c: (c["content_sha256"], c["catalog_id"])):
        catalog_id = catalog["catalog_id"]
        rows = by_catalog.get(catalog_id)
        if not rows:
            continue
        stem = Path(catalog["path"]).stem
        entry: dict[str, Any] = {
            "uuid": id_factory.uuid_for("mapping", f"{ledger.run_id}:{catalog_id}"),
            "source-resource": {"type": "catalog", "href": "requirements-catalog.json"},
            "target-resource": {"type": "catalog", "href": f"catalogs/{stem}.json"},
            "maps": [
                _map_entry(row)
                for row in sorted(rows, key=lambda m: (m["req_id"], m["control_id"]))
            ],
        }
        mapped = {row["req_id"] for row in rows}
        unmapped = [req_id for req_id in accepted if req_id not in mapped]
        if unmapped:
            entry["source-gap-summary"] = {
                "uuid": id_factory.uuid_for(
                    "gap-summary", f"{ledger.run_id}:{catalog_id}"
                ),
                "unmapped-controls": [{"with-ids": [req_id]} for req_id in unmapped],
            }
        mappings.append(entry)

    if not mappings:
        return None

    collection = {
        "uuid": id_factory.uuid_for("mapping-collection", ledger.run_id),
        "metadata": metadata(
            f"smeargle mapping collection ({ledger.run_id})", clock=clock
        ),
        "provenance": {
            "method": "automation",
            "matching-rationale": "semantic",
            "status": "draft",
            "mapping-description": _description(ledger, mappings),
        },
        "mappings": mappings,
    }
    return {"mapping-collection": collection}
