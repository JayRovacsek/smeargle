import json
import os
import subprocess
import sys

from fakes.servers import FakeHttpService, jev_responder, llm_responder

from smeargle.store.run_store import RunStore


def _fixtures(tmp_path):
    document = tmp_path / "spec.txt"
    document.write_text("The system MUST encrypt data at rest.", encoding="utf-8")
    catalog = tmp_path / "vendor.json"
    catalog.write_text(
        json.dumps({"catalog": {"name": "V", "securityControls": [
            {"controlId": "1.1", "title": "Policy", "family": "Access"}]}}),
        encoding="utf-8",
    )
    return document, catalog


def _invoke(tmp_path, document, catalog, llm, jev, run_id):
    return subprocess.run(
        [
            sys.executable, "-m", "smeargle",
            "--state-dir", str(tmp_path / "state"), "--output", str(tmp_path / "out"),
            "--yes", "--run-id", run_id,
            "--llm-endpoint", llm.url, "--jev-endpoint", jev.url,
            "run", "-i", str(document), "-c", str(catalog),
        ],
        capture_output=True, text=True, env=os.environ.copy(), timeout=120,
    )


def test_phase3_run_operates_end_to_end(tmp_path):
    document, catalog = _fixtures(tmp_path)
    with FakeHttpService(llm_responder) as llm, FakeHttpService(jev_responder) as jev:
        result = _invoke(tmp_path, document, catalog, llm, jev, "run-e2e")
    assert result.returncode == 0, result.stderr
    with RunStore.open(tmp_path / "state") as store:
        counts = store.counts("run-e2e")
        assert counts["requirements"] == 1
        assert counts["candidate_pairs"] == 1
        assert counts["mappings"] == 1


def test_phase3_resume_issues_no_new_calls(tmp_path):
    document, catalog = _fixtures(tmp_path)
    with FakeHttpService(llm_responder) as llm, FakeHttpService(jev_responder) as jev:
        assert _invoke(tmp_path, document, catalog, llm, jev, "run-e2e").returncode == 0
        llm_calls, jev_calls = llm.calls, jev.calls
        resume = _invoke(tmp_path, document, catalog, llm, jev, "run-e2e")
        assert resume.returncode == 0, resume.stderr
        assert llm.calls == llm_calls
        assert jev.calls == jev_calls
    with RunStore.open(tmp_path / "state") as store:
        counts = store.counts("run-e2e")
        assert counts["mappings"] == 1
