"""Typed repository over the SQLite run store (spec 7)."""

from __future__ import annotations

import json
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from smeargle.domain.clock import Clock, SystemClock
from smeargle.domain.controls import Control, DomainIndex
from smeargle.domain.documents import Document
from smeargle.domain.ids import IdFactory, UuidIdFactory, sha256_hex
from smeargle.domain.mapping import CandidatePair, MappingRecord
from smeargle.domain.requirements import Keyword, Requirement
from smeargle.observability import redact
from smeargle.store import db as db_module
from smeargle.store.schema import migrate


@dataclass(frozen=True, slots=True)
class CatalogRow:
    run_id: str
    catalog_id: str
    ordinal: int
    uri: str
    path: str
    external_id: Optional[str]
    content_sha256: str
    oscal_version: Optional[str]
    status: str


def _requirement_from_row(row) -> Requirement:
    keyword = row["keyword"]
    return Requirement(
        run_id=row["run_id"],
        req_id=row["req_id"],
        doc_id=row["doc_id"],
        ordinal=row["ordinal"],
        text=row["text"],
        normalized_text=row["normalized_text"],
        keyword=Keyword(keyword) if keyword is not None else None,
        extract_status=row["extract_status"],
        gate_status=row["gate_status"],
        gate_noul_prob=row["gate_noul_prob"],
        gate_choice=row["gate_choice"],
        retrieve_status=row["retrieve_status"],
    )


