import pytest

from smeargle.errors import StoreError
from smeargle.store import db, schema


def test_connect_sets_pragmas(tmp_path):
    conn = db.connect(tmp_path)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    conn.close()


def test_migrate_sets_user_version_and_is_idempotent(tmp_path):
    conn = db.connect(tmp_path)
    schema.migrate(conn)
    assert schema.current_version(conn) == schema.SCHEMA_VERSION
    schema.migrate(conn)
    assert schema.current_version(conn) == schema.SCHEMA_VERSION
    names = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {
        "runs",
        "documents",
        "requirements",
        "catalogs",
        "controls",
        "domain_index",
        "candidate_pairs",
        "mappings",
        "attempts",
        "evidence",
        "stage_runs",
    } <= names
    conn.close()


def test_migrate_refuses_newer_database(tmp_path):
    conn = db.connect(tmp_path)
    conn.execute("PRAGMA user_version = 999")
    conn.commit()
    with pytest.raises(StoreError):
        schema.migrate(conn)
    conn.close()


def test_transaction_rolls_back_on_error(tmp_path):
    conn = db.connect(tmp_path)
    schema.migrate(conn)
    conn.execute(
        "INSERT INTO runs (run_id, fingerprint, config_hash, status, oscal_version, created_at, updated_at)"
        " VALUES ('r', 'f', 'c', 'started', '1.2.3', 't', 't')"
    )
    conn.commit()
    with pytest.raises(ValueError):
        with db.transaction(conn):
            conn.execute("UPDATE runs SET status='changed' WHERE run_id='r'")
            raise ValueError("boom")
    status = conn.execute("SELECT status FROM runs WHERE run_id='r'").fetchone()[0]
    assert status == "started"
    conn.close()
