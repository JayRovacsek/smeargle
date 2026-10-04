"""Shared ledger fixtures for Phase 4 artifact tests."""

from __future__ import annotations

from datetime import datetime, timezone

from smeargle.domain.clock import FrozenClock
from smeargle.domain.ids import UuidIdFactory
from smeargle.domain.requirements import Keyword, Requirement
from smeargle.domain.run import Ledger

FROZEN = datetime(2026, 1, 1, tzinfo=timezone.utc)
CLOCK = FrozenClock(FROZEN)
IDS = UuidIdFactory()
RUN_1 = "run-1"


def document(doc_id="d1", *, content_sha256="a" * 64, ordinal=0,
             path="/in/spec.txt", uri="file:///in/spec.txt"):
    return {
        "run_id": RUN_1, "doc_id": doc_id, "ordinal": ordinal, "path": path, "uri": uri,
        "external_id": None, "media_type": "text/plain", "content_sha256": content_sha256,
        "size_bytes": 10, "status": "loaded",
    }


def catalog(catalog_id="c1", *, content_sha256="b" * 64, ordinal=0,
            path="/in/vendor.json", uri="file:///in/vendor.json"):
    return {
        "run_id": RUN_1, "catalog_id": catalog_id, "ordinal": ordinal, "uri": uri,
        "path": path, "external_id": None, "content_sha256": content_sha256,
        "oscal_version": "1.2.3", "status": "loaded",
    }


def requirement(req_id="req-1", *, doc_id="d1", ordinal=0,
                text="The system MUST encrypt data at rest.", keyword=Keyword.MUST,
                gate="passed", retrieve="nominated", gate_noul_prob=0.9):
    return Requirement(
        RUN_1, req_id, doc_id, ordinal, text, text, keyword, "proposed", gate,
        gate_noul_prob, keyword.value if keyword else None, retrieve,
    )


def pair_row(pair_id="pair-1", *, req_id="req-1", catalog_id="c1", control_id="c-1.1",
             verify="passed", noul=0.9, classify="done", relation="subset-of",
             percentage=0.85, category="high"):
    return {
        "run_id": RUN_1, "pair_id": pair_id, "req_id": req_id, "catalog_id": catalog_id,
        "control_id": control_id, "verify_status": verify, "noul_prob": noul,
        "mapped_threshold": 0.5, "classify_status": classify, "relation": relation,
        "confidence_percentage": percentage, "confidence_category": category,
    }


def mapping_row(req_id="req-1", *, catalog_id="c1", control_id="c-1.1",
                relation="subset-of", percentage=0.85, category="high"):
    return {
        "run_id": RUN_1, "map_uuid": IDS.uuid_for(
            "map", f"{RUN_1}:{req_id}:{catalog_id}:{control_id}"
        ),
        "req_id": req_id, "catalog_id": catalog_id, "control_id": control_id,
        "relation": relation, "confidence_percentage": percentage,
        "confidence_category": category, "rationale": None,
    }


def run_block(**overrides):
    base = {
        "run_id": RUN_1, "fingerprint": "fp", "config_hash": "ch",
        "created_at": "2026-01-01T00:00:00+00:00", "finished_at": "2026-01-01T00:00:00+00:00",
        "status": "mapped", "oscal_version": "1.2.3", "config": {},
    }
    base.update(overrides)
    return base


def ledger(**overrides):
    base = dict(
        run_id=RUN_1, documents=(document(),), requirements=(requirement(),),
        catalogs=(catalog(),), controls=(), pairs=(pair_row(),),
        mappings=(mapping_row(),), evidence=(), domains={"c-1.1": "access"},
        failures=(), run=run_block(),
    )
    base.update(overrides)
    return Ledger(**base)
