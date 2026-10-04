"""Stage 2 (catalog ingest portion): parse catalogs and emit normalised OSCAL (spec 10)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional

from smeargle.catalog_adapters import normalise
from smeargle.catalog_adapters.registry import parse_catalog
from smeargle.clients.dto import IndexResponseModel
from smeargle.clients.ports import CallMeta, LLMClient
from smeargle.domain.clock import Clock
from smeargle.domain.controls import Control, DomainIndex
from smeargle.domain.ids import IdFactory, catalog_id_for, index_id_for
from smeargle.errors import CatalogError
from smeargle.oscal_build import facade
from smeargle.prompts import indexing as indexing_prompt
from smeargle.store.run_store import CatalogRow, RunStore


def _oscal_timestamp(clock: Clock) -> str:
    return clock.now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")


def _check_stems(paths: list[Path]) -> None:
    seen: dict[str, Path] = {}
    for path in paths:
        stem = path.stem
        if stem in seen and seen[stem] != path:
            raise CatalogError(
                f"inputs '{seen[stem]}' and '{path}' share the stem '{stem}';"
                " rename one so normalised catalogs do not collide"
            )
        seen[stem] = path


def ingest_catalogs(
    store: RunStore,
    run_id: str,
    catalog_paths: Iterable[Path],
    output_dir: Path,
    *,
    catalog_format: str,
    clock: Clock,
    id_factory: IdFactory,
) -> list[str]:
    store.start_stage(run_id, "index")
    paths = [Path(p) for p in catalog_paths]
    _check_stems(paths)

    parsed_catalogs = []
    for path in paths:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise CatalogError(f"could not read catalog '{path}': {exc}") from exc
        catalog_id = catalog_id_for(raw)
        _kind, parsed = parse_catalog(path, catalog_format)
        parsed_catalogs.append((path, catalog_id, parsed))

    duplicate_paths: dict[str, Path] = {}
    for path, _catalog_id, parsed in parsed_catalogs:
        for control in parsed.controls:
            if control.control_id in duplicate_paths:
                raise CatalogError(
                    f"duplicate control id '{control.original_id}'"
                    f" (sanitised '{control.control_id}') in catalogs"
                    f" '{duplicate_paths[control.control_id]}' and '{path}'"
                )
            duplicate_paths[control.control_id] = path

    with store.transaction():
        for ordinal, (path, catalog_id, parsed) in enumerate(parsed_catalogs):
            store.add_catalog(
                CatalogRow(
                    run_id=run_id,
                    catalog_id=catalog_id,
                    ordinal=ordinal,
                    uri=path.absolute().as_uri(),
                    path=str(path),
                    external_id=None,
                    content_sha256=catalog_id,
                    oscal_version=parsed.oscal_version,
                    status="loaded",
                )
            )
            store.add_controls(
                [
                    Control(
                        run_id=run_id,
                        catalog_id=catalog_id,
                        control_id=control.control_id,
                        title=control.title,
                        text=control.text,
                        domain=control.domain,
                        family=control.family,
                        path=control.path,
                    )
                    for control in parsed.controls
                ]
            )
            document = normalise.build_normalised_catalog(
                catalog_id=catalog_id,
                parsed=parsed,
                source_uri=path.absolute().as_uri(),
                last_modified=_oscal_timestamp(clock),
                uuid_for=id_factory.uuid_for,
            )
            facade.validate("catalog", document)
            catalogs_dir = Path(output_dir) / "catalogs"
            catalogs_dir.mkdir(parents=True, exist_ok=True)
            (catalogs_dir / f"{path.stem}.json").write_text(
                facade.serialise_json("catalog", document), encoding="utf-8"
            )
        store.complete_stage(run_id, "index")

    return [catalog_id for _path, catalog_id, _parsed in parsed_catalogs]


def control_chunks(controls: list[Control], *, chunk_size: int) -> list[list[Control]]:
    if chunk_size < 1:
        raise ValueError("chunk_size must be >= 1")
    return [controls[i : i + chunk_size] for i in range(0, len(controls), chunk_size)]


def render_control_chunk(controls: list[Control]) -> str:
    listing = "\n".join(
        f"{control.control_id} | {control.title} | {control.text}" for control in controls
    )
    return indexing_prompt.render_indexing(listing)


def label_chunk(
    llm: LLMClient, controls: list[Control], *, meta: Optional[CallMeta] = None
) -> dict[str, tuple[str, str]]:
    known = {control.control_id for control in controls}
    messages = [{"role": "user", "content": render_control_chunk(controls)}]
    response = llm.complete_json(IndexResponseModel, messages, meta=meta)
    labels: dict[str, tuple[str, str]] = {}
    for label in response.labels:
        if label.control_id in known:
            labels[label.control_id] = (label.domain, label.family)
    return labels


def domain_index_from_labels(
    content_sha256: str,
    model_id: str,
    prompt_hash: str,
    labels: dict[str, tuple[str, str]],
) -> DomainIndex:
    domains: dict[str, list[str]] = {}
    for control_id, (domain, _family) in sorted(labels.items()):
        domains.setdefault(domain, []).append(control_id)
    return DomainIndex(
        index_id=index_id_for(content_sha256, model_id, prompt_hash),
        content_sha256=content_sha256,
        model_id=model_id,
        prompt_hash=prompt_hash,
        domains={domain: sorted(ids) for domain, ids in sorted(domains.items())},
    )


def cached_domain_index(
    store: RunStore, content_sha256: str, model_id: str, prompt_hash: str
) -> Optional[DomainIndex]:
    row = store.get_domain_index(content_sha256, model_id, prompt_hash)
    if row is None:
        return None
    return DomainIndex(
        index_id=row["index_id"],
        content_sha256=row["content_sha256"],
        model_id=row["model_id"],
        prompt_hash=row["prompt_hash"],
        domains=json.loads(row["index_json"]),
    )
