import json
import sqlite3

from support.schemas import validate_against_schema

from smeargle.cli import main


def test_phase2_run_ingests_and_emits_valid_catalog(tmp_path):
    document = tmp_path / "spec.txt"
    document.write_text("The system MUST encrypt data at rest.", encoding="utf-8")
    catalog = tmp_path / "vendor.json"
    catalog.write_text(
        json.dumps(
            {
                "catalog": {
                    "name": "Vendor Controls",
                    "securityControls": [
                        {
                            "controlId": "1.1",
                            "title": "Policy",
                            "family": "Access Control",
                            "description": "Establish a policy.",
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    state = tmp_path / "state"
    output = tmp_path / "out"

    code = main(
        [
            "--state-dir",
            str(state),
            "--output",
            str(output),
            "--yes",
            "run",
            "-i",
            str(document),
            "-c",
            str(catalog),
        ]
    )

    assert code == 0

    conn = sqlite3.connect(state / "smeargle.db")
    try:
        run_count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        document_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        catalog_count = conn.execute("SELECT COUNT(*) FROM catalogs").fetchone()[0]
        control_count = conn.execute("SELECT COUNT(*) FROM controls").fetchone()[0]
        assert (run_count, document_count, catalog_count, control_count) == (1, 1, 1, 1)
    finally:
        conn.close()

    emitted = json.loads((output / "catalogs" / "vendor.json").read_text(encoding="utf-8"))
    validate_against_schema("catalog", emitted)
    assert emitted["catalog"]["metadata"]["oscal-version"] == "1.2.3"
