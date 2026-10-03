"""Derived work queries and stage lifecycle helpers (spec 7, 10)."""

from __future__ import annotations

from typing import Any

from smeargle.domain.mapping import CandidatePair
from smeargle.domain.requirements import Requirement
from smeargle.store.run_store import RunStore


def pending_documents(store: RunStore, run_id: str) -> list[dict[str, Any]]:
    return store.list_documents(run_id)


def pending_gate(store: RunStore, run_id: str) -> list[Requirement]:
    return store.requirements_for_gate(run_id)


def pending_retrieval(store: RunStore, run_id: str) -> list[Requirement]:
    return store.requirements_for_retrieval(run_id)


def pending_verify(store: RunStore, run_id: str) -> list[CandidatePair]:
    return store.candidate_pairs_for_verify(run_id)


def pending_classify(store: RunStore, run_id: str) -> list[CandidatePair]:
    return store.candidate_pairs_for_classify(run_id)


def claim_stage(store: RunStore, run_id: str, stage: str) -> None:
    store.start_stage(run_id, stage)


def complete_stage(store: RunStore, run_id: str, stage: str) -> None:
    store.complete_stage(run_id, stage)


def stage_complete(store: RunStore, run_id: str, stage: str) -> bool:
    row = store.get_stage(run_id, stage)
    return bool(row and row["status"] == "complete")


def chunk_ref(doc_id: str, index: int) -> str:
    return f"doc:{doc_id}:chunk:{index}"


def pair_ref(req_id: str, catalog_id: str, control_id: str) -> str:
    return f"pair:{req_id}:{catalog_id}:{control_id}"
