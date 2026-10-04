import httpx
import pytest
import respx
from pydantic import ValidationError

from smeargle.clients import dto as wire
from smeargle.clients.http import build_client
from smeargle.clients.llm import OpenAiCompatibleLLM
from smeargle.errors import ServiceError


@respx.mock
def test_duplicate_json_keys_are_rejected_after_repairs():
    content = '{"requirements": [], "requirements": []}'
    respx.post("https://llm.example/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    )
    llm = OpenAiCompatibleLLM(
        build_client(base_url="https://llm.example", timeout=5.0),
        model="m", retries=0, structured_output=False,
    )
    with pytest.raises(ServiceError):
        llm.complete_json(wire.ExtractionResponseModel, [{"role": "user", "content": "x"}])


def test_out_of_range_probability_is_rejected():
    with pytest.raises(ValidationError):
        wire.JevResponseModel.model_validate(
            {"answers": [{"answer": "yes", "answer_confidence": -0.1}]}
        )
