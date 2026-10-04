import json

from smeargle.oscal_build import emit


def _record(**overrides):
    base = {
        "evidence_id": "e1", "run_id": "run-1", "stage": "extract",
        "item_ref": "gate:req-1", "call_type": "jev_gate", "attempt_no": 1,
        "http_status": 200, "request_sha256": "abc", "prompt_hash": "p1",
        "request": {"api_key": "[REDACTED]", "prompt": "hi"},
        "response": {"answer": "ok"},
    }
    base.update(overrides)
    return base


def test_exports_one_record_per_call_with_metadata(tmp_path):
    (path,) = emit.export_evidence((_record(),), tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["stage"] == "extract"
    assert payload["item_ref"] == "gate:req-1"
    assert payload["call_type"] == "jev_gate"
    assert payload["attempt_no"] == 1
    assert payload["http_status"] == 200
    assert payload["request_sha256"] == "abc"
    assert payload["prompt_hash"] == "p1"


def test_export_filenames_are_deterministic_and_sanitised(tmp_path):
    first = emit.export_evidence((_record(),), tmp_path / "a")
    second = emit.export_evidence((_record(),), tmp_path / "b")
    assert first[0].name == second[0].name
    assert ":" not in first[0].name and "/" not in first[0].name
    # The same (stage, item_ref, call_type, attempt_no) with different request_sha256
    # (repair-loop / fallback attempts) must not overwrite each other.
    distinct = emit.export_evidence(
        (_record(request_sha256="abc"), _record(request_sha256="def")), tmp_path / "c"
    )
    assert len({path.name for path in distinct}) == 2


def test_export_redacts_secrets_again_as_defence_in_depth(tmp_path):
    (path,) = emit.export_evidence(
        (_record(request={"authorization": "Bearer leaked"}),), tmp_path
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["request"]["authorization"] == "[REDACTED]"
