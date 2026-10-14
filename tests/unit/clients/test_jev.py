import json

import httpx
import pytest
import respx
from fakes.clients import RecordingRecorder

from smeargle.clients.http import build_client
from smeargle.clients.jev import LayaJevClient
from smeargle.domain.jev import JevQuestion
from smeargle.errors import ServiceError


def _noul(confidence: float) -> dict:
    return {"type": "noul", "action": {"act_probability": 1}, "confidence": confidence, "noul": confidence}


def _client(**kwargs):
    return LayaJevClient(
        build_client(base_url="https://jev.example", timeout=5.0), model="jev-1", **kwargs
    )


@respx.mock
def test_systemone_noul_probability_is_answer_confidence():
    route = respx.post("https://jev.example/v1/systemone").mock(
        return_value=httpx.Response(200, json={"answers": {"q0": _noul(0.83)}})
    )
    question = JevQuestion(question="Is this genuine?", kind="noul")
    recorder = RecordingRecorder()
    result = _client(retries=0, recorder=recorder).systemone("state", [question])
    assert result.answers[0].answer == "yes"
    assert result.answers[0].answer_confidence == 0.83
    assert recorder.responses[0]["attempt_no"] == 1
    body = json.loads(route.calls[0].request.content)
    assert body["model"] == "jev-1"
    assert body["questions"]["q0"]["type"] == "noul"
    assert body["questions"]["q0"]["instructions"] == "Is this genuine?"


@respx.mock
def test_choice_sends_options_and_records_entropy_separately():
    route = respx.post("https://jev.example/v1/systemone").mock(
        return_value=httpx.Response(200, json={"answers": {"q0": {
            "type": "choice", "action": {"act_probability": 1}, "confidence": 0.25,
            "choice": "subset-of", "probabilities": {"subset-of": 0.7, "equal-to": 0.3},
        }}})
    )
    question = JevQuestion(question="Relation?", kind="choice", options=("subset-of", "equal-to"))
    result = _client(retries=0).systemone("state", [question])
    assert result.answers[0].answer == "subset-of"
    assert result.answers[0].answer_confidence == 0.7
    assert result.answers[0].confidence == 0.25
    body = json.loads(route.calls[0].request.content)
    assert body["questions"]["q0"]["criteria"] == {"subset-of": "subset-of", "equal-to": "equal-to"}


@respx.mock
def test_systemone_batch_maps_results_to_states():
    probabilities = {"a": 0.9, "b": 0.1, "c": 0.7}

    def handler(request):
        body = json.loads(request.content)
        assert body["questions"] == {"q0": {"type": "noul", "instructions": "q?"}}
        return httpx.Response(
            200, json={"results": [
                {"answers": {"q0": _noul(probabilities[state])}} for state in body["states"]
            ]}
        )

    respx.post("https://jev.example/v1/decide/batch").mock(side_effect=handler)
    question = JevQuestion(question="q?", kind="noul")
    results = _client(retries=0, batch=True).systemone_batch(["a", "b", "c"], [question])
    assert [r.answers[0].answer for r in results] == ["yes", "no", "yes"]


@respx.mock
def test_batch_short_result_array_raises_service_error():
    respx.post("https://jev.example/v1/decide/batch").mock(
        return_value=httpx.Response(200, json={"results": [{"answers": {"q0": _noul(0.5)}}]})
    )
    question = JevQuestion(question="q?", kind="noul")
    with pytest.raises(ServiceError):
        _client(retries=0, batch=True).systemone_batch(["a", "b"], [question])


@respx.mock
def test_batch_non_object_body_raises_service_error():
    respx.post("https://jev.example/v1/decide/batch").mock(
        return_value=httpx.Response(200, text="gateway noise")
    )
    question = JevQuestion(question="q?", kind="noul")
    with pytest.raises(ServiceError, match="missing results"):
        _client(retries=0, batch=True).systemone_batch(["a"], [question])


@respx.mock
def test_batch_disabled_falls_back_to_sequential_calls():
    route = respx.post("https://jev.example/v1/systemone").mock(
        return_value=httpx.Response(200, json={"answers": {"q0": _noul(0.9)}})
    )
    question = JevQuestion(question="q?", kind="noul")
    _client(retries=0, batch=False).systemone_batch(["a", "b"], [question])
    assert route.call_count == 2


@respx.mock
def test_batch_size_clamps_to_64_and_omits_min_confidence():
    route = respx.post("https://jev.example/v1/decide/batch").mock(
        side_effect=lambda request: httpx.Response(
            200, json={"results": [
                {"answers": {"q0": _noul(0.9)}} for _ in json.loads(request.content)["states"]
            ]}
        )
    )
    question = JevQuestion(question="q?", kind="noul")
    client = _client(retries=0, batch=True, batch_size=64, min_confidence=0.4)
    client.systemone_batch([str(i) for i in range(70)], [question])
    assert route.call_count == 2
    first = json.loads(route.calls[0].request.content)
    assert len(first["states"]) == 64
    assert "min_confidence" not in first
