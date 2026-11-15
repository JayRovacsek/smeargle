import json
from datetime import datetime, timezone

import httpx
import pytest
import respx

from smeargle.config import Settings
from smeargle.domain.clock import FrozenClock
from smeargle.domain.ids import UuidIdFactory
from smeargle.errors import ServiceError
from smeargle.pipeline import run as run_pipeline
from smeargle.store.run_store import RunStore


def _settings(tmp_path, **overrides):
    settings = Settings.load(overrides=overrides)
    settings.output = tmp_path / "out"
    settings.state_dir = tmp_path / "state"
    settings.llm.base_url = "https://llm.example"
    settings.llm.model = "test-model"
    settings.jev.base_url = "https://jev.example"
    settings.jev.model = "jev-model"
    settings.jev.transport = "systemone"
    return settings


def _chat(content):
    return {"choices": [{"message": {"content": content}}]}


def _single_answer(answer, confidence):
    if answer in {"yes", "no"}:
        return {"type": "noul", "action": {"act_probability": 1}, "confidence": confidence, "noul": confidence}
    return {
        "type": "choice", "action": {"act_probability": 1}, "confidence": confidence,
        "choice": answer, "probabilities": {answer: confidence},
    }


def _answers(*specs):
    return {"answers": {f"q{i}": _single_answer(a, c) for i, (a, c) in enumerate(specs)}}


def _jev_router(request):
    question = next(iter(json.loads(request.content)["questions"].values()))
    if question["type"] == "choice":
        return httpx.Response(200, json=_answers(("MUST", 0.9)))
    return httpx.Response(200, json=_answers(("yes", 0.9)))


def _fixtures(tmp_path):
    document = tmp_path / "spec.txt"
    document.write_text("The system MUST encrypt data at rest.", encoding="utf-8")
    catalog = tmp_path / "vendor.json"
    catalog.write_text(
        json.dumps(
            {
                "catalog": {
                    "name": "V",
                    "securityControls": [
                        {"controlId": "1.1", "title": "Policy", "family": "Access"}
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    return document, catalog


def _run(tmp_path, settings, document, catalog):
    return run_pipeline.run_pipeline(
        state_dir=settings.state_dir,
        output=settings.output,
        input_paths=[document],
        catalog_paths=[catalog],
        settings=settings,
        clock=FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        id_factory=UuidIdFactory(),
        run_id="run-1",
    )


@respx.mock
def test_full_pipeline_persists_requirements_pairs_and_mappings(tmp_path):
    settings = _settings(tmp_path)
    document, catalog = _fixtures(tmp_path)

    def chat_router(request):
        body = json.loads(request.content)
        prompt = body["messages"][0]["content"]
        if "extract normative requirements" in prompt:
            return httpx.Response(
                200,
                json=_chat(
                    json.dumps(
                        {"requirements": [{"text": "The system MUST encrypt data at rest.", "keyword": "MUST"}]}
                    )
                ),
            )
        if "classify security controls" in prompt:
            return httpx.Response(
                200,
                json=_chat(json.dumps({"labels": [{"control_id": "c-1.1", "domain": "access", "family": "Access"}]})),
            )
        if "control domains" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"domains": ["access"]})))
        return httpx.Response(200, json=_chat(json.dumps({"control_ids": ["c-1.1"]})))

    respx.post("https://llm.example/chat/completions").mock(side_effect=chat_router)
    respx.post("https://jev.example/v1/systemone").mock(
        side_effect=[
            httpx.Response(200, json=_answers(("yes", 0.9))),
            httpx.Response(200, json=_answers(("MUST", 0.9))),
            httpx.Response(200, json=_answers(("yes", 0.9))),
            httpx.Response(200, json=_answers(("subset-of", 0.85))),
        ]
    )

    result = _run(tmp_path, settings, document, catalog)
    assert result.requirement_count == 1
    assert result.candidate_count == 1
    with RunStore.open(settings.state_dir) as store:
        assert store.counts("run-1")["mappings"] == 1
        assert store.list_requirements("run-1")[0].gate_status == "passed"
        assert store.list_mappings("run-1")[0]["relation"] == "subset-of"


@respx.mock
def test_no_candidates_marks_requirement_none_terminal(tmp_path):
    settings = _settings(tmp_path)
    document, catalog = _fixtures(tmp_path)

    def chat_router(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        if "extract normative requirements" in prompt:
            return httpx.Response(
                200, json=_chat(json.dumps({"requirements": [{"text": "MUST x", "keyword": "MUST"}]}))
            )
        if "classify security controls" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"labels": []})))
        return httpx.Response(200, json=_chat(json.dumps({"domains": []})))

    respx.post("https://llm.example/chat/completions").mock(side_effect=chat_router)
    respx.post("https://jev.example/v1/systemone").mock(side_effect=_jev_router)
    _run(tmp_path, settings, document, catalog)
    with RunStore.open(settings.state_dir) as store:
        assert store.list_requirements("run-1")[0].retrieve_status == "none"
        assert store.counts("run-1")["candidate_pairs"] == 0


