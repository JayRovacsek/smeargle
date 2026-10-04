"""Build the §11.1 requirements catalog from the ledger (pure)."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from smeargle.domain.clock import Clock
from smeargle.domain.ids import IdFactory
from smeargle.domain.requirements import Requirement
from smeargle.domain.run import Ledger
from smeargle.errors import IntegrityError
from smeargle.oscal_build.common import metadata, truncate


def _check_unique(requirements: Iterable[Requirement]) -> None:
    # §11.1 requires req_id collisions anywhere in the run to fail fast, not only among
    # the accepted requirements.
    seen: set[str] = set()
    for requirement in requirements:
        if requirement.req_id in seen:
            raise IntegrityError(f"duplicate requirement id '{requirement.req_id}'")
        seen.add(requirement.req_id)


def _group_title(document: Mapping[str, Any]) -> str:
    return document["path"] or document["uri"] or f"doc-{document['doc_id']}"


def _doc_props(document: Mapping[str, Any]) -> list[dict[str, str]]:
    return [
        {"name": "source-path", "value": document["path"] or document["doc_id"]},
        {"name": "source-uri", "value": document["uri"] or document["doc_id"]},
        {"name": "document-id", "value": document["doc_id"]},
        {"name": "content-sha256", "value": document["content_sha256"]},
    ]


def _control(requirement: Requirement, resource_uuid: str) -> dict[str, Any]:
    keyword = requirement.keyword.value if requirement.keyword else "MUST"
    return {
        "id": requirement.req_id,
        "title": truncate(requirement.text),
        "props": [
            {"name": "keyword", "value": keyword},
            {"name": "requirement-source", "value": requirement.doc_id},
        ],
        "parts": [
            {"id": f"{requirement.req_id}-statement", "name": "statement",
             "prose": requirement.text}
        ],
        "links": [{"rel": "reference", "href": f"#{resource_uuid}"}],
    }


def build(ledger: Ledger, *, clock: Clock, id_factory: IdFactory) -> dict[str, Any]:
    _check_unique(ledger.requirements)
    accepted = [r for r in ledger.requirements if r.gate_status == "passed"]
    by_doc: dict[str, list[Requirement]] = {}
    for requirement in accepted:
        by_doc.setdefault(requirement.doc_id, []).append(requirement)

    groups: list[dict[str, Any]] = []
    resources: list[dict[str, Any]] = []
    for document in sorted(ledger.documents, key=lambda d: (d["content_sha256"], d["doc_id"])):
        doc_id = document["doc_id"]
        resource_uuid = id_factory.uuid_for("document-resource", f"{ledger.run_id}:{doc_id}")
        group: dict[str, Any] = {
            "id": f"doc-{doc_id}", "title": _group_title(document),
            "props": _doc_props(document),
        }
        if by_doc.get(doc_id):
            # `controls` must be omitted (not empty) when there are no accepted
            # requirements: the catalog schema gives it minItems 1, while a group that
            # carries only title/props is still schema-valid.
            group["controls"] = [
                _control(requirement, resource_uuid)
                for requirement in sorted(by_doc[doc_id], key=lambda r: (r.ordinal, r.req_id))
            ]
        groups.append(group)
        resources.append(
            {"uuid": resource_uuid, "title": _group_title(document),
             "rlinks": [{"href": document["uri"] or document["path"]}]}
        )

    catalog: dict[str, Any] = {
        "uuid": id_factory.uuid_for("requirements-catalog", ledger.run_id),
        "metadata": metadata(f"smeargle requirements ({ledger.run_id})", clock=clock),
    }
    if groups:
        catalog["groups"] = groups
    if resources:
        catalog["back-matter"] = {"resources": resources}
    return {"catalog": catalog}
