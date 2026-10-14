import httpx
import openai
import pytest
import respx
from pydantic import ValidationError

from smeargle.clients import dto as wire
from smeargle.clients.llm import OpenAiCompatibleLLM
from smeargle.errors import ServiceError


@respx.mock
def test_duplicate_json_keys_are_rejected_after_repairs():
    content = '{"requirements": [], "requirements": []}'
    respx.post("https://llm.example/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    )
    llm = OpenAiCompatibleLLM(
        openai.OpenAI(base_url="https://llm.example", api_key="sk-test", max_retries=0),
        model="m", retries=0, structured_output=False,
    )
    with pytest.raises(ServiceError):
        llm.complete_json(wire.ExtractionResponseModel, [{"role": "user", "content": "x"}])


def test_out_of_range_probability_is_rejected():
    with pytest.raises(ValidationError):
        wire.JevSystemOneResponseModel.model_validate({"answers": {"q0": {"type": "noul", "noul": -0.1}}})