class RunStore:
    def __init__(self, conn, clock: Optional[Clock] = None, id_factory: Optional[IdFactory] = None):
        self._conn = conn
        self._clock = clock or SystemClock()
        self._ids = id_factory or UuidIdFactory()

    @classmethod
    def open(
        cls,
        state_dir: Path,
        *,
        clock: Optional[Clock] = None,
        id_factory: Optional[IdFactory] = None,
    ) -> "RunStore":
        conn = db_module.connect(state_dir)
        migrate(conn)
        return cls(conn, clock=clock, id_factory=id_factory)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "RunStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def transaction(self):
        return db_module.transaction(self._conn)

    def _now(self) -> str:
        return self._clock.now_utc().isoformat()

    # -- runs ---------------------------------------------------------------
    def create_run(
        self,
        run_id: str,
        fingerprint: str,
        config_hash: str,
        *,
        oscal_version: str = "1.2.3",
        status: str = "started",
    ) -> None:
        now = self._now()
        self._conn.execute(
            "INSERT INTO runs (run_id, fingerprint, config_hash, status, oscal_version,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, fingerprint, config_hash, status, oscal_version, now, now),
        )

    def get_run(self, run_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def list_runs(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM runs ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]

    def find_runs_by_fingerprint(self, fingerprint: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM runs WHERE fingerprint = ? ORDER BY created_at DESC",
            (fingerprint,),
        ).fetchall()
        return [dict(row) for row in rows]

    def set_run_status(self, run_id: str, status: str, *, finished: bool = False) -> None:
        now = self._now()
        if finished:
            self._conn.execute(
                "UPDATE runs SET status = ?, updated_at = ?, finished_at = ? WHERE run_id = ?",
                (status, now, now, run_id),
            )
        else:
            self._conn.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE run_id = ?",
                (status, now, run_id),
            )

    # -- stage_runs ---------------------------------------------------------
    def start_stage(self, run_id: str, stage: str) -> None:
        self._conn.execute(
            "INSERT INTO stage_runs (run_id, stage, status, started_at)"
            " VALUES (?, ?, 'running', ?)"
            " ON CONFLICT (run_id, stage) DO UPDATE SET status = 'running',"
            " started_at = excluded.started_at, finished_at = NULL, error = NULL",
            (run_id, stage, self._now()),
        )

    def complete_stage(self, run_id: str, stage: str) -> None:
        self._conn.execute(
            "UPDATE stage_runs SET status = 'complete', finished_at = ?"
            " WHERE run_id = ? AND stage = ?",
            (self._now(), run_id, stage),
        )

    def fail_stage(self, run_id: str, stage: str, error: str) -> None:
        self._conn.execute(
            "UPDATE stage_runs SET status = 'failed', finished_at = ?, error = ?"
            " WHERE run_id = ? AND stage = ?",
            (self._now(), error, run_id, stage),
        )

    def get_stage(self, run_id: str, stage: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM stage_runs WHERE run_id = ? AND stage = ?", (run_id, stage)
        ).fetchone()
        return dict(row) if row else None

    # -- documents ----------------------------------------------------------
    def add_document(
        self, document: Document, *, status: str = "loaded", error: Optional[str] = None
    ) -> None:
        self._conn.execute(
            "INSERT INTO documents (run_id, doc_id, ordinal, path, uri, external_id,"
            " media_type, content_sha256, size_bytes, status, error, loaded_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                document.run_id,
                document.doc_id,
                document.ordinal,
                document.path,
                document.uri,
                document.external_id,
                document.media_type,
                document.content_sha256,
                document.size_bytes,
                status,
                error,
                self._now(),
            ),
        )

    def document_content_exists(self, run_id: str, content_sha256: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM documents WHERE run_id = ? AND content_sha256 = ?",
            (run_id, content_sha256),
        ).fetchone()
        return row is not None

    def list_documents(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM documents WHERE run_id = ? ORDER BY ordinal", (run_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    # -- catalogs and controls ---------------------------------------------
    def add_catalog(self, catalog: CatalogRow) -> None:
        self._conn.execute(
            "INSERT INTO catalogs (run_id, catalog_id, ordinal, uri, path, external_id,"
            " content_sha256, oscal_version, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                catalog.run_id,
                catalog.catalog_id,
                catalog.ordinal,
                catalog.uri,
                catalog.path,
                catalog.external_id,
                catalog.content_sha256,
                catalog.oscal_version,
                catalog.status,
            ),
        )

    def list_catalogs(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM catalogs WHERE run_id = ? ORDER BY ordinal", (run_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    def add_control(self, control: Control) -> None:
        self._conn.execute(
            "INSERT INTO controls (run_id, catalog_id, control_id, title, text, domain,"
            " family, path) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                control.run_id,
                control.catalog_id,
                control.control_id,
                control.title,
                control.text,
                control.domain,
                control.family,
                json.dumps(list(control.path)),
            ),
        )

    def add_controls(self, controls: Iterable[Control]) -> None:
        for control in controls:
            self.add_control(control)

    def list_controls(self, run_id: str, catalog_id: Optional[str] = None) -> list[Control]:
        if catalog_id is None:
            rows = self._conn.execute(
                "SELECT * FROM controls WHERE run_id = ? ORDER BY catalog_id, control_id",
                (run_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM controls WHERE run_id = ? AND catalog_id = ?"
                " ORDER BY control_id",
                (run_id, catalog_id),
            ).fetchall()
        return [
            Control(
                run_id=row["run_id"],
                catalog_id=row["catalog_id"],
                control_id=row["control_id"],
                title=row["title"],
                text=row["text"],
                domain=row["domain"],
                family=row["family"],
                path=tuple(json.loads(row["path"])),
            )
            for row in rows
        ]

    # -- requirements -------------------------------------------------------
    def add_requirement(self, requirement: Requirement) -> None:
        self._conn.execute(
            "INSERT INTO requirements (run_id, req_id, doc_id, ordinal, text,"
            " normalized_text, keyword, extract_status, gate_status, gate_noul_prob,"
            " gate_choice, retrieve_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                requirement.run_id,
                requirement.req_id,
                requirement.doc_id,
                requirement.ordinal,
                requirement.text,
                requirement.normalized_text,
                requirement.keyword.value if requirement.keyword else None,
                requirement.extract_status,
                requirement.gate_status,
                requirement.gate_noul_prob,
                requirement.gate_choice,
                requirement.retrieve_status,
            ),
        )

    def set_requirement_gate(
        self,
        run_id: str,
        req_id: str,
        *,
        gate_status: str,
        gate_noul_prob: Optional[float],
        gate_choice: Optional[str],
        keyword: Optional[str],
        extract_status: str,
    ) -> None:
        self._conn.execute(
            "UPDATE requirements SET extract_status = ?, gate_status = ?,"
            " gate_noul_prob = ?, gate_choice = ?, keyword = ?"
            " WHERE run_id = ? AND req_id = ?",
            (extract_status, gate_status, gate_noul_prob, gate_choice, keyword, run_id, req_id),
        )

    def set_requirement_retrieve_status(
        self, run_id: str, req_id: str, retrieve_status: str
    ) -> None:
        self._conn.execute(
            "UPDATE requirements SET retrieve_status = ? WHERE run_id = ? AND req_id = ?",
            (retrieve_status, run_id, req_id),
        )

    def get_requirement(self, run_id: str, req_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM requirements WHERE run_id = ? AND req_id = ?", (run_id, req_id)
        ).fetchone()
        return dict(row) if row else None

    def requirements_for_gate(self, run_id: str) -> list[Requirement]:
        rows = self._conn.execute(
            "SELECT * FROM requirements WHERE run_id = ? AND gate_status IS NULL"
            " ORDER BY req_id",
            (run_id,),
        ).fetchall()
        return [_requirement_from_row(row) for row in rows]

    def requirements_for_retrieval(self, run_id: str) -> list[Requirement]:
        rows = self._conn.execute(
            "SELECT * FROM requirements WHERE run_id = ? AND gate_status = 'passed'"
            " AND retrieve_status IS NULL ORDER BY req_id",
            (run_id,),
        ).fetchall()
        return [_requirement_from_row(row) for row in rows]

    def add_requirement_if_absent(self, requirement: Requirement) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO requirements (run_id, req_id, doc_id, ordinal, text,"
            " normalized_text, keyword, extract_status, gate_status, gate_noul_prob,"
            " gate_choice, retrieve_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                requirement.run_id,
                requirement.req_id,
                requirement.doc_id,
                requirement.ordinal,
                requirement.text,
                requirement.normalized_text,
                requirement.keyword.value if requirement.keyword else None,
                requirement.extract_status,
                requirement.gate_status,
                requirement.gate_noul_prob,
                requirement.gate_choice,
                requirement.retrieve_status,
            ),
        )

    def list_requirements(self, run_id: str) -> list[Requirement]:
        rows = self._conn.execute(
            "SELECT * FROM requirements WHERE run_id = ? ORDER BY ordinal, req_id", (run_id,)
        ).fetchall()
        return [_requirement_from_row(row) for row in rows]

    def has_evidence_response(
        self, run_id: str, stage: str, item_ref: str, call_type: str
    ) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM evidence WHERE run_id = ? AND stage = ? AND item_ref = ?"
            " AND call_type = ? AND response_json IS NOT NULL LIMIT 1",
            (run_id, stage, item_ref, call_type),
        ).fetchone()
        return row is not None

    def list_candidate_pairs(self, run_id: str) -> list[CandidatePair]:
        rows = self._conn.execute(
            "SELECT * FROM candidate_pairs WHERE run_id = ? ORDER BY pair_id", (run_id,)
        ).fetchall()
        return [self._pair_from_row(row) for row in rows]

    # -- candidate pairs and mappings --------------------------------------
    def add_candidate_pair(
        self, pair: CandidatePair, *, mapped_threshold: Optional[float] = None
    ) -> None:
        self._conn.execute(
            "INSERT INTO candidate_pairs (run_id, pair_id, req_id, catalog_id, control_id,"
            " verify_status, noul_prob, mapped_threshold) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                pair.run_id,
                pair.pair_id,
                pair.req_id,
                pair.catalog_id,
                pair.control_id,
                pair.verify_status,
                pair.noul_prob,
                mapped_threshold,
            ),
        )

    def set_pair_verify(
        self, run_id: str, pair_id: str, *, verify_status: str, noul_prob: Optional[float]
    ) -> None:
        self._conn.execute(
            "UPDATE candidate_pairs SET verify_status = ?, noul_prob = ?"
            " WHERE run_id = ? AND pair_id = ?",
            (verify_status, noul_prob, run_id, pair_id),
        )

    def set_pair_classify(
        self,
        run_id: str,
        pair_id: str,
        *,
        classify_status: str,
        relation: Optional[str] = None,
        confidence_percentage: Optional[float] = None,
        confidence_category: Optional[str] = None,
    ) -> None:
        self._conn.execute(
            "UPDATE candidate_pairs SET classify_status = ?, relation = ?,"
            " confidence_percentage = ?, confidence_category = ?"
            " WHERE run_id = ? AND pair_id = ?",
            (
                classify_status,
                relation,
                confidence_percentage,
                confidence_category,
                run_id,
                pair_id,
            ),
        )

    def get_candidate_pair(self, run_id: str, pair_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM candidate_pairs WHERE run_id = ? AND pair_id = ?", (run_id, pair_id)
        ).fetchone()
        return dict(row) if row else None

    def candidate_pairs_for_verify(self, run_id: str) -> list[CandidatePair]:
        rows = self._conn.execute(
            "SELECT * FROM candidate_pairs WHERE run_id = ? AND verify_status = 'pending'"
            " ORDER BY pair_id",
            (run_id,),
        ).fetchall()
        return [self._pair_from_row(row) for row in rows]

    def candidate_pairs_for_classify(self, run_id: str) -> list[CandidatePair]:
        rows = self._conn.execute(
            "SELECT * FROM candidate_pairs WHERE run_id = ? AND verify_status = 'passed'"
            " AND classify_status IS NULL ORDER BY pair_id",
            (run_id,),
        ).fetchall()
        return [self._pair_from_row(row) for row in rows]

    @staticmethod
    def _pair_from_row(row) -> CandidatePair:
        return CandidatePair(
            run_id=row["run_id"],
            pair_id=row["pair_id"],
            req_id=row["req_id"],
            catalog_id=row["catalog_id"],
            control_id=row["control_id"],
            verify_status=row["verify_status"],
            noul_prob=row["noul_prob"],
        )

    def add_mapping(self, record: MappingRecord, *, rationale: Optional[str] = None) -> None:
        map_uuid = self._ids.uuid_for(
            "map", f"{record.run_id}:{record.req_id}:{record.catalog_id}:{record.control_id}"
        )
        self._conn.execute(
            "INSERT INTO mappings (run_id, map_uuid, req_id, catalog_id, control_id, relation,"
            " confidence_percentage, confidence_category, rationale)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.run_id,
                map_uuid,
                record.req_id,
                record.catalog_id,
                record.control_id,
                record.relation.value,
                record.confidence_percentage,
                record.confidence_category,
                rationale,
            ),
        )

    def list_mappings(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM mappings WHERE run_id = ? ORDER BY map_uuid", (run_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    # -- domain index (content-keyed, cross-run) ---------------------------
    def add_domain_index(self, index: DomainIndex) -> None:
        self._conn.execute(
            "INSERT INTO domain_index (index_id, content_sha256, model_id, prompt_hash,"
            " index_json) VALUES (?, ?, ?, ?, ?)",
            (
                index.index_id,
                index.content_sha256,
                index.model_id,
                index.prompt_hash,
                json.dumps(dict(index.domains)),
            ),
        )

    def get_domain_index(
        self, content_sha256: str, model_id: str, prompt_hash: str
    ) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM domain_index WHERE content_sha256 = ? AND model_id = ?"
            " AND prompt_hash = ?",
            (content_sha256, model_id, prompt_hash),
        ).fetchone()
        return dict(row) if row else None

    # -- attempts and evidence ---------------------------------------------
    def record_attempt(
        self,
        *,
        run_id: str,
        stage: str,
        item_ref: str,
        call_type: str,
        attempt_no: int,
        http_status: Optional[int] = None,
        error_class: Optional[str] = None,
        error: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> str:
        attempt_id = self._ids.uuid_for(
            "attempt", f"{run_id}:{stage}:{item_ref}:{call_type}:{attempt_no}"
        )
        self._conn.execute(
            "INSERT INTO attempts (attempt_id, run_id, stage, item_ref, call_type, attempt_no,"
            " http_status, error_class, error, duration_ms, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (attempt_id) DO UPDATE SET http_status = excluded.http_status,"
            " error_class = excluded.error_class, error = excluded.error,"
            " duration_ms = excluded.duration_ms, created_at = excluded.created_at",
            (
                attempt_id,
                run_id,
                stage,
                item_ref,
                call_type,
                attempt_no,
                http_status,
                error_class,
                error,
                duration_ms,
                self._now(),
            ),
        )
        return attempt_id

    def record_evidence(
        self,
        *,
        run_id: str,
        stage: str,
        item_ref: str,
        call_type: str,
        request: Any,
        response: Any = None,
        request_sha256: Optional[str] = None,
        http_status: Optional[int] = None,
        attempt_no: Optional[int] = None,
        prompt_hash: Optional[str] = None,
    ) -> str:
        request_bytes = json.dumps(
            redact(request), sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
        digest = request_sha256 or sha256_hex(request_bytes)
        evidence_id = self._ids.uuid_for(
            "evidence", f"{run_id}:{item_ref}:{call_type}:{digest}"
        )
        response_blob = None
        if response is not None:
            response_blob = zlib.compress(
                json.dumps(
                    redact(response), sort_keys=True, separators=(",", ":"), default=str
                ).encode("utf-8")
            )
        self._conn.execute(
            "INSERT INTO evidence (evidence_id, run_id, stage, item_ref, call_type,"
            " request_json, response_json, request_sha256, http_status, attempt_no,"
            " prompt_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (run_id, item_ref, call_type, request_sha256) DO UPDATE SET"
            " response_json = excluded.response_json, http_status = excluded.http_status,"
            " attempt_no = excluded.attempt_no, prompt_hash = excluded.prompt_hash",
            (
                evidence_id,
                run_id,
                stage,
                item_ref,
                call_type,
                zlib.compress(request_bytes),
                response_blob,
                digest,
                http_status,
                attempt_no,
                prompt_hash,
                self._now(),
            ),
        )
        return evidence_id

    def list_evidence(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM evidence WHERE run_id = ? ORDER BY created_at, evidence_id",
            (run_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def counts(self, run_id: str) -> dict[str, int]:
        tables = (
            "documents",
            "catalogs",
            "controls",
            "requirements",
            "candidate_pairs",
            "mappings",
            "evidence",
            "attempts",
        )
        result: dict[str, int] = {}
        for table in tables:
            row = self._conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE run_id = ?", (run_id,)
            ).fetchone()
            result[table] = int(row[0])
        return result
