from concurrent.futures import ThreadPoolExecutor

import pytest
from fakes.clients import FakeLLMClient

from smeargle.config import Settings
from smeargle.domain.controls import Control, DomainIndex
from smeargle.domain.ids import index_id_for
from smeargle.pipeline import index
from smeargle.pipeline import run as run_pipeline
from smeargle.pipeline.executor import Writer
from smeargle.prompts import indexing as indexing_prompt
from smeargle.store.run_store import CatalogRow, RunStore


def _control(control_id, text="text"):
    return Control("run-1", "cat-1", control_id, "T", text, "", "", ())


def _rendered_length(chunk):
    return sum(len(f"{c.control_id} | {c.title} | {c.text}") + 1 for c in chunk)


def test_label_chunk_parses_and_ignores_unknown_ids():
    llm = FakeLLMClient(
        default={
            "labels": [
                {"control_id": "ac-2", "domain": "access", "family": "Access"},
                {"control_id": "unknown", "domain": "x", "family": "X"},
            ]
        }
    )
    labels = index.label_chunk(llm, [_control("ac-2")], meta=None)
    assert labels == {"ac-2": ("access", "Access")}


def test_domain_index_groups_sorted_control_ids():
    labels = {"c2": ("access", "Access"), "c1": ("access", "Access"), "c3": ("audit", "Audit")}
    domain_index = index.domain_index_from_labels("sum", "model", "prompt", labels)
    assert domain_index.domains == {"access": ["c1", "c2"], "audit": ["c3"]}
    assert domain_index.index_id == index_id_for("sum", "model", "prompt")


def test_control_chunks_pack_below_the_char_budget():
    controls = [_control(f"c{i}", text="x" * 10) for i in range(5)]
    chunks = index.control_chunks(controls, max_chars=50)
    flattened = [control for chunk in chunks for control in chunk]
    assert flattened == controls
    for chunk in chunks:
        if len(chunk) > 1:
            assert _rendered_length(chunk) <= 50


def test_control_chunks_keeps_an_oversized_control_whole():
    oversized = _control("big", text="x" * 500)
    chunks = index.control_chunks([oversized], max_chars=50)
    assert len(chunks) == 1
    assert chunks[0] == [oversized]
    assert chunks[0][0].text == "x" * 500


def test_control_chunks_empty_input_returns_no_chunks():
    assert index.control_chunks([], max_chars=100) == []


def test_control_chunks_rejects_non_positive_budget():
    with pytest.raises(ValueError):
        index.control_chunks([_control("c0")], max_chars=0)


def test_control_chunks_split_a_large_catalog_into_multiple_chunks():
    controls = [_control(f"c{i}", text="x" * 100) for i in range(10)]
    chunks = index.control_chunks(controls, max_chars=250)
    assert len(chunks) > 1


def test_render_control_chunk_matches_the_control_lines():
    controls = [_control("c0", text="alpha"), _control("c1", text="beta")]
    listing = "\n".join(index._control_line(control) for control in controls)
    assert index.render_control_chunk(controls) == indexing_prompt.render_indexing(listing)


def test_run_index_llm_splits_a_large_control_set_into_multiple_calls(tmp_path):
    settings = Settings.load(overrides={"execution": {"control_chunk_chars": 50}})
    settings.llm.model = "test-model"
    llm = FakeLLMClient(default={"labels": []})
    writer = Writer(tmp_path)
    writer.start()
    try:
        writer.call(lambda store: store.create_run("run-1", "fp", "ch"))
        writer.call(
            lambda store: store.add_catalog(
                CatalogRow(
                    run_id="run-1",
                    catalog_id="cat-1",
                    ordinal=0,
                    uri="file:///catalog.json",
                    path="/catalog.json",
                    external_id=None,
                    content_sha256="sum",
                    oscal_version="1.2.3",
                    status="loaded",
                )
            )
        )
        controls = [_control(f"c{i}", text="x" * 100) for i in range(10)]
        writer.call(lambda store: store.add_controls(controls))
        with ThreadPoolExecutor(max_workers=2) as pool:
            complete = run_pipeline.run_index_llm(
                writer, "run-1", settings=settings, pool=pool, llm=llm
            )
        assert complete is True
        assert len(llm.calls) > 1
    finally:
        writer.stop()


def test_cached_domain_index_round_trips(tmp_path):
    with RunStore.open(tmp_path) as store:
        assert index.cached_domain_index(store, "sum", "model", "prompt") is None
        domain_index = DomainIndex("idx-1", "sum", "model", "prompt", {"access": ["c1"]})
        store.add_domain_index(domain_index)
        cached = index.cached_domain_index(store, "sum", "model", "prompt")
        assert cached == domain_index
