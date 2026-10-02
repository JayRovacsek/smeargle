"""Orchestrate Stage 0 load and the Stage 2 catalog ingest; stop before any LLM work (spec 10)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from smeargle.config import Settings
from smeargle.domain.clock import Clock
from smeargle.domain.ids import IdFactory, config_hash, fingerprint, sha256_hex
from smeargle.observability import redact
from smeargle.pipeline import index, load
from smeargle.store.run_store import RunStore

_SECRET_SCOPED_KEYS = {"run_id", "force", "yes", "verbose"}


@dataclass(frozen=True, slots=True)
class IngestionResult:
    run_id: str
    fingerprint: str
    config_hash: str
    document_count: int
    catalog_count: int
    control_count: int


def config_snapshot(settings: Settings) -> dict[str, Any]:
    return {
        "llm": settings.llm.model_dump(mode="json"),
        "jev": settings.jev.model_dump(mode="json"),
        "mapping": settings.mapping.model_dump(mode="json"),
        "execution": {
            key: value
            for key, value in settings.execution.model_dump(mode="json").items()
            if key not in _SECRET_SCOPED_KEYS
        },
    }


def compute_fingerprint(input_paths: Iterable[Path], catalog_paths: Iterable[Path]) -> str:
    input_digests = [sha256_hex(Path(p).read_bytes()) for p in input_paths]
    catalog_digests = [sha256_hex(Path(p).read_bytes()) for p in catalog_paths]
    return fingerprint(input_digests, catalog_digests)


def run_ingestion(
    *,
    state_dir: Path,
    output: Path,
    input_paths: Iterable[Path],
    catalog_paths: Iterable[Path],
    settings: Settings,
    clock: Clock,
    id_factory: IdFactory,
    run_id: Optional[str] = None,
) -> IngestionResult:
    input_paths = [Path(p) for p in input_paths]
    catalog_paths = [Path(p) for p in catalog_paths]
    computed_fingerprint = compute_fingerprint(input_paths, catalog_paths)
    computed_config_hash = config_hash(redact(config_snapshot(settings)))
    selected_run_id = run_id or id_factory.run_uuid()

    with RunStore.open(state_dir, clock=clock, id_factory=id_factory) as store:
        store.create_run(selected_run_id, computed_fingerprint, computed_config_hash)
        documents = load.run_load(store, selected_run_id, input_paths)
        catalog_ids = index.ingest_catalogs(
            store,
            selected_run_id,
            catalog_paths,
            output,
            catalog_format=settings.execution.catalog_format,
            clock=clock,
            id_factory=id_factory,
        )
        store.set_run_status(selected_run_id, "ingested", finished=True)
        counts = store.counts(selected_run_id)

    return IngestionResult(
        run_id=selected_run_id,
        fingerprint=computed_fingerprint,
        config_hash=computed_config_hash,
        document_count=len(documents),
        catalog_count=len(catalog_ids),
        control_count=counts["controls"],
    )
