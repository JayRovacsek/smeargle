import json
import sqlite3
import time
from datetime import datetime, timezone

import httpx
import respx

from smeargle.config import Settings
from smeargle.domain.clock import FrozenClock
from smeargle.domain.ids import UuidIdFactory
from smeargle.pipeline import run as run_pipeline
from smeargle.store.db import DB_FILENAME
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
    documents = []
    for name, text in (("spec-a.txt", "MUST alpha."), ("spec-b.txt", "MUST beta.")):
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        documents.append(path)
    catalog = tmp_path / "vendor.json"
    catalog.write_text(
        json.dumps({"catalog": {"name": "V", "securityControls": [
            {"controlId": "1.1", "title": "Policy", "family": "Access"}]}}),
        encoding="utf-8",
    )
    return documents, catalog


def _mock_all(*, llm_calls=None, jev_calls=None):
    def chat_router(request):
        if llm_calls is not None:
            llm_calls["n"] += 1
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

    def jev_router(request):
        if jev_calls is not None:
            jev_calls["n"] += 1
        return httpx.Response(200, json=_answers("MUST", 0.9))

    respx.post("https://llm.example/v1/chat/completions").mock(side_effect=chat_router)
    respx.post("https://jev.example/v1/systemone").mock(side_effect=jev_router)


def _mock_extraction_delays(delays):
    def chat_router(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        if "extract normative requirements" in prompt:
            for marker, delay in delays.items():
                if marker in prompt:
                    if delay:
                        time.sleep(delay)
                    return httpx.Response(200, json=_chat(json.dumps({"requirements": [
                        {"text": f"MUST {marker}", "keyword": "MUST"}]})))
            return httpx.Response(200, json=_chat(json.dumps({"requirements": []})))
        if "classify security controls" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"labels": [
                {"control_id": "c-1.1", "domain": "access", "family": "Access"}]})))
        if "control domains" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"domains": ["access"]})))
        return httpx.Response(200, json=_chat(json.dumps({"control_ids": ["c-1.1"]})))

    respx.post("https://llm.example/v1/chat/completions").mock(side_effect=chat_router)
    respx.post("https://jev.example/v1/systemone").mock(
        side_effect=lambda request: httpx.Response(200, json=_answers("MUST", 0.9))
    )


def _run(settings, documents, catalog, run_id):
    return run_pipeline.run_pipeline(
        state_dir=settings.state_dir, output=settings.output, input_paths=list(documents),
        catalog_paths=[catalog], settings=settings, clock=_clock(),
        id_factory=UuidIdFactory(), run_id=run_id,
    )


@respx.mock
def test_persistence_is_independent_of_completion_order(tmp_path):
    delays = {"alpha": 0.1, "beta": 0.0}
    _mock_extraction_delays(delays)
    documents, catalog = _fixtures(tmp_path)

    first_settings = _settings(tmp_path / "a")
    first_settings.state_dir.mkdir(parents=True, exist_ok=True)
    _run(first_settings, documents, catalog, "run-A")

    delays["alpha"] = 0.0
    delays["beta"] = 0.1
    second_settings = _settings(tmp_path / "b")
    second_settings.state_dir.mkdir(parents=True, exist_ok=True)
    _run(second_settings, documents, catalog, "run-A")

    with RunStore.open(first_settings.state_dir) as store:
        first = [r.req_id for r in store.list_requirements("run-A")]
    with RunStore.open(second_settings.state_dir) as store:
        second = [r.req_id for r in store.list_requirements("run-A")]
    assert first
    assert len(first) >= 2
    assert first == second


@respx.mock
def test_resume_does_not_duplicate_evidence(tmp_path):
    llm_calls = {"n": 0}
    jev_calls = {"n": 0}
    _mock_all(llm_calls=llm_calls, jev_calls=jev_calls)
    settings = _settings(tmp_path)
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    documents, catalog = _fixtures(tmp_path)
    _run(settings, documents, catalog, "run-A")

    with RunStore.open(settings.state_dir) as store:
        before = len(store.list_evidence("run-A"))
    assert before > 0
    assert llm_calls["n"] > 0
    assert jev_calls["n"] > 0

    llm_after_first = llm_calls["n"]
    jev_after_first = jev_calls["n"]
    _run(settings, documents, catalog, "run-A")
    assert llm_calls["n"] == llm_after_first
    assert jev_calls["n"] == jev_after_first
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
        side_effect=lambda request: httpx.Response(200, json=_answers("MUST", 0.9))
    )
    settings = _settings(tmp_path)
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    documents, catalog = _fixtures(tmp_path)
    _run(settings, documents, catalog, "run-A")
    first = calls["count"]
    assert first > 0

    with sqlite3.connect(settings.state_dir / DB_FILENAME) as connection:
        connection.execute(
            "DELETE FROM stage_runs WHERE run_id = 'run-A' AND stage LIKE 'extract:doc:%'"
        )
        connection.commit()

    _run(settings, documents, catalog, "run-A")
    assert calls["count"] == first + len(documents)


@respx.mock
def test_stage_runs_are_marked_complete(tmp_path):
    _mock_all()
    settings = _settings(tmp_path)
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    documents, catalog = _fixtures(tmp_path)
    _run(settings, documents, catalog, "run-A")
    with RunStore.open(settings.state_dir) as store:
        for stage in ("extract", "retrieve", "verify", "classify"):
            row = store.get_stage("run-A", stage)
            assert row is not None and row["status"] == "complete"
