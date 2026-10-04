import json
import sqlite3
from datetime import datetime, timezone

import httpx
import respx

from smeargle.config import Settings
from smeargle.domain.clock import FrozenClock
from smeargle.domain.ids import UuidIdFactory
from smeargle.pipeline import run as run_pipeline
from smeargle.store.run_store import RunStore


def _clock():
    return FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc))


def _settings(tmp_path):
    settings = Settings.load()
    settings.output = tmp_path / "out"
    settings.state_dir = tmp_path / "state"
    settings.llm.endpoint = "https://llm.example"
    settings.llm.model = "test-model"
    settings.jev.endpoint = "https://jev.example"
    settings.jev.model = "jev-model"
    return settings


def _chat(content):
    return {"choices": [{"message": {"content": content}}]}


def _answers(answer, confidence):
    return {"answers": [{"question": "q", "answer": answer, "answer_confidence": confidence}]}


def _fixtures(tmp_path):
    document = tmp_path / "spec.txt"
    document.write_text("MUST a. MUST b.", encoding="utf-8")
    catalog = tmp_path / "vendor.json"
    catalog.write_text(
        json.dumps({"catalog": {"name": "V", "securityControls": [
            {"controlId": "1.1", "title": "Policy", "family": "Access"}]}}),
        encoding="utf-8",
    )
    return document, catalog


def _mock_all():
    def chat_router(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        if "extract normative requirements" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"requirements": [
                {"text": "MUST a", "keyword": "MUST"}, {"text": "MUST b", "keyword": "MUST"}]})))
        if "classify security controls" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"labels": [
                {"control_id": "c-1.1", "domain": "access", "family": "Access"}]})))
        if "control domains" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"domains": ["access"]})))
        return httpx.Response(200, json=_chat(json.dumps({"control_ids": ["c-1.1"]})))

    respx.post("https://llm.example/v1/chat/completions").mock(side_effect=chat_router)
    respx.post("https://jev.example/v1/systemone").mock(
        return_value=httpx.Response(200, json=_answers("MUST", 0.9))
    )


def _run(settings, document, catalog, run_id):
    return run_pipeline.run_pipeline(
        state_dir=settings.state_dir, output=settings.output, input_paths=[document],
        catalog_paths=[catalog], settings=settings, clock=_clock(),
        id_factory=UuidIdFactory(), run_id=run_id,
    )


@respx.mock
def test_persistence_is_independent_of_completion_order(tmp_path):
    _mock_all()
    first_settings = _settings(tmp_path / "a")
    first_settings.state_dir.mkdir(parents=True, exist_ok=True)
    document, catalog = _fixtures(tmp_path)
    _run(first_settings, document, catalog, "run-A")
    second_settings = _settings(tmp_path / "b")
    second_settings.state_dir.mkdir(parents=True, exist_ok=True)
    _run(second_settings, document, catalog, "run-A")
    with RunStore.open(first_settings.state_dir) as store:
        first = [r.req_id for r in store.list_requirements("run-A")]
    with RunStore.open(second_settings.state_dir) as store:
        second = [r.req_id for r in store.list_requirements("run-A")]
    assert first == second


@respx.mock
def test_resume_does_not_duplicate_evidence(tmp_path):
    _mock_all()
    settings = _settings(tmp_path)
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    document, catalog = _fixtures(tmp_path)
    _run(settings, document, catalog, "run-A")

    with RunStore.open(settings.state_dir) as store:
        before = len(store.list_evidence("run-A"))
    _run(settings, document, catalog, "run-A")
    with RunStore.open(settings.state_dir) as store:
        assert len(store.list_evidence("run-A")) == before


@respx.mock
def test_incomplete_chunk_stage_is_reissued_on_resume(tmp_path):
    calls = {"count": 0}

    def chat_router(request):
        calls["count"] += 1
        prompt = json.loads(request.content)["messages"][0]["content"]
        if "classify security controls" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"labels": []})))
        if "control domains" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"domains": []})))
        return httpx.Response(200, json=_chat(json.dumps({"requirements": [{"text": "MUST x", "keyword": "MUST"}]})))

    respx.post("https://llm.example/v1/chat/completions").mock(side_effect=chat_router)
    respx.post("https://jev.example/v1/systemone").mock(
        return_value=httpx.Response(200, json=_answers("MUST", 0.9))
    )
    settings = _settings(tmp_path)
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    document, catalog = _fixtures(tmp_path)
    _run(settings, document, catalog, "run-A")
    first = calls["count"]

    connection = sqlite3.connect(settings.state_dir / "smeargle.db")
    connection.execute(
        "DELETE FROM stage_runs WHERE run_id = 'run-A' AND stage LIKE 'extract:doc:%'"
    )
    connection.commit()
    connection.close()

    _run(settings, document, catalog, "run-A")
    assert calls["count"] == first + 1


@respx.mock
def test_stage_runs_are_marked_complete(tmp_path):
    _mock_all()
    settings = _settings(tmp_path)
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    document, catalog = _fixtures(tmp_path)
    _run(settings, document, catalog, "run-A")
    with RunStore.open(settings.state_dir) as store:
        for stage in ("extract", "retrieve", "verify", "classify"):
            row = store.get_stage("run-A", stage)
            assert row is not None and row["status"] == "complete"
