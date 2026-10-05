import json

import httpx
import pytest
import respx
from fakes.clients import RecordingRecorder

from smeargle.clients import dto as wire
from smeargle.clients.http import build_client
from smeargle.clients.llm import OpenAiCompatibleLLM, extract_first_json_object
from smeargle.clients.ports import CallMeta
from smeargle.errors import ServiceError

URL = "https://llm.example/v1/chat/completions"


def _chat(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


def _client(**kwargs):
    return OpenAiCompatibleLLM(
        build_client(base_url="https://llm.example", timeout=5.0),
        model="test-model",
        **kwargs,
    )


@respx.mock
def test_json_schema_mode_uses_strict_response_format():
    route = respx.post(URL).mock(
        return_value=httpx.Response(200, json=_chat('{"requirements": []}'))
    )
    result = _client(retries=0).complete_json(
        wire.ExtractionResponseModel, [{"role": "user", "content": "hi"}]
    )
    assert isinstance(result, wire.ExtractionResponseModel)
    body = json.loads(route.calls[0].request.content)
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["temperature"] == 0.0


@respx.mock
def test_falls_back_to_json_object_when_schema_mode_rejected():
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(400, json={"error": "unsupported"}),
            httpx.Response(200, json=_chat('{"requirements": []}')),
        ]
    )
    _client(retries=0).complete_json(
        wire.ExtractionResponseModel, [{"role": "user", "content": "hi"}]
    )
    second = json.loads(route.calls[1].request.content)
    assert second["response_format"] == {"type": "json_object"}
    assert any("schema" in m["content"].lower() for m in second["messages"])


@respx.mock
def test_falls_back_to_plain_prompt_and_extracts_first_json_object():
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(400, json={}),
            httpx.Response(400, json={}),
            httpx.Response(200, json=_chat('Here you go:\n{"requirements": []}\nthanks')),
        ]
    )
    _client(retries=0).complete_json(
        wire.ExtractionResponseModel, [{"role": "user", "content": "hi"}]
    )
    assert route.calls[2].request.content


@respx.mock
def test_repair_loop_feeds_validation_error_back_immediately():
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(200, json=_chat('{"requirements": "nope"}')),
            httpx.Response(200, json=_chat('{"requirements": []}')),
        ]
    )
    llm = _client(retries=0, structured_output=False)
    llm.complete_json(wire.ExtractionResponseModel, [{"role": "user", "content": "hi"}])
    second = json.loads(route.calls[1].request.content)
    assert any("invalid" in m["content"].lower() for m in second["messages"])
    assert llm.call_count == 2


@respx.mock
def test_repair_exhaustion_raises_service_error():
    bad = '{"requirements": [{"text": "x", "keyword": "BOGUS"}]}'
    respx.post(URL).mock(return_value=httpx.Response(200, json=_chat(bad)))
    with pytest.raises(ServiceError):
        _client(retries=0, structured_output=False).complete_json(
            wire.ExtractionResponseModel, [{"role": "user", "content": "hi"}]
        )


@respx.mock
def test_records_evidence_and_attempts_around_retried_call():
    respx.post(URL).mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, json=_chat('{"requirements": []}')),
        ]
    )
    recorder = RecordingRecorder()
    meta = CallMeta(stage="extract", item_ref="doc-1", call_type="llm_extract", prompt_hash="ph")
    _client(retries=2, structured_output=False, recorder=recorder).complete_json(
        wire.ExtractionResponseModel, [{"role": "user", "content": "hi"}], meta=meta
    )
    assert len(recorder.requests) == 1
    assert recorder.responses[0]["http_status"] == 200
    assert recorder.responses[0]["attempt_no"] == 2
    assert [a["attempt_no"] for a in recorder.attempts] == [1, 2]


def test_extract_first_json_object_handles_nested_braces_and_strings():
    text = 'prefix {"a": {"b": "}"}} suffix'
    assert extract_first_json_object(text) == '{"a": {"b": "}"}}'


@respx.mock
def test_schema_instruction_is_a_leading_system_message():
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(400, json={}),
            httpx.Response(200, json=_chat('{"requirements": []}')),
        ]
    )
    _client(retries=0).complete_json(
        wire.ExtractionResponseModel, [{"role": "user", "content": "hi"}]
    )
    body = json.loads(route.calls[1].request.content)
    assert body["messages"][0]["role"] == "system"
    assert "schema" in body["messages"][0]["content"].lower()
    assert body["messages"][1] == {"role": "user", "content": "hi"}


@respx.mock
def test_plain_prompt_also_sends_a_leading_system_message():
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(400, json={}),
            httpx.Response(400, json={}),
            httpx.Response(200, json=_chat('{"requirements": []}')),
        ]
    )
    _client(retries=0).complete_json(
        wire.ExtractionResponseModel, [{"role": "user", "content": "hi"}]
    )
    body = json.loads(route.calls[2].request.content)
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1] == {"role": "user", "content": "hi"}
