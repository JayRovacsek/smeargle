from smeargle.clients.ports import JevClient, LLMClient
from smeargle.domain.jev import JevResult


class _FakeLLM:
    def complete_json(self, schema, messages):
        return schema.model_validate({})


class _FakeJev:
    def systemone(self, state, questions):
        return JevResult(answers=())

    def systemone_batch(self, states, questions):
        return [JevResult(answers=()) for _ in states]


def test_fakes_satisfy_protocols():
    assert isinstance(_FakeLLM(), LLMClient)
    assert isinstance(_FakeJev(), JevClient)
