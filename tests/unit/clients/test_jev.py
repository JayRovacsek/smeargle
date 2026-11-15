import json

import httpx
import respx
from fakes.clients import RecordingRecorder

from smeargle.clients.http import build_client
from smeargle.clients.jev import LayaJevClient
from smeargle.domain.jev import JevQuestion


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
def test_batch_loops_per_state_calls():
    def handler(request):
        body = json.loads(request.content)
        confidence = 0.9 if body["state"] == "a" else 0.1
        return httpx.Response(200, json={"answers": {"q0": _noul(confidence)}})

    route = respx.post("https://jev.example/v1/systemone").mock(side_effect=handler)
    batch_route = respx.post("https://jev.example/v1/decide/batch").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    question = JevQuestion(question="q?", kind="noul")
    results = _client(retries=0, batch=True).systemone_batch(["a", "b"], [question])
    assert route.call_count == 2
    assert batch_route.call_count == 0
    assert [r.answers[0].answer for r in results] == ["yes", "no"]


@respx.mock
def test_batch_disabled_falls_back_to_sequential_calls():
    route = respx.post("https://jev.example/v1/systemone").mock(
        return_value=httpx.Response(200, json={"answers": {"q0": _noul(0.9)}})
    )
    question = JevQuestion(question="q?", kind="noul")
    _client(retries=0, batch=False).systemone_batch(["a", "b"], [question])
    assert route.call_count == 2


@respx.mock
def test_base_url_v1_suffix_is_normalised():
    route = respx.post("https://jev.example/v1/systemone").mock(
        return_value=httpx.Response(200, json={"answers": {"q0": _noul(0.9)}})
    )
    client = LayaJevClient(
        build_client(base_url="https://jev.example/v1", timeout=5.0), model="jev-1", retries=0
    )
    client.systemone("state", [JevQuestion(question="q?", kind="noul")])
    assert str(route.calls[0].request.url) == "https://jev.example/v1/systemone"


@respx.mock
def test_min_confidence_not_sent_on_wire():
    route = respx.post("https://jev.example/v1/systemone").mock(
        return_value=httpx.Response(200, json={"answers": {"q0": _noul(0.9)}})
    )
    client = _client(retries=0, min_confidence=0.6)
    client.systemone("state", [JevQuestion(question="q?", kind="noul")])
    body = json.loads(route.calls[0].request.content)
    assert "min_confidence" not in body
