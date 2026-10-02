"""Stage 2 (catalog ingest portion): parse catalogs and emit normalised OSCAL (spec 10)."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from smeargle.catalog_adapters import normalise
from smeargle.catalog_adapters.registry import parse_catalog
from smeargle.domain.clock import Clock
from smeargle.domain.controls import Control
from smeargle.domain.ids import IdFactory, catalog_id_for
from smeargle.errors import CatalogError
from smeargle.oscal_build import facade
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
        raw = path.read_bytes()
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
