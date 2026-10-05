"""Stage 6: read the ledger and assemble the §11 output (spec 11)."""

from __future__ import annotations

import json
import zlib
from pathlib import Path
from typing import Any, Mapping

from smeargle.config import Settings
from smeargle.domain.clock import Clock
from smeargle.domain.ids import IdFactory
from smeargle.domain.run import Ledger
from smeargle.oscal_build import emit
from smeargle.pipeline import index
from smeargle.prompts import indexing as indexing_prompt
from smeargle.store.run_store import RunStore


def _decompress(row: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(row)
    for key, name in (("request_json", "request"), ("response_json", "response")):
        blob = record.get(key)
        record[name] = json.loads(zlib.decompress(blob)) if blob else None
    return record


def _domains(store: RunStore, catalogs: list[dict[str, Any]],
             settings: Settings) -> dict[str, str]:
    model_id = settings.llm.model or "default"
    domains: dict[str, str] = {}
    for catalog in sorted(catalogs, key=lambda c: (c["content_sha256"], c["catalog_id"])):
        cached = index.cached_domain_index(
            store, catalog["content_sha256"], model_id, indexing_prompt.PROMPT_HASH
        )
        if cached is None:
            continue
        for domain, control_ids in cached.domains.items():
            for control_id in control_ids:
                domains[control_id] = domain
    return domains


def build_ledger(store: RunStore, run_id: str, *, settings: Settings,
                 config: Mapping[str, Any]) -> Ledger:
    run = dict(store.get_run(run_id) or {})
    run["config"] = dict(config)
    catalogs = store.list_catalogs(run_id)
    failures = tuple(
        row for row in store.list_attempts(run_id)
        if row.get("error_class") == "per_item_failure"
    )
    return Ledger(
        run_id=run_id,
        documents=tuple(store.list_documents(run_id)),
        requirements=tuple(store.list_requirements(run_id)),
        catalogs=tuple(catalogs),
        controls=tuple(store.list_controls(run_id)),
        pairs=tuple(store.list_pair_rows(run_id)),
        mappings=tuple(store.list_mappings(run_id)),
        evidence=tuple(_decompress(row) for row in store.list_evidence(run_id)),
        domains=_domains(store, catalogs, settings),
        failures=failures,
        run=run,
    )


def run_assemble(
    store: RunStore,
    run_id: str,
    output: Path,
    *,
    clock: Clock,
    id_factory: IdFactory,
    settings: Settings,
    config: Mapping[str, Any],
    partial: bool = False,
) -> emit.Assembly:
    ledger = build_ledger(store, run_id, settings=settings, config=config)
    assembly = emit.assemble(ledger, clock=clock, id_factory=id_factory, partial=partial)
    # §3 order: assemble → integrity gate (validate everything) → write outputs/export
    # evidence. A gate failure (exit 7) must leave NO assemble-owned artifacts or evidence
    # on disk (requirements-catalog/profile/mapping-collection/rationale + evidence/), so
    # nothing here is written until the gate has passed. Phase 2's Stage 2 `ingest_catalogs`
    # already wrote output/catalogs/*.json before assembly; that pre-assembly output is
    # external to this invariant and is deliberately not rolled back.
    emit.integrity_gate(assembly, ledger, partial=partial)
    emit.write_assembly(assembly, Path(output))
    emit.export_evidence(ledger.evidence, Path(output))
    return assembly
