import json
import math

import httpx
import openai
import pytest
import respx

from smeargle.clients.jev_openai import OpenAiJevClient
from smeargle.clients.llm import OpenAiCompatibleLLM
from smeargle.domain.jev import JevQuestion
from smeargle.errors import ServiceError

URL = "https://llm.example/chat/completions"


def _client(**kwargs):
    return OpenAiJevClient(
        OpenAiCompatibleLLM(
            openai.OpenAI(base_url="https://llm.example", api_key="sk-test", max_retries=0),
            model="decider-0.8b",
            retries=2,
            structured_output=False,
            **kwargs,
        ),
        model="decider-0.8b",
    )


def _chat_with_logprobs(content: str, top_logprobs: list[dict]) -> dict:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": "decider-0.8b",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
                "logprobs": {
                    "content": [
                        {"token": top_logprobs[0]["token"], "logprob": top_logprobs[0]["logprob"], "top_logprobs": top_logprobs}
                    ]
                },
            }
        ],
    }


@respx.mock
def test_noul_question_builds_enum_schema_request():
    route = respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            json=_chat_with_logprobs(
                '"yes"',
                [
                    {"token": '"yes"', "logprob": math.log(0.8)},
                    {"token": '"no"', "logprob": math.log(0.2)},
                ],
            ),
        )
    )
    question = JevQuestion(kind="noul", question="Is this a requirement?")
    _client().systemone("some state text", [question])
    body = json.loads(route.calls[0].request.content)
    assert body["response_format"]["json_schema"]["schema"]["enum"] == ["no", "yes"]
    assert body["response_format"]["json_schema"]["description"] == "Is this a requirement?"
    assert body["logprobs"] is True
    assert body["top_logprobs"] == 2
    assert body["messages"] == [{"role": "user", "content": "some state text"}]


@respx.mock
def test_choice_question_uses_options_as_enum():
    route = respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            json=_chat_with_logprobs(
                '"MUST"',
                [
                    {"token": '"MUST"', "logprob": math.log(0.9)},
                    {"token": '"SHOULD"', "logprob": math.log(0.1)},
                ],
            ),
        )
    )
    question = JevQuestion(kind="choice", question="Which level?", options=("MUST", "SHOULD"))
    _client().systemone("state", [question])
    body = json.loads(route.calls[0].request.content)
    assert body["response_format"]["json_schema"]["schema"]["enum"] == ["MUST", "SHOULD"]
    assert body["top_logprobs"] == 2


@respx.mock
def test_multi_question_request_issues_one_call_per_question():
    route = respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            json=_chat_with_logprobs(
                '"yes"',
                [
                    {"token": '"yes"', "logprob": math.log(0.7)},
                    {"token": '"no"', "logprob": math.log(0.3)},
                ],
            ),
        )
    )
    questions = [
        JevQuestion(kind="noul", question="Is a requirement?"),
        JevQuestion(kind="noul", question="Is actionable?"),
    ]
    result = _client().systemone("state", questions)
    assert route.call_count == 2
    assert len(result.answers) == 2


@respx.mock
def test_answer_confidence_from_top_logprobs():
    respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            json=_chat_with_logprobs(
                '"yes"',
                [
                    {"token": '"yes"', "logprob": math.log(0.8)},
                    {"token": '"no"', "logprob": math.log(0.2)},
                ],
            ),
        )
    )
    question = JevQuestion(kind="noul", question="Is a requirement?")
    result = _client().systemone("state", [question])
    answer = result.answers[0]
    assert answer.answer == "yes"
    assert answer.answer_confidence == pytest.approx(0.8)


@respx.mock
def test_content_object_shape_parsed():
    respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            json=_chat_with_logprobs(
                '{"result": "yes"}',
                [
                    {"token": '"yes"', "logprob": math.log(0.6)},
                    {"token": '"no"', "logprob": math.log(0.4)},
                ],
            ),
        )
    )
    question = JevQuestion(kind="noul", question="Is a requirement?")
    result = _client().systemone("state", [question])
    assert result.answers[0].answer == "yes"


@respx.mock
def test_batch_loops_states():
    route = respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            json=_chat_with_logprobs(
                '"yes"',
                [
                    {"token": '"yes"', "logprob": math.log(0.8)},
                    {"token": '"no"', "logprob": math.log(0.2)},
                ],
            ),
        )
    )
    questions = [JevQuestion(kind="noul", question="Is a requirement?")]
    results = _client().systemone_batch(["a", "b"], questions)
    assert route.call_count == 2
    assert len(results) == 2


@respx.mock
def test_missing_choices_raise_service_error():
    respx.post(URL).mock(return_value=httpx.Response(200, json={"object": "chat.completion"}))
    question = JevQuestion(kind="noul", question="Is a requirement?")
    with pytest.raises(ServiceError):
        _client().systemone("state", [question])


@respx.mock
def test_exhausted_retries_raise_service_error():
    respx.post(URL).mock(return_value=httpx.Response(429, json={"error": "slow down"}))
    question = JevQuestion(kind="noul", question="Is a requirement?")
    with pytest.raises(ServiceError):
        _client(sleep=lambda seconds: None).systemone("state", [question])
