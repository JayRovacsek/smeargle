from fakes.clients import FakeLLMClient

from smeargle.domain.controls import Control, DomainIndex
from smeargle.domain.ids import index_id_for
from smeargle.pipeline import index
from smeargle.store.run_store import RunStore


def _control(control_id, text="text"):
    return Control("run-1", "cat-1", control_id, "T", text, "", "", ())


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


def test_control_chunks_are_deterministic():
    controls = [_control(f"c{i}") for i in range(5)]
    chunks = index.control_chunks(controls, chunk_size=2)
    assert [[c.control_id for c in chunk] for chunk in chunks] == [
        ["c0", "c1"], ["c2", "c3"], ["c4"]
    ]


def test_cached_domain_index_round_trips(tmp_path):
    with RunStore.open(tmp_path) as store:
        assert index.cached_domain_index(store, "sum", "model", "prompt") is None
        domain_index = DomainIndex("idx-1", "sum", "model", "prompt", {"access": ["c1"]})
        store.add_domain_index(domain_index)
        cached = index.cached_domain_index(store, "sum", "model", "prompt")
        assert cached == domain_index
