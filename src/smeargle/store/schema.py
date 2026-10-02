"""Schema DDL and `PRAGMA user_version` migrations (spec 7)."""

from __future__ import annotations

import sqlite3

from smeargle.errors import StoreError

SCHEMA_VERSION = 1

MIGRATION_1 = """
CREATE TABLE runs (
    run_id        TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    config_hash   TEXT NOT NULL,
    status        TEXT NOT NULL,
    oscal_version TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    finished_at   TEXT
);
CREATE INDEX idx_runs_fingerprint ON runs (fingerprint, created_at DESC);

CREATE TABLE documents (
    run_id         TEXT NOT NULL,
    doc_id         TEXT NOT NULL,
    ordinal        INTEGER NOT NULL,
    path           TEXT NOT NULL,
    uri            TEXT NOT NULL,
    external_id    TEXT,
    media_type     TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    size_bytes     INTEGER NOT NULL,
    status         TEXT NOT NULL,
    error          TEXT,
    loaded_at      TEXT NOT NULL,
    PRIMARY KEY (run_id, doc_id),
    UNIQUE (run_id, content_sha256),
    UNIQUE (run_id, ordinal),
    FOREIGN KEY (run_id) REFERENCES runs (run_id)
);

CREATE TABLE requirements (
    run_id          TEXT NOT NULL,
    req_id          TEXT NOT NULL,
    doc_id          TEXT NOT NULL,
    ordinal         INTEGER NOT NULL,
    text            TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    keyword         TEXT,
    extract_status  TEXT NOT NULL,
    gate_status     TEXT,
    gate_noul_prob  REAL,
    gate_choice     TEXT,
    retrieve_status TEXT,
    PRIMARY KEY (run_id, req_id),
    UNIQUE (run_id, doc_id, normalized_text),
    FOREIGN KEY (run_id) REFERENCES runs (run_id)
);

CREATE TABLE catalogs (
    run_id         TEXT NOT NULL,
    catalog_id     TEXT NOT NULL,
    ordinal        INTEGER NOT NULL,
    uri            TEXT NOT NULL,
    path           TEXT NOT NULL,
    external_id    TEXT,
    content_sha256 TEXT NOT NULL,
    oscal_version  TEXT,
    status         TEXT NOT NULL,
    PRIMARY KEY (run_id, catalog_id),
    FOREIGN KEY (run_id) REFERENCES runs (run_id)
);

CREATE TABLE controls (
    run_id     TEXT NOT NULL,
    catalog_id TEXT NOT NULL,
    control_id TEXT NOT NULL,
    title      TEXT NOT NULL,
    text       TEXT NOT NULL,
    domain     TEXT NOT NULL,
    family     TEXT NOT NULL,
    path       TEXT NOT NULL,
    PRIMARY KEY (run_id, catalog_id, control_id),
    FOREIGN KEY (run_id, catalog_id) REFERENCES catalogs (run_id, catalog_id)
);

CREATE TABLE domain_index (
    index_id       TEXT PRIMARY KEY,
    content_sha256 TEXT NOT NULL,
    model_id       TEXT NOT NULL,
    prompt_hash    TEXT NOT NULL,
    index_json     TEXT NOT NULL,
    UNIQUE (content_sha256, model_id, prompt_hash)
);

CREATE TABLE candidate_pairs (
    run_id                TEXT NOT NULL,
    pair_id               TEXT NOT NULL,
    req_id                TEXT NOT NULL,
    catalog_id            TEXT NOT NULL,
    control_id            TEXT NOT NULL,
    verify_status         TEXT NOT NULL,
    noul_prob             REAL,
    mapped_threshold      REAL,
    classify_status       TEXT,
    relation              TEXT,
    confidence_percentage REAL,
    confidence_category   TEXT,
    PRIMARY KEY (run_id, pair_id),
    UNIQUE (run_id, req_id, catalog_id, control_id),
    FOREIGN KEY (run_id) REFERENCES runs (run_id)
);

CREATE TABLE mappings (
    run_id                TEXT NOT NULL,
    map_uuid              TEXT NOT NULL,
    req_id                TEXT NOT NULL,
    catalog_id            TEXT NOT NULL,
    control_id            TEXT NOT NULL,
    relation              TEXT NOT NULL,
    confidence_percentage REAL,
    confidence_category   TEXT,
    rationale             TEXT,
    PRIMARY KEY (run_id, map_uuid),
    UNIQUE (run_id, req_id, catalog_id, control_id),
    FOREIGN KEY (run_id) REFERENCES runs (run_id)
);

CREATE TABLE attempts (
    attempt_id  TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL,
    stage       TEXT NOT NULL,
    item_ref    TEXT NOT NULL,
    call_type   TEXT NOT NULL,
    attempt_no  INTEGER NOT NULL,
    http_status INTEGER,
    error_class TEXT,
    error       TEXT,
    duration_ms INTEGER,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs (run_id)
);

CREATE TABLE evidence (
    evidence_id    TEXT PRIMARY KEY,
    run_id         TEXT NOT NULL,
    stage          TEXT NOT NULL,
    item_ref       TEXT NOT NULL,
    call_type      TEXT NOT NULL,
    request_json   BLOB,
    response_json  BLOB,
    request_sha256 TEXT NOT NULL,
    http_status    INTEGER,
    attempt_no     INTEGER,
    prompt_hash    TEXT,
    created_at     TEXT NOT NULL,
    UNIQUE (run_id, item_ref, call_type, request_sha256),
    FOREIGN KEY (run_id) REFERENCES runs (run_id)
);

CREATE TABLE stage_runs (
    run_id      TEXT NOT NULL,
    stage       TEXT NOT NULL,
    status      TEXT NOT NULL,
    cursor      TEXT,
    started_at  TEXT,
    finished_at TEXT,
    error       TEXT,
    PRIMARY KEY (run_id, stage),
    FOREIGN KEY (run_id) REFERENCES runs (run_id)
);
"""

MIGRATIONS: tuple[str, ...] = (MIGRATION_1,)


def current_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def migrate(conn: sqlite3.Connection) -> None:
    version = current_version(conn)
    if version > SCHEMA_VERSION:
        raise StoreError(
            f"database schema version {version} is newer than supported {SCHEMA_VERSION}"
        )
    for target, script in enumerate(MIGRATIONS[version:], start=version + 1):
        conn.executescript(script)
        conn.execute(f"PRAGMA user_version = {int(target)}")
