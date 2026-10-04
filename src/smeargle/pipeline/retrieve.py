"""Stage 3: choose relevant domains and nominate plausible controls (spec 10)."""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

from smeargle.clients.dto import DomainSelectionModel, NominationResponseModel
from smeargle.clients.ports import CallMeta, LLMClient
from smeargle.domain.controls import Control, DomainIndex
from smeargle.domain.requirements import Requirement
from smeargle.prompts import retrieval as retrieval_prompt


def merge_domain_indexes(indexes: Iterable[DomainIndex]) -> DomainIndex:
    domains: dict[str, set[str]] = {}
    for index in indexes:
        for domain, control_ids in index.domains.items():
            domains.setdefault(domain, set()).update(control_ids)
    return DomainIndex(
        index_id="merged",
        content_sha256="",
        model_id="",
        prompt_hash="",
        domains={domain: sorted(ids) for domain, ids in sorted(domains.items())},
    )


def domain_controls(
    domain_index: DomainIndex, controls: Sequence[Control]
) -> dict[str, list[Control]]:
    by_id = {control.control_id: control for control in controls}
    return {
        domain: [by_id[control_id] for control_id in control_ids if control_id in by_id]
        for domain, control_ids in domain_index.domains.items()
    }


def relevant_domains(
    llm: LLMClient, requirement: str, domains: Sequence[str], *,
    meta: Optional[CallMeta] = None,
) -> list[str]:
    known = set(domains)
    messages = [
        {
            "role": "user",
            "content": retrieval_prompt.render_domain_selection(requirement, domains),
        }
    ]
    response = llm.complete_json(DomainSelectionModel, messages, meta=meta)
    return [domain for domain in response.domains if domain in known]


def nominate_controls(
    llm: LLMClient, requirement: str, controls: Sequence[Control], *,
    meta: Optional[CallMeta] = None,
) -> list[str]:
    known = {control.control_id for control in controls}
    listing = [{"id": control.control_id, "text": control.text} for control in controls]
    messages = [
        {"role": "user", "content": retrieval_prompt.render_nomination(requirement, listing)}
    ]
    response = llm.complete_json(NominationResponseModel, messages, meta=meta)
    nominated: list[str] = []
    for control_id in response.control_ids:
        if control_id in known and control_id not in nominated:
            nominated.append(control_id)
    return nominated


def retrieve_requirement(
    llm: LLMClient,
    requirement: Requirement,
    domain_index: DomainIndex,
    controls: Sequence[Control],
    *,
    meta_prefix: str,
) -> list[tuple[str, str]]:
    mapping = domain_controls(domain_index, controls)
    chosen = relevant_domains(
        llm,
        requirement.text,
        list(mapping),
        meta=CallMeta(
            stage="retrieve", item_ref=f"{meta_prefix}:domains", call_type="llm_domains",
            prompt_hash=retrieval_prompt.DOMAIN_PROMPT_HASH,
        ),
    )
    by_id = {control.control_id: control for control in controls}
    nominated: list[tuple[str, str]] = []
    for domain in chosen:
        control_ids = nominate_controls(
            llm,
            requirement.text,
            mapping[domain],
            meta=CallMeta(
                stage="retrieve", item_ref=f"{meta_prefix}:nominated:{domain}",
                call_type="llm_nomination",
                prompt_hash=retrieval_prompt.NOMINATION_PROMPT_HASH,
            ),
        )
        for control_id in control_ids:
            control = by_id[control_id]
            pair = (control.catalog_id, control.control_id)
            if pair not in nominated:
                nominated.append(pair)
    return nominated
