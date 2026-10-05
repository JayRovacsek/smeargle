import json

import httpx
import pytest
import respx
from fakes.clients import RecordingRecorder

from smeargle.clients.http import build_client
from smeargle.clients.jev import LayaJevClient
from smeargle.domain.jev import JevQuestion
from smeargle.errors import ServiceError


def _answer(answer: str, confidence: float, entropy: float | None = None) -> dict:
    payload = {"question": "q", "answer": answer, "answer_confidence": confidence}
    if entropy is not None:
        payload["confidence"] = entropy
    return payload


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
def test_systemone_batch_maps_results_positionally():
    def handler(request):
        states = json.loads(request.content)["states"]
        return httpx.Response(
            200, json={"results": [[_answer(f"for-{state}", 0.5)] for state in states]}
        )

    respx.post("https://jev.example/v1/systemone/batch").mock(side_effect=handler)
    question = JevQuestion(question="q?", kind="noul")
    results = _client(retries=0, batch=True).systemone_batch(
        ["a", "b", "c"], [[question], [question], [question]]
    )
    assert [r.answers[0].answer for r in results] == ["for-a", "for-b", "for-c"]


@respx.mock
def test_batch_short_result_array_raises_service_error():
    respx.post("https://jev.example/v1/systemone/batch").mock(
        return_value=httpx.Response(200, json={"results": [[_answer("only-one", 0.5)]]})
    )
    question = JevQuestion(question="q?", kind="noul")
    with pytest.raises(ServiceError):
        _client(retries=0, batch=True).systemone_batch(["a", "b"], [[question], [question]])


@respx.mock
def test_batch_disabled_falls_back_to_sequential_calls():
    route = respx.post("https://jev.example/v1/systemone").mock(
        return_value=httpx.Response(200, json={"answers": {"q0": _noul(0.9)}})
    )
    question = JevQuestion(question="q?", kind="noul")
    _client(retries=0, batch=False).systemone_batch(["a", "b"], [[question], [question]])
    assert route.call_count == 2


@respx.mock
def test_min_confidence_is_sent_and_batch_size_clamps_to_64():
    route = respx.post("https://jev.example/v1/systemone/batch").mock(
        side_effect=lambda request: httpx.Response(
            200, json={"results": [[_answer("yes", 0.9)] for _ in json.loads(request.content)["states"]]}
        )
    )
    question = JevQuestion(question="q?", kind="noul")
    client = _client(retries=0, batch=True, batch_size=64, min_confidence=0.4)
    client.systemone_batch(
        [str(i) for i in range(70)], [[question] for _ in range(70)]
    )
    assert route.call_count == 2
    first = json.loads(route.calls[0].request.content)
    assert len(first["states"]) == 64
    assert first["min_confidence"] == 0.4
