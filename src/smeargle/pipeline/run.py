"""Orchestrate Stage 0 load and the Stage 2 catalog ingest; stop before any LLM work (spec 10)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from smeargle.clients.http import build_client, load_bearer_token
from smeargle.clients.jev import LayaJevClient
from smeargle.clients.llm import OpenAiCompatibleLLM
from smeargle.clients.ports import CallMeta
from smeargle.config import Settings
from smeargle.domain.clock import Clock
from smeargle.domain.ids import (
    IdFactory,
    config_hash,
    fingerprint,
    pair_id_for,
    req_id_for,
    sha256_hex,
)
from smeargle.domain.mapping import CandidatePair
from smeargle.domain.requirements import Requirement
from smeargle.errors import CatalogError, FatalServiceError, InputError, ServiceError
from smeargle.loaders import registry as loader_registry
from smeargle.observability import redact
from smeargle.pipeline import (
    classify,
    extract,
    index,
    load,
    retrieve,
    verify,
    work,
)
from smeargle.pipeline.executor import EvidenceBus, Writer, persist_sorted
from smeargle.pipeline.index import ingest_catalogs
from smeargle.prompts import (
    extraction as extraction_prompt,
)
from smeargle.prompts import (
    indexing as indexing_prompt,
)
from smeargle.prompts import (
    retrieval as retrieval_prompt,
)
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
    input_digests = []
    for path in input_paths:
        try:
            input_digests.append(sha256_hex(Path(path).read_bytes()))
        except OSError as exc:
            raise InputError(f"could not read input '{path}': {exc}") from exc
    catalog_digests = []
    for path in catalog_paths:
        try:
            catalog_digests.append(sha256_hex(Path(path).read_bytes()))
        except OSError as exc:
            raise CatalogError(f"could not read catalog '{path}': {exc}") from exc
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


@dataclass(frozen=True, slots=True)
class RunResult:
    run_id: str
    fingerprint: str
    config_hash: str
    document_count: int
    requirement_count: int
    candidate_count: int


def _is_fatal(error: BaseException) -> bool:
    return isinstance(error, FatalServiceError)


def _fan_out(pool: ThreadPoolExecutor, jobs: list[tuple[Any, Any]]) -> list[tuple[Any, Any, Optional[BaseException]]]:
    futures = {pool.submit(fn): key for key, fn in jobs}
    results: list[tuple[Any, Any, Optional[BaseException]]] = []
    for future in as_completed(futures):
        key = futures[future]
        try:
            results.append((key, future.result(), None))
        except BaseException as error:  # noqa: BLE001 - per-item failures continue
            if _is_fatal(error):
                raise
            results.append((key, None, error))
    return results


def _phase3_config_snapshot(settings: Settings) -> dict[str, Any]:
    snapshot = config_snapshot(settings)
    snapshot["prompts"] = {
        "extraction": extraction_prompt.PROMPT_HASH,
        "indexing": indexing_prompt.PROMPT_HASH,
        "retrieval_domain": retrieval_prompt.DOMAIN_PROMPT_HASH,
        "retrieval_nomination": retrieval_prompt.NOMINATION_PROMPT_HASH,
    }
    return snapshot


def _build_llm(settings: Settings, bus: EvidenceBus):
    if not settings.llm.endpoint:
        raise ServiceError("llm endpoint is not configured")
    token = load_bearer_token(auth_file=settings.llm.auth_file, api_key_env=settings.llm.api_key_env)
    http = build_client(
        base_url=settings.llm.endpoint, timeout=settings.llm.timeout, token=token,
        max_connections=settings.execution.concurrency,
    )
    client = OpenAiCompatibleLLM(
        http, model=settings.llm.model or "default", retries=settings.llm.retries,
        temperature=settings.llm.temperature, structured_output=settings.llm.structured_output,
        recorder=bus,
    )
    return http, client


def _build_jev(settings: Settings, bus: EvidenceBus):
    if not settings.jev.endpoint:
        raise ServiceError("jev endpoint is not configured")
    token = load_bearer_token(auth_file=settings.jev.auth_file, api_key_env=settings.jev.api_key_env)
    http = build_client(
        base_url=settings.jev.endpoint, timeout=settings.jev.timeout, token=token,
        max_connections=settings.execution.concurrency,
    )
    client = LayaJevClient(
        http, model=settings.jev.model or "default", retries=settings.jev.retries,
        batch=settings.jev.batch, batch_size=settings.jev.batch_size,
        min_confidence=settings.jev.min_confidence, recorder=bus,
    )
    return http, client


def run_extract(
    writer: Writer, run_id: str, *, settings: Settings, pool: ThreadPoolExecutor,
    llm, jev,
) -> None:
    writer.call(lambda store: work.claim_stage(store, run_id, "extract"))
    documents = writer.call(lambda store: work.pending_documents(store, run_id))
    jobs: list[tuple[Any, Any]] = []
    payloads: dict[Any, Any] = {}
    for document in documents:
        _media_type, text = loader_registry.load_document(Path(document["path"]))
        chunks = extract.chunk_text(
            text,
            chunk_size=settings.execution.chunk_size,
            overlap=settings.execution.chunk_overlap,
        )
        for position, chunk in enumerate(chunks):
            ref = work.chunk_ref(document["doc_id"], position)
            stage = f"extract:{ref}"
            if writer.call(
                lambda store: work.stage_complete(store, run_id, stage)
            ):
                continue
            key = (document["ordinal"], position)
            writer.call(lambda store: work.claim_stage(store, run_id, stage))
            meta = CallMeta(
                stage="extract", item_ref=ref, call_type="llm_extract",
                prompt_hash=extraction_prompt.PROMPT_HASH,
            )
            jobs.append((key, lambda chunk=chunk, meta=meta: extract.propose_chunk(llm, chunk, meta=meta)))
            payloads[key] = (document, position, chunk, stage)

    proposals: list[tuple[Any, str, Requirement]] = []
    completed: list[Any] = []
    for key, outcome, error in _fan_out(pool, jobs):
        if error is not None:
            continue
        completed.append(key)
        document, position, _chunk, _stage = payloads[key]
        for order, (text, keyword, _rationale) in enumerate(outcome):
            normalised = extract.normalise_text(text)
            req_id = req_id_for(document["content_sha256"], normalised)
            requirement = Requirement(
                run_id=run_id, req_id=req_id, doc_id=document["doc_id"], ordinal=0,
                text=text, normalized_text=normalised, keyword=keyword,
                extract_status="proposed", gate_status=None, gate_noul_prob=None,
                gate_choice=None, retrieve_status=None,
            )
            proposals.append(((document["ordinal"], position, order), req_id, requirement))

    unique: dict[str, Requirement] = {}
    for _key, req_id, requirement in sorted(proposals, key=lambda item: item[0]):
        unique.setdefault(req_id, requirement)
    ordered = [replace(requirement, ordinal=index) for index, requirement in enumerate(unique.values())]
    persist_sorted(
        writer, [(requirement.req_id, requirement) for requirement in ordered],
        lambda store, requirement: store.add_requirement_if_absent(requirement),
    )
    for key in sorted(completed):
        _document, _position, _chunk, stage = payloads[key]
        writer.call(lambda store: work.complete_stage(store, run_id, stage))

    gate_requirements = writer.call(lambda store: work.pending_gate(store, run_id))
    gate_jobs: list[tuple[Any, Any]] = []
    for requirement in gate_requirements:
        meta = CallMeta(stage="extract", item_ref=f"gate:{requirement.req_id}", call_type="jev_gate")
        gate_jobs.append(
            (
                requirement.req_id,
                lambda requirement=requirement, meta=meta: (
                    requirement,
                    extract.gate_requirement(
                        jev, requirement,
                        threshold=settings.mapping.extract_gate_threshold,
                        min_confidence=settings.jev.min_confidence, meta=meta,
                    ),
                ),
            )
        )
    gate_results = _fan_out(pool, gate_jobs)

    def apply_gate(store, item) -> None:
        requirement, outcome = item
        store.set_requirement_gate(
            run_id, requirement.req_id, gate_status=outcome.gate_status,
            gate_noul_prob=outcome.gate_noul_prob, gate_choice=outcome.gate_choice,
            keyword=outcome.keyword.value if outcome.keyword else None,
            extract_status=outcome.extract_status,
        )

    persist_sorted(
        writer,
        [(key, item) for key, item, error in gate_results if error is None],
        apply_gate,
    )
    writer.call(lambda store: work.complete_stage(store, run_id, "extract"))


def run_index_llm(
    writer: Writer, run_id: str, *, settings: Settings, pool: ThreadPoolExecutor, llm
) -> bool:
    catalogs = writer.call(lambda store: store.list_catalogs(run_id))
    model_id = settings.llm.model or "default"
    all_complete = True
    for catalog in catalogs:
        cached = writer.call(
            lambda store: index.cached_domain_index(
                store, catalog["content_sha256"], model_id, indexing_prompt.PROMPT_HASH
            )
        )
        if cached is not None:
            continue
        controls = writer.call(
            lambda store: store.list_controls(run_id, catalog["catalog_id"])
        )
        chunks = index.control_chunks(controls, chunk_size=settings.execution.chunk_size)
        jobs: list[tuple[Any, Any]] = []
        for position, chunk in enumerate(chunks):
            ref = f"catalog:{catalog['catalog_id']}:chunk:{position}"
            meta = CallMeta(
                stage="index", item_ref=ref, call_type="llm_index",
                prompt_hash=indexing_prompt.PROMPT_HASH,
            )
            jobs.append((ref, lambda chunk=chunk, meta=meta: index.label_chunk(llm, chunk, meta=meta)))
        labels: dict[str, tuple[str, str]] = {}
        failed = False
        for _key, outcome, error in _fan_out(pool, jobs):
            if error is not None:
                failed = True
            elif outcome:
                labels.update(outcome)
        if failed:
            all_complete = False
            writer.call(
                lambda store: store.record_attempt(
                    run_id=run_id, stage="index",
                    item_ref=f"catalog:{catalog['catalog_id']}", call_type="llm_index",
                    attempt_no=0, error_class="incomplete",
                    error="one or more domain-index chunks failed", duration_ms=0,
                )
            )
            continue
        domain_index = index.domain_index_from_labels(
            catalog["content_sha256"], model_id, indexing_prompt.PROMPT_HASH, labels
        )
        writer.call(lambda store: store.add_domain_index(domain_index))
    return all_complete


def run_retrieve(
    writer: Writer, run_id: str, *, settings: Settings, pool: ThreadPoolExecutor, llm
) -> None:
    writer.call(lambda store: work.claim_stage(store, run_id, "retrieve"))
    model_id = settings.llm.model or "default"
    indexes = []
    for catalog in writer.call(lambda store: store.list_catalogs(run_id)):
        cached = writer.call(
            lambda store: index.cached_domain_index(
                store, catalog["content_sha256"], model_id, indexing_prompt.PROMPT_HASH
            )
        )
        if cached is not None:
            indexes.append(cached)
    domain_index = retrieve.merge_domain_indexes(indexes)
    controls = writer.call(lambda store: store.list_controls(run_id))
    requirements = writer.call(lambda store: work.pending_retrieval(store, run_id))
    jobs = [
        (
            requirement.req_id,
            lambda requirement=requirement: (
                requirement,
                retrieve.retrieve_requirement(
                    llm, requirement, domain_index, controls,
                    meta_prefix=f"req:{requirement.req_id}",
                ),
            ),
        )
        for requirement in requirements
    ]
    results = _fan_out(pool, jobs)

    def apply(store, item) -> None:
        requirement, pairs = item
        if not pairs:
            store.set_requirement_retrieve_status(run_id, requirement.req_id, "none")
            return
        for catalog_id, control_id in pairs:
            store.add_candidate_pair(
                CandidatePair(
                    run_id=run_id,
                    pair_id=pair_id_for(requirement.req_id, catalog_id, control_id),
                    req_id=requirement.req_id, catalog_id=catalog_id, control_id=control_id,
                    verify_status="pending",
                ),
                mapped_threshold=settings.mapping.mapped_threshold,
            )
        store.set_requirement_retrieve_status(run_id, requirement.req_id, "nominated")

    persist_sorted(
        writer,
        [(key, item) for key, item, error in results if error is None],
        apply,
    )
    writer.call(lambda store: work.complete_stage(store, run_id, "retrieve"))


def run_verify(
    writer: Writer, run_id: str, *, settings: Settings, pool: ThreadPoolExecutor, jev
) -> None:
    writer.call(lambda store: work.claim_stage(store, run_id, "verify"))
    requirements = {r.req_id: r for r in writer.call(lambda store: store.list_requirements(run_id))}
    controls = {
        (c.catalog_id, c.control_id): c for c in writer.call(lambda store: store.list_controls(run_id))
    }
    pairs = writer.call(lambda store: work.pending_verify(store, run_id))
    items = [
        (pair, requirements[pair.req_id].text, controls[(pair.catalog_id, pair.control_id)].text)
        for pair in pairs
    ]
    persisted: list[tuple[Any, Any]] = []
    if settings.jev.batch and items:
        batch_jobs = []
        for start in range(0, len(items), settings.jev.batch_size):
            group = items[start : start + settings.jev.batch_size]
            pair_group = [pair for pair, _requirement, _control in group]
            call_items = [(pair.pair_id, requirement, control) for pair, requirement, control in group]
            meta = CallMeta(
                stage="verify", item_ref=f"batch:{pair_group[0].pair_id}", call_type="jev_noul"
            )
            batch_jobs.append(
                (
                    pair_group[0].pair_id,
                    lambda pair_group=pair_group, call_items=call_items, meta=meta: list(
                        zip(
                            pair_group,
                            verify.verify_batch(
                                jev, call_items,
                                threshold=settings.mapping.mapped_threshold,
                                min_confidence=settings.jev.min_confidence, meta=meta,
                            ),
                        )
                    ),
                )
            )
        for _key, value, error in _fan_out(pool, batch_jobs):
            if error is None:
                persisted.extend((pair.pair_id, (pair, outcome)) for pair, outcome in value)
    else:
        jobs = []
        for pair in pairs:
            meta = CallMeta(stage="verify", item_ref=work.pair_ref(pair.req_id, pair.catalog_id, pair.control_id), call_type="jev_noul")
            jobs.append(
                (
                    pair.pair_id,
                    lambda pair=pair, meta=meta: (
                        pair,
                        verify.verify_pair(
                            jev, requirements[pair.req_id].text, controls[(pair.catalog_id, pair.control_id)].text,
                            threshold=settings.mapping.mapped_threshold,
                            min_confidence=settings.jev.min_confidence, meta=meta,
                        ),
                    ),
                )
            )
        persisted = [(key, item) for key, item, error in _fan_out(pool, jobs) if error is None]

    def apply(store, item) -> None:
        pair, outcome = item
        store.set_pair_verify(
            run_id, pair.pair_id, verify_status=outcome.verify_status, noul_prob=outcome.noul_prob
        )

    persist_sorted(writer, persisted, apply)
    writer.call(lambda store: work.complete_stage(store, run_id, "verify"))


def run_classify(
    writer: Writer, run_id: str, *, settings: Settings, pool: ThreadPoolExecutor, jev
) -> None:
    writer.call(lambda store: work.claim_stage(store, run_id, "classify"))
    requirements = {r.req_id: r for r in writer.call(lambda store: store.list_requirements(run_id))}
    controls = {
        (c.catalog_id, c.control_id): c for c in writer.call(lambda store: store.list_controls(run_id))
    }
    pairs = writer.call(lambda store: work.pending_classify(store, run_id))
    items = [
        (pair, requirements[pair.req_id].text, controls[(pair.catalog_id, pair.control_id)].text)
        for pair in pairs
    ]
    persisted: list[tuple[Any, Any]] = []
    if settings.jev.batch and items:
        batch_jobs = []
        for start in range(0, len(items), settings.jev.batch_size):
            group = items[start : start + settings.jev.batch_size]
            pair_group = [pair for pair, _requirement, _control in group]
            call_items = [(pair.pair_id, requirement, control) for pair, requirement, control in group]
            meta = CallMeta(
                stage="classify", item_ref=f"batch:{pair_group[0].pair_id}", call_type="jev_choice"
            )
            batch_jobs.append(
                (
                    pair_group[0].pair_id,
                    lambda pair_group=pair_group, call_items=call_items, meta=meta: list(
                        zip(
                            pair_group,
                            classify.classify_batch(
                                jev, call_items,
                                min_confidence=settings.jev.min_confidence, meta=meta,
                            ),
                        )
                    ),
                )
            )
        for _key, value, error in _fan_out(pool, batch_jobs):
            if error is None:
                persisted.extend((pair.pair_id, (pair, outcome)) for pair, outcome in value)
    else:
        jobs = []
        for pair in pairs:
            meta = CallMeta(stage="classify", item_ref=f"pair:{pair.pair_id}", call_type="jev_choice")
            jobs.append(
                (
                    pair.pair_id,
                    lambda pair=pair, meta=meta: (
                        pair,
                        classify.classify_pair(
                            jev, requirements[pair.req_id].text,
                            controls[(pair.catalog_id, pair.control_id)].text,
                            min_confidence=settings.jev.min_confidence, meta=meta,
                        ),
                    ),
                )
            )
        persisted = [(key, item) for key, item, error in _fan_out(pool, jobs) if error is None]

    def apply(store, item) -> None:
        pair, outcome = item
        if outcome.classify_status == "done":
            record = classify.build_mapping_record(
                run_id=run_id, req_id=pair.req_id, catalog_id=pair.catalog_id,
                control_id=pair.control_id, outcome=outcome,
                category_high=settings.mapping.category_high,
                category_medium=settings.mapping.category_medium,
            )
            store.add_mapping(record)
            store.set_pair_classify(
                run_id, pair.pair_id, classify_status="done", relation=outcome.relation.value,
                confidence_percentage=outcome.confidence_percentage,
                confidence_category=record.confidence_category,
            )
        else:
            store.set_pair_classify(run_id, pair.pair_id, classify_status=outcome.classify_status)

    persist_sorted(writer, persisted, apply)
    writer.call(lambda store: work.complete_stage(store, run_id, "classify"))


def run_pipeline(
    *,
    state_dir: Path,
    output: Path,
    input_paths: Sequence[Path],
    catalog_paths: Sequence[Path],
    settings: Settings,
    clock: Clock,
    id_factory: IdFactory,
    run_id: Optional[str] = None,
) -> RunResult:
    input_paths = [Path(p) for p in input_paths]
    catalog_paths = [Path(p) for p in catalog_paths]
    computed_fingerprint = compute_fingerprint(input_paths, catalog_paths)
    computed_config_hash = config_hash(redact(_phase3_config_snapshot(settings)))
    selected = run_id or settings.execution.run_id or id_factory.run_uuid()

    writer = Writer(state_dir, clock=clock, id_factory=id_factory)
    writer.start()
    llm_http = jev_http = None
    try:
        bus = EvidenceBus(writer, selected)
        llm_http, llm = _build_llm(settings, bus)
        jev_http, jev = _build_jev(settings, bus)
        if writer.call(lambda store: store.get_run(selected)) is None:
            writer.call(lambda store: store.create_run(selected, computed_fingerprint, computed_config_hash))
        with ThreadPoolExecutor(max_workers=settings.execution.concurrency) as pool:
            if not writer.call(lambda store: work.stage_complete(store, selected, "load")):
                writer.call(lambda store: load.run_load(store, selected, input_paths))
            if not writer.call(lambda store: work.stage_complete(store, selected, "index")):
                writer.call(
                    lambda store: ingest_catalogs(
                        store, selected, catalog_paths, output,
                        catalog_format=settings.execution.catalog_format,
                        clock=clock, id_factory=id_factory,
                    )
                )
            with ThreadPoolExecutor(max_workers=2) as streams:
                extract_stream = streams.submit(
                    run_extract, writer, selected, settings=settings, pool=pool, llm=llm, jev=jev
                )
                index_stream = streams.submit(
                    run_index_llm, writer, selected, settings=settings, pool=pool, llm=llm
                )
                extract_stream.result()
                index_ok = index_stream.result()
            if index_ok:
                run_retrieve(writer, selected, settings=settings, pool=pool, llm=llm)
                run_verify(writer, selected, settings=settings, pool=pool, jev=jev)
                run_classify(writer, selected, settings=settings, pool=pool, jev=jev)
        if index_ok:
            writer.call(lambda store: store.set_run_status(selected, "mapped", finished=True))
        else:
            writer.call(lambda store: store.set_run_status(selected, "index_incomplete"))
        counts = writer.call(lambda store: store.counts(selected))
    finally:
        if llm_http is not None:
            llm_http.close()
        if jev_http is not None:
            jev_http.close()
        writer.stop()

    return RunResult(
        run_id=selected,
        fingerprint=computed_fingerprint,
        config_hash=computed_config_hash,
        document_count=counts["documents"],
        requirement_count=counts["requirements"],
        candidate_count=counts["candidate_pairs"],
    )
