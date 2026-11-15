import json
import os
import subprocess
import sys

from fakes.servers import FakeHttpService, jev_responder, llm_responder
from support.schemas import validate_against_schema

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
    env = {key: value for key, value in os.environ.items() if not key.startswith("SMEARGLE_")}
    proxy_bypass = "127.0.0.1,localhost"
    existing_bypass = env.get("NO_PROXY") or env.get("no_proxy")
    if existing_bypass:
        proxy_bypass = f"{proxy_bypass},{existing_bypass}"
    env["NO_PROXY"] = proxy_bypass
    env["no_proxy"] = proxy_bypass
    return subprocess.run(
        [
            sys.executable, "-m", "smeargle",
            "--state-dir", str(tmp_path / "state"), "--output", str(tmp_path / "out"),
            "--yes", "--run-id", run_id,
            "--llm-base-url", llm.url, "--jev-base-url", jev.url,
            "--jev-transport", "systemone",
            "run", "-i", str(document), "-c", str(catalog),
        ],
        capture_output=True, text=True, env=env, timeout=120,
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
        assert store.get_run("run-e2e")["status"] == "mapped"
        for stage in ("extract", "retrieve", "verify", "classify"):
            assert store.get_stage("run-e2e", stage)["status"] == "complete"

    emitted = json.loads(
        (tmp_path / "out" / "catalogs" / "vendor.json").read_text(encoding="utf-8")
    )
    validate_against_schema("catalog", emitted)


def test_phase3_resume_issues_no_new_calls(tmp_path):
    document, catalog = _fixtures(tmp_path)
    with FakeHttpService(llm_responder) as llm, FakeHttpService(jev_responder) as jev:
        assert _invoke(tmp_path, document, catalog, llm, jev, "run-e2e").returncode == 0
        llm_calls, jev_calls = llm.calls, jev.calls
        assert llm_calls > 0 and jev_calls > 0
        resume = _invoke(tmp_path, document, catalog, llm, jev, "run-e2e")
        assert resume.returncode == 0, resume.stderr
        assert llm.calls == llm_calls
        assert jev.calls == jev_calls
    with RunStore.open(tmp_path / "state") as store:
        counts = store.counts("run-e2e")
        assert counts["mappings"] == 1
