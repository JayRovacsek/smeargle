"""SQLite connection, pragmas, and transaction handling (spec 7)."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DB_FILENAME = "smeargle.db"
PRAGMAS = (
    "journal_mode=WAL",
    "synchronous=NORMAL",
    "foreign_keys=ON",
    "busy_timeout=5000",
)


def connect(state_dir: Path) -> sqlite3.Connection:
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(state_dir / DB_FILENAME)
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None
    for pragma in PRAGMAS:
        conn.execute(f"PRAGMA {pragma}")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
