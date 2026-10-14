import json
import os
import subprocess
from pathlib import Path

import pytest
from fakes.servers import FakeHttpService, jev_responder, llm_responder
from support.artifacts import validate_output

from smeargle.oscal_build import facade


def _binary() -> str:
    path = Path("result/bin/smeargle")
    if not path.exists():
        pytest.skip("run `nix build .#smeargle` first so result/bin/smeargle exists")
    return str(path)


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
            _binary(), "--state-dir", str(tmp_path / "state"),
            "--output", str(tmp_path / "out"), "--yes", "--run-id", run_id,
            "--llm-base-url", llm.url, "--jev-base-url", jev.url,
            "run", "-i", str(document), "-c", str(catalog),
        ],
        capture_output=True, text=True, env=os.environ.copy(), timeout=120,
    )


def test_installed_binary_emits_and_validates_full_output_tree(tmp_path):
    facade.configure_support_file(tmp_path / "support.db")
    document, catalog = _fixtures(tmp_path)
    with FakeHttpService(llm_responder) as llm, FakeHttpService(jev_responder) as jev:
        result = _invoke(tmp_path, document, catalog, llm, jev, "run-e2e")
    assert result.returncode == 0, result.stderr
    output = tmp_path / "out"
    assert sorted(path.name for path in output.iterdir() if path.is_file()) == [
        "mapping-collection.json", "profile.json", "rationale.json",
        "requirements-catalog.json",
    ]
    assert list((output / "catalogs").glob("*.json"))
    assert list((output / "evidence").glob("*.json"))
    assert sorted(validate_output(output)) == [
        "mapping-collection.json", "profile.json", "rationale.json",
        "requirements-catalog.json",
    ]


def test_installed_binary_zero_relation_run_omits_mapping_collection(tmp_path):
    facade.configure_support_file(tmp_path / "support.db")

    def empty_llm(path, body):
        prompt = body["messages"][0]["content"]
        if "extract normative requirements" in prompt:
            content = {"requirements": [
                {"text": "The system MUST encrypt data at rest.", "keyword": "MUST"}]}
        elif "classify security controls" in prompt:
            content = {"labels": []}  # IndexResponseModel
        elif "control domains" in prompt:
            content = {"domains": []}  # DomainSelectionModel
        else:
            content = {"control_ids": []}  # NominationResponseModel
        return {"choices": [{"message": {"content": json.dumps(content)}}]}

    def empty_jev(path, body):
        question = next(iter(body["questions"].values()))
        if question["type"] == "noul":
            payload = {"type": "noul", "action": {"act_probability": 1}, "confidence": 0.9, "noul": 0.9}
        else:
            payload = {
                "type": "choice", "action": {"act_probability": 1}, "confidence": 0.9,
                "choice": "MUST", "probabilities": {"MUST": 0.9},
            }
        return {"answers": {"q0": payload}}

    document, catalog = _fixtures(tmp_path)
    with FakeHttpService(empty_llm) as llm, FakeHttpService(empty_jev) as jev:
        result = _invoke(tmp_path, document, catalog, llm, jev, "run-gap")
    assert result.returncode == 6, result.stderr
    assert not (tmp_path / "out" / "mapping-collection.json").exists()
    assert (tmp_path / "out" / "requirements-catalog.json").exists()