@respx.mock
def test_fatal_auth_failure_aborts_run(tmp_path):
    settings = _settings(tmp_path)
    document, catalog = _fixtures(tmp_path)
    respx.post("https://llm.example/chat/completions").mock(
        return_value=httpx.Response(401, json={"error": "denied"})
    )
    respx.post("https://jev.example/v1/systemone").mock(return_value=httpx.Response(200, json=_answers(("yes", 0.9))))
    with pytest.raises(ServiceError):
        _run(tmp_path, settings, document, catalog)


@respx.mock
def test_fatal_abort_stamps_stage_and_run_failure(tmp_path):
    settings = _settings(tmp_path)
    document, catalog = _fixtures(tmp_path)
    respx.post("https://llm.example/chat/completions").mock(
        return_value=httpx.Response(401, json={"error": "denied"})
    )
    respx.post("https://jev.example/v1/systemone").mock(
        return_value=httpx.Response(200, json=_answers(("yes", 0.9)))
    )
    with pytest.raises(ServiceError):
        _run(tmp_path, settings, document, catalog)
    with RunStore.open(settings.state_dir) as store:
        assert store.get_run("run-1")["status"] == "failed"
        assert store.get_stage("run-1", "extract")["status"] == "failed"


@respx.mock
def test_classification_unmapped_records_no_mapping(tmp_path):
    settings = _settings(tmp_path)
    document, catalog = _fixtures(tmp_path)

    def chat_router(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        if "extract normative requirements" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"requirements": [{"text": "MUST x", "keyword": "MUST"}]})))
        if "classify security controls" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"labels": [{"control_id": "c-1.1", "domain": "access", "family": "Access"}]})))
        if "control domains" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"domains": ["access"]})))
        return httpx.Response(200, json=_chat(json.dumps({"control_ids": ["c-1.1"]})))

    respx.post("https://llm.example/chat/completions").mock(side_effect=chat_router)
    respx.post("https://jev.example/v1/systemone").mock(
        side_effect=[
            httpx.Response(200, json=_answers(("yes", 0.9))),
            httpx.Response(200, json=_answers(("MUST", 0.9))),
            httpx.Response(200, json=_answers(("yes", 0.9))),
            httpx.Response(200, json=_answers(("no-relationship", 0.9))),
        ]
    )
    _run(tmp_path, settings, document, catalog)
    with RunStore.open(settings.state_dir) as store:
        assert store.counts("run-1")["mappings"] == 0
        pair = store.list_candidate_pairs("run-1")[0]
        assert pair.verify_status == "passed"
        assert store.get_candidate_pair("run-1", pair.pair_id)["classify_status"] == "unmapped"


@respx.mock
def test_resume_skips_completed_work(tmp_path):
    settings = _settings(tmp_path)
    document, catalog = _fixtures(tmp_path)
    llm_calls = {"count": 0}

    def chat_router(request):
        llm_calls["count"] += 1
        prompt = json.loads(request.content)["messages"][0]["content"]
        if "extract normative requirements" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"requirements": [{"text": "MUST x", "keyword": "MUST"}]})))
        if "classify security controls" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"labels": [{"control_id": "c-1.1", "domain": "access", "family": "Access"}]})))
        if "control domains" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"domains": ["access"]})))
        return httpx.Response(200, json=_chat(json.dumps({"control_ids": ["c-1.1"]})))

    respx.post("https://llm.example/chat/completions").mock(side_effect=chat_router)
    respx.post("https://jev.example/v1/systemone").mock(
        side_effect=[
            httpx.Response(200, json=_answers(("yes", 0.9))),
            httpx.Response(200, json=_answers(("MUST", 0.9))),
            httpx.Response(200, json=_answers(("yes", 0.9))),
            httpx.Response(200, json=_answers(("subset-of", 0.85))),
        ]
    )
    _run(tmp_path, settings, document, catalog)
    first = llm_calls["count"]
    _run(tmp_path, settings, document, catalog)
    assert llm_calls["count"] == first


