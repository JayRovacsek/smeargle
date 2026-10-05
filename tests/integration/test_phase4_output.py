import json
from datetime import datetime, timezone

import httpx
import respx
from support.schemas import validate_against_schema

from smeargle.config import Settings
from smeargle.domain.clock import FrozenClock
from smeargle.domain.ids import UuidIdFactory
from smeargle.oscal_build import facade
from smeargle.pipeline import run as run_pipeline


def _clock():
    return FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc))


def _settings(tmp_path):
    settings = Settings.load()
    settings.state_dir = tmp_path / "state"
    settings.output = tmp_path / "out"
    settings.llm.endpoint = "https://llm.example"
    settings.llm.model = "test-model"
    settings.jev.endpoint = "https://jev.example"
    settings.jev.model = "jev-model"
    return settings


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


def _chat(content):
    return {"choices": [{"message": {"content": json.dumps(content)}}]}


def _answers(answer, confidence):
    return {"answers": [{"question": "q", "answer": answer, "answer_confidence": confidence}]}


def _mock_endpoints():
    def llm(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        if "extract normative requirements" in prompt:
            return httpx.Response(200, json=_chat({"requirements": [
                {"text": "The system MUST encrypt data at rest.", "keyword": "MUST"}]}))
        if "classify security controls" in prompt:
            return httpx.Response(200, json=_chat({"labels": [
                {"control_id": "c-1.1", "domain": "access", "family": "Access"}]}))
        if "control domains" in prompt:
            return httpx.Response(200, json=_chat({"domains": ["access"]}))
        return httpx.Response(200, json=_chat({"control_ids": ["c-1.1"]}))

    respx.post("https://llm.example/v1/chat/completions").mock(side_effect=llm)
    respx.post("https://jev.example/v1/systemone").mock(side_effect=[
        httpx.Response(200, json=_answers("yes", 0.9)),
        httpx.Response(200, json=_answers("MUST", 0.9)),
        httpx.Response(200, json=_answers("yes", 0.9)),
        httpx.Response(200, json=_answers("subset-of", 0.85)),
    ])


@respx.mock
def test_full_run_output_validates_against_vendored_schemas(tmp_path):
    facade.configure_support_file(tmp_path / "support.db")
    _mock_endpoints()
    settings = _settings(tmp_path)
    document, catalog = _fixtures(tmp_path)
    result = run_pipeline.run_pipeline(
        state_dir=settings.state_dir, output=settings.output,
        input_paths=[document], catalog_paths=[catalog], settings=settings,
        clock=_clock(), id_factory=UuidIdFactory(), run_id="run-a",
    )
    assert result.gaps == 0
    validate_against_schema(
        "catalog", json.loads((settings.output / "requirements-catalog.json").read_text())
    )
    validate_against_schema(
        "profile", json.loads((settings.output / "profile.json").read_text())
    )
    validate_against_schema(
        "mapping-collection",
        json.loads((settings.output / "mapping-collection.json").read_text()),
    )
    assert json.loads((settings.output / "rationale.json").read_text())["run"]["run_id"] == "run-a"


def test_vendored_schema_rejects_adversarial_mapping():
    import jsonschema_rs
    import pytest

    with pytest.raises(jsonschema_rs.ValidationError):
        validate_against_schema(
            "mapping-collection",
            {"mapping-collection": {"uuid": "not-a-uuid", "metadata": {},
                                    "provenance": {}, "mappings": []}},
        )


def test_assembly_is_value_identical_for_the_same_ledger(tmp_path):
    from support.ledger import CLOCK, IDS, ledger

    from smeargle.oscal_build import emit

    source = ledger()
    first = emit.assemble(source, clock=CLOCK, id_factory=IDS)
    second = emit.assemble(source, clock=CLOCK, id_factory=IDS)
    for key in ("requirements_catalog", "profile", "mapping_collection", "rationale"):
        assert json.dumps(getattr(first, key), sort_keys=True) == json.dumps(
            getattr(second, key), sort_keys=True
        )
