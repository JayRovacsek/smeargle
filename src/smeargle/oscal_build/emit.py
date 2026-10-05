"""Assemble, write, and gate the §11 output layout (pure builders + gate)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from smeargle.domain.clock import Clock
from smeargle.domain.ids import IdFactory
from smeargle.domain.run import Ledger
from smeargle.errors import CatalogError, IntegrityError
from smeargle.observability import redact
from smeargle.oscal_build import (
    facade,
)
from smeargle.oscal_build import (
    mapping as mapping_builder,
)
from smeargle.oscal_build import (
    profile as profile_builder,
)
from smeargle.oscal_build import (
    rationale as rationale_builder,
)
from smeargle.oscal_build import (
    requirements_catalog as requirements_builder,
)

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _evidence_name(record: Mapping[str, Any]) -> str:
    # `request_sha256` distinguishes repair-loop / fallback rows that share the same
    # (stage, item_ref, call_type, attempt_no); dropping it would overwrite records.
    stem = "-".join(
        [
            str(record.get("stage", "stage")),
            str(record.get("item_ref", "item")),
            str(record.get("call_type", "call")),
            str(record.get("attempt_no", 0)),
            str(record.get("request_sha256", "")),
        ]
    )
    return _UNSAFE.sub("-", stem).strip("-") + ".json"


def export_evidence(evidence: Sequence[Mapping[str, Any]], output: Path) -> list[Path]:
    directory = Path(output) / "evidence"
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for record in evidence:
        payload = {
            "stage": record.get("stage"),
            "item_ref": record.get("item_ref"),
            "call_type": record.get("call_type"),
            "attempt_no": record.get("attempt_no"),
            "http_status": record.get("http_status"),
            "request_sha256": record.get("request_sha256"),
            "prompt_hash": record.get("prompt_hash"),
            "request": redact(record.get("request")),
            "response": redact(record.get("response")),
        }
        path = directory / _evidence_name(record)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8"
        )
        written.append(path)
    return written


@dataclass(frozen=True, slots=True)
class Assembly:
    requirements_catalog: Mapping[str, Any]
    profile: Mapping[str, Any] | None
    mapping_collection: Mapping[str, Any] | None
    rationale: Mapping[str, Any]
    unmapped_requirements: tuple[str, ...]
    failures: int
    partial: bool = False

    @property
    def gaps(self) -> int:
        return len(self.unmapped_requirements) + self.failures


def assemble(ledger: Ledger, *, clock: Clock, id_factory: IdFactory,
             partial: bool = False) -> Assembly:
    requirements_catalog = requirements_builder.build(
        ledger, clock=clock, id_factory=id_factory
    )
    if partial:
        return Assembly(requirements_catalog, None, None, {}, (), len(ledger.failures),
                        partial=True)
    mapping_collection = mapping_builder.build(ledger, clock=clock, id_factory=id_factory)
    profile = profile_builder.build(
        ledger, mapping_present=mapping_collection is not None, clock=clock,
        id_factory=id_factory,
    )
    rationale = rationale_builder.build(ledger, clock=clock, id_factory=id_factory)
    unmapped = tuple(item["req_id"] for item in rationale["unmapped_requirements"])
    return Assembly(requirements_catalog, profile, mapping_collection, rationale,
                    unmapped, len(ledger.failures))


def write_assembly(assembly: Assembly, output: Path) -> list[Path]:
    output = Path(output)
    written: list[Path] = []
    target = output / "requirements-catalog.json"
    facade.write_document(target, "catalog", assembly.requirements_catalog)
    written.append(target)
    if assembly.profile is not None:
        target = output / "profile.json"
        facade.write_document(target, "profile", assembly.profile)
        written.append(target)
    if assembly.mapping_collection is not None:
        target = output / "mapping-collection.json"
        facade.write_document(target, "mapping-collection", assembly.mapping_collection)
        written.append(target)
    if assembly.rationale:
        target = output / "rationale.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(assembly.rationale, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        written.append(target)
    return written


def _resources(document: Mapping[str, Any], key: str) -> list[Any]:
    return ((document.get(key) or {}).get("back-matter") or {}).get("resources") or []


def _iter_links(node: Any):
    if isinstance(node, Mapping):
        if "href" in node:
            yield node
        for value in node.values():
            yield from _iter_links(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_links(value)


def _resource_uuids(assembly: Assembly) -> set[str]:
    uuids: set[str] = set()
    for document, key in (
        (assembly.requirements_catalog, "catalog"),
        (assembly.profile, "profile"),
        (assembly.mapping_collection, "mapping-collection"),
    ):
        if document is not None:
            for resource in _resources(document, key):
                if resource.get("uuid"):
                    uuids.add(resource["uuid"])
    return uuids


def _control_ids(document: Mapping[str, Any]) -> set[str]:
    # Only catalog controls (never groups or other id+title nodes) can be the target of a
    # `resource-fragment`, so restrict the walk to `controls` arrays.
    ids: set[str] = set()

    def walk_controls(controls: Any) -> None:
        if not isinstance(controls, list):
            return
        for control in controls:
            if not isinstance(control, Mapping):
                continue
            if "id" in control:
                ids.add(str(control["id"]))
            walk_controls(control.get("controls"))

    def walk_groups(groups: Any) -> None:
        if not isinstance(groups, list):
            return
        for group in groups:
            if not isinstance(group, Mapping):
                continue
            walk_controls(group.get("controls"))
            walk_groups(group.get("groups"))

    catalog = document.get("catalog") or {}
    walk_controls(catalog.get("controls"))
    walk_groups(catalog.get("groups"))
    return ids


def _gap_summary_ids(assembly: Assembly) -> set[str]:
    ids: set[str] = set()
    if assembly.mapping_collection is None:
        return ids
    for entry in assembly.mapping_collection["mapping-collection"]["mappings"]:
        summary = entry.get("source-gap-summary") or {}
        for select in summary.get("unmapped-controls", []):
            ids.update(select.get("with-ids", []))
    return ids


def _mapped_ids(assembly: Assembly) -> set[str]:
    ids: set[str] = set()
    if assembly.mapping_collection is None:
        return ids
    for entry in assembly.mapping_collection["mapping-collection"]["mappings"]:
        for map_entry in entry["maps"]:
            ids.update(source["id-ref"] for source in map_entry["sources"])
    return ids


def _validate(model: str | None, document: Mapping[str, Any] | None) -> None:
    if model is None or document is None:
        return
    try:
        facade.validate(model, document)
    except CatalogError as exc:
        raise IntegrityError(str(exc)) from exc


def integrity_gate(assembly: Assembly, ledger: Ledger, *, partial: bool = False) -> None:
    _validate("catalog", assembly.requirements_catalog)
    _check_fragments(assembly)
    _check_unique_control_ids(ledger)
    if partial:
        return
    _validate("profile", assembly.profile)
    _validate("mapping-collection", assembly.mapping_collection)
    _check_accepted_coverage(assembly, ledger)
    _check_imports(assembly, ledger)


def _check_accepted_coverage(assembly: Assembly, ledger: Ledger) -> None:
    represented = _mapped_ids(assembly) | _gap_summary_ids(assembly) | set(
        assembly.unmapped_requirements
    )
    for requirement in ledger.requirements:
        if requirement.gate_status == "passed" and requirement.req_id not in represented:
            raise IntegrityError(
                f"accepted requirement '{requirement.req_id}' is not represented"
            )


def _check_imports(assembly: Assembly, ledger: Ledger) -> None:
    if assembly.profile is None:
        return
    imports = assembly.profile["profile"]["imports"]
    expected = {
        f"catalogs/{Path(catalog['path']).stem}.json" for catalog in ledger.catalogs
    }
    imported = {entry.get("href") for entry in imports}
    if imported != expected:
        raise IntegrityError(
            f"profile imports {sorted(imported)} do not cover catalogs {sorted(expected)}"
        )
    for entry in imports:
        if "include-all" not in entry:
            raise IntegrityError("every profile import must include-all")


def _check_fragments(assembly: Assembly) -> None:
    uuids = _resource_uuids(assembly)
    req_ids = _control_ids(assembly.requirements_catalog)
    for document, key in (
        (assembly.requirements_catalog, "catalog"),
        (assembly.profile, "profile"),
        (assembly.mapping_collection, "mapping-collection"),
    ):
        if document is None:
            continue
        for link in _iter_links(document):
            href = str(link.get("href", ""))
            if link.get("rel") == "reference":
                if href.startswith("#"):
                    if href[1:] not in uuids:
                        raise IntegrityError(f"fragment reference '{href}' does not resolve")
                elif not urlsplit(href).scheme:
                    raise IntegrityError(f"link href '{href}' is not an absolute URI")
            elif href.startswith("#") and href[1:] not in uuids:
                raise IntegrityError(f"fragment reference '{href}' does not resolve")
            fragment = link.get("resource-fragment")
            if fragment is not None and fragment not in req_ids:
                raise IntegrityError(
                    f"resource-fragment '{fragment}' does not resolve in the requirements catalog"
                )


def _check_unique_control_ids(ledger: Ledger) -> None:
    seen: set[str] = set()
    for control in ledger.controls:
        if control.control_id in seen:
            raise IntegrityError(f"duplicate control id '{control.control_id}'")
        seen.add(control.control_id)