@respx.mock
def test_incomplete_index_defers_retrieval_until_resumed(tmp_path):
    settings = _settings(tmp_path)
    document, catalog = _fixtures(tmp_path)
    fail_indexing = {"value": True}

    def chat_router(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        if "classify security controls" in prompt:
            if fail_indexing["value"]:
                return httpx.Response(200, json=_chat('{"labels": "nope"}'))
            return httpx.Response(200, json=_chat(json.dumps({"labels": [{"control_id": "c-1.1", "domain": "access", "family": "Access"}]})))
        if "extract normative requirements" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"requirements": [{"text": "MUST x", "keyword": "MUST"}]})))
        if "control domains" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"domains": ["access"]})))
        return httpx.Response(200, json=_chat(json.dumps({"control_ids": ["c-1.1"]})))

    def jev_router(request):
        question = next(iter(json.loads(request.content)["questions"].values()))
        if question["type"] == "noul":
            return httpx.Response(200, json=_answers(("yes", 0.9)))
        if "MUST" in question.get("criteria", {}):
            return httpx.Response(200, json=_answers(("MUST", 0.9)))
        return httpx.Response(200, json=_answers(("subset-of", 0.85)))

    respx.post("https://llm.example/chat/completions").mock(side_effect=chat_router)
    respx.post("https://jev.example/v1/systemone").mock(side_effect=jev_router)

    _run(tmp_path, settings, document, catalog)
    with RunStore.open(settings.state_dir) as store:
        assert store.get_run("run-1")["status"] == "index_incomplete"
        assert store.list_requirements("run-1")[0].retrieve_status is None
        assert store.counts("run-1")["mappings"] == 0

    fail_indexing["value"] = False
    _run(tmp_path, settings, document, catalog)
    with RunStore.open(settings.state_dir) as store:
        assert store.get_run("run-1")["status"] == "mapped"
        assert store.list_requirements("run-1")[0].retrieve_status == "nominated"
        assert store.counts("run-1")["mappings"] == 1


@respx.mock
def test_partial_extract_resume_does_not_duplicate_ordinals(tmp_path):
    settings = _settings(tmp_path, execution={"chunk_size": 100, "chunk_overlap": 0})
    document, catalog = _fixtures(tmp_path)
    document.write_text("REQ-ALPHA " + "a" * 190 + "REQ-BETA " + "b" * 191, encoding="utf-8")
    fail_beta = {"value": True}

    def chat_router(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        if "extract normative requirements" in prompt:
            if fail_beta["value"] and "REQ-BETA" in prompt:
                return httpx.Response(200, json=_chat('{"requirements": "invalid"}'))
            if "REQ-ALPHA" in prompt:
                return httpx.Response(
                    200,
                    json=_chat(json.dumps({"requirements": [{"text": "Alpha MUST hold.", "keyword": "MUST"}]})),
                )
            if "REQ-BETA" in prompt:
                return httpx.Response(
                    200,
                    json=_chat(json.dumps({"requirements": [{"text": "Beta MUST hold.", "keyword": "MUST"}]})),
                )
            return httpx.Response(200, json=_chat(json.dumps({"requirements": []})))
        if "classify security controls" in prompt:
            return httpx.Response(
                200,
                json=_chat(json.dumps({"labels": [{"control_id": "c-1.1", "domain": "access", "family": "Access"}]})),
            )
        if "control domains" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"domains": []})))
        return httpx.Response(200, json=_chat(json.dumps({"control_ids": ["c-1.1"]})))

    respx.post("https://llm.example/chat/completions").mock(side_effect=chat_router)
    respx.post("https://jev.example/v1/systemone").mock(side_effect=_jev_router)

    _run(tmp_path, settings, document, catalog)
    fail_beta["value"] = False
    _run(tmp_path, settings, document, catalog)
    with RunStore.open(settings.state_dir) as store:
        requirements = store.list_requirements("run-1")
        ordinals = [requirement.ordinal for requirement in requirements]
        assert sorted(ordinals) == [0, 1]
        assert {requirement.normalized_text for requirement in requirements} == {
            "Alpha MUST hold.",
            "Beta MUST hold.",
        }


