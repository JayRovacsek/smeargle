import uuid

from smeargle.domain.ids import (
    UuidIdFactory,
    catalog_id_for,
    config_hash,
    doc_id_for,
    fingerprint,
    index_id_for,
    pair_id_for,
    req_id_for,
)


def test_doc_and_catalog_ids_are_content_hashes():
    assert doc_id_for(b"abc") == doc_id_for(b"abc")
    assert doc_id_for(b"abc") != doc_id_for(b"abd")
    assert len(doc_id_for(b"abc")) == 64
    assert catalog_id_for(b"abc") == doc_id_for(b"abc")


def test_fingerprint_is_order_independent():
    assert fingerprint(["a", "b"], ["c"]) == fingerprint(["b", "a"], ["c"])


def test_fingerprint_is_content_sensitive():
    assert fingerprint(["a"], []) != fingerprint(["b"], [])
    assert fingerprint(["a"], []) != fingerprint(["a"], ["a"])


def test_req_id_is_prefixed_and_deterministic():
    r1 = req_id_for("deadbeef", "The system MUST x")
    r2 = req_id_for("deadbeef", "The system MUST x")
    r3 = req_id_for("deadbeef", "The system MUST y")
    assert r1 == r2
    assert r1 != r3
    assert r1.startswith("req-")


def test_pair_and_index_ids_are_deterministic():
    assert pair_id_for("req-a", "cat", "ctrl") == pair_id_for("req-a", "cat", "ctrl")
    assert pair_id_for("req-a", "cat", "ctrl") != pair_id_for("req-a", "cat", "ctrl2")
    assert index_id_for("sum", "model", "prompt") == index_id_for("sum", "model", "prompt")
    assert index_id_for("sum", "model", "prompt") != index_id_for("sum", "model2", "prompt")


def test_config_hash_is_order_independent_and_sensitive():
    assert config_hash({"a": 1, "b": 2}) == config_hash({"b": 2, "a": 1})
    assert config_hash({"a": 1}) != config_hash({"a": 2})


def test_uuid_factory_is_stable():
    factory = UuidIdFactory()
    u1 = factory.uuid_for("map", "run:req:cat:ctrl")
    u2 = factory.uuid_for("map", "run:req:cat:ctrl")
    assert u1 == u2
    assert uuid.UUID(u1)
    assert factory.uuid_for("map", "x") != factory.uuid_for("other", "x")
    assert uuid.UUID(factory.run_uuid())