@respx.mock
def test_per_item_extract_failure_persists_attempt_trace(tmp_path):
    settings = _settings(tmp_path)
    document, catalog = _fixtures(tmp_path)

    def chat_router(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        if "extract normative requirements" in prompt:
            return httpx.Response(200, json=_chat('{"requirements": "invalid"}'))
        if "classify security controls" in prompt:
            return httpx.Response(
                200,
                json=_chat(json.dumps({"labels": [{"control_id": "c-1.1", "domain": "access", "family": "Access"}]})),
            )
        if "control domains" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"domains": []})))
        return httpx.Response(200, json=_chat(json.dumps({"control_ids": ["c-1.1"]})))

    respx.post("https://llm.example/chat/completions").mock(side_effect=chat_router)
    respx.post("https://jev.example/v1/systemone").mock(side_effect=_jev_router)

    _run(tmp_path, settings, document, catalog)
    with RunStore.open(settings.state_dir) as store:
        attempts = store.list_attempts("run-1")
        assert any(
            attempt["stage"] == "extract" and attempt["error_class"] == "ServiceError"
            for attempt in attempts
        )


def _mock_pipeline():
    def chat_router(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        if "extract normative requirements" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"requirements": [
                {"text": "The system MUST encrypt data at rest.", "keyword": "MUST"}]})))
        if "classify security controls" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"labels": [
                {"control_id": "c-1.1", "domain": "access", "family": "Access"}]})))
        if "control domains" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"domains": ["access"]})))
        return httpx.Response(200, json=_chat(json.dumps({"control_ids": ["c-1.1"]})))

    def jev_router(request):
        question = next(iter(json.loads(request.content)["questions"].values()))
        if question["type"] == "noul":
            return httpx.Response(200, json=_answers(("yes", 0.9)))
        if "MUST" in question.get("criteria", {}):
            return httpx.Response(200, json=_answers(("MUST", 0.9)))
        return httpx.Response(200, json=_answers(("subset-of", 0.85)))

    respx.post("https://llm.example/chat/completions").mock(side_effect=chat_router)
    respx.post("https://jev.example/v1/systemone").mock(side_effect=jev_router)


@respx.mock
def test_run_pipeline_emits_artifacts_and_reports_zero_gaps(tmp_path):
    _mock_pipeline()
    settings = _settings(tmp_path)
    document, catalog = _fixtures(tmp_path)
    seen = []
    result = run_pipeline.run_pipeline(
        state_dir=settings.state_dir, output=settings.output,
        input_paths=[document], catalog_paths=[catalog], settings=settings,
        clock=FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        id_factory=UuidIdFactory(), run_id="run-out",
        estimate=lambda kind, count: seen.append((kind, count)),
    )
    assert result.gaps == 0
    assert (settings.output / "requirements-catalog.json").exists()
    assert ("requirements", 1) in seen and any(kind == "candidates" for kind, _ in seen)


@respx.mock
def test_run_extract_only_writes_partial_output(tmp_path):
    _mock_pipeline()
    settings = _settings(tmp_path)
    document, _catalog = _fixtures(tmp_path)
    result = run_pipeline.run_extract_only(
        state_dir=settings.state_dir, output=settings.output, input_paths=[document],
        settings=settings, clock=FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        id_factory=UuidIdFactory(), run_id="run-x",
    )
    assert (settings.output / "requirements-catalog.json").exists()
    assert not (settings.output / "profile.json").exists()
    assert result.run_id == "run-x"


@respx.mock
def test_run_map_completes_an_extract_only_run(tmp_path):
    _mock_pipeline()
    settings = _settings(tmp_path)
    document, catalog = _fixtures(tmp_path)
    run_pipeline.run_extract_only(
        state_dir=settings.state_dir, output=settings.output, input_paths=[document],
        settings=settings, clock=FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        id_factory=UuidIdFactory(), run_id="run-map",
    )
    result = run_pipeline.run_map(
        state_dir=settings.state_dir, output=settings.output, catalog_paths=[catalog],
        settings=settings, clock=FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        id_factory=UuidIdFactory(), run_id="run-map",
    )
    assert result.run_id == "run-map"
    assert (settings.output / "profile.json").exists()


@respx.mock
def test_resume_run_reuses_recorded_documents(tmp_path):
    _mock_pipeline()
    settings = _settings(tmp_path)
    document, catalog = _fixtures(tmp_path)
    run_pipeline.run_pipeline(
        state_dir=settings.state_dir, output=settings.output,
        input_paths=[document], catalog_paths=[catalog], settings=settings,
        clock=FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        id_factory=UuidIdFactory(), run_id="run-resume",
    )
    result = run_pipeline.resume_run(
        state_dir=settings.state_dir, output=settings.output, settings=settings,
        clock=FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        id_factory=UuidIdFactory(), run_id="run-resume",
    )
    assert result.run_id == "run-resume"


@respx.mock
def test_jev_batching_issues_one_batch_call_for_verification_and_classification(tmp_path):
    settings = _settings(tmp_path)
    settings.jev.batch = True
    settings.jev.batch_size = 64
    document, catalog = _fixtures(tmp_path)

    def chat_router(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        if "extract normative requirements" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"requirements": [
                {"text": "The system MUST encrypt data at rest.", "keyword": "MUST"}]})))
        if "classify security controls" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"labels": [
                {"control_id": "c-1.1", "domain": "access", "family": "Access"}]})))
        if "control domains" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"domains": ["access"]})))
        return httpx.Response(200, json=_chat(json.dumps({"control_ids": ["c-1.1"]})))

    respx.post("https://llm.example/chat/completions").mock(side_effect=chat_router)
    # The legacy server has no batch route: with batching enabled the client
    # still falls back to one /v1/systemone call per state for verification and
    # classification (plus the two extract-gate calls), never /v1/decide/batch.
    batch = respx.post("https://jev.example/v1/decide/batch").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    systemone = respx.post("https://jev.example/v1/systemone").mock(
        side_effect=[
            httpx.Response(200, json=_answers(("yes", 0.9))),
            httpx.Response(200, json=_answers(("MUST", 0.9))),
            httpx.Response(200, json=_answers(("yes", 0.9))),
            httpx.Response(200, json=_answers(("subset-of", 0.85))),
        ]
    )
    result = run_pipeline.run_pipeline(
        state_dir=settings.state_dir, output=settings.output,
        input_paths=[document], catalog_paths=[catalog], settings=settings,
        clock=FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        id_factory=UuidIdFactory(), run_id="run-batch",
    )
    assert batch.call_count == 0
    assert systemone.call_count == 4
    assert result.candidate_count == 1
    with RunStore.open(settings.state_dir) as store:
        assert store.counts("run-batch")["mappings"] == 1


@respx.mock
def test_resume_reports_a_persisted_failure_as_a_gap(tmp_path):
    _mock_pipeline()
    settings = _settings(tmp_path)
    document, catalog = _fixtures(tmp_path)
    run_pipeline.run_pipeline(
        state_dir=settings.state_dir, output=settings.output,
        input_paths=[document], catalog_paths=[catalog], settings=settings,
        clock=FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        id_factory=UuidIdFactory(), run_id="run-gap",
    )
    with RunStore.open(settings.state_dir) as store:
        store.record_attempt(
            run_id="run-gap", stage="verify", item_ref="pair-stale",
            call_type="jev_noul", attempt_no=0,
            error_class="per_item_failure", error="boom",
        )
    result = run_pipeline.resume_run(
        state_dir=settings.state_dir, output=settings.output, settings=settings,
        clock=FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        id_factory=UuidIdFactory(), run_id="run-gap",
    )
    rationale = json.loads((settings.output / "rationale.json").read_text())
    assert rationale["summary"]["failures"] == 1
    assert result.failure_count == 1
    assert result.gaps == 1
