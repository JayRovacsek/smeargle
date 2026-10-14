"""In-process protocol fakes and call recorders (spec 14)."""

from __future__ import annotations

from pydantic import BaseModel

from smeargle.domain.jev import JevResult


class RecordingRecorder:
    def __init__(self):
        self.requests = []
        self.responses = []
        self.attempts = []

    def request(self, **kwargs):
        self.requests.append(kwargs)

    def response(self, **kwargs):
        self.responses.append(kwargs)

    def attempt(self, **kwargs):
        self.attempts.append(kwargs)


class FakeLLMClient:
    def __init__(self, responses=None, default=None):
        self.calls = []
        self._responses = list(responses or [])
        self._default = default

    def complete_json(self, schema, messages, *, meta=None):
        self.calls.append({"schema": schema, "messages": messages, "meta": meta})
        result = self._responses.pop(0) if self._responses else self._default
        if result is None:
            result = {"requirements": []}
        if callable(result):
            result = result(messages)
        if isinstance(result, BaseModel):
            return result
        return schema.model_validate(result)


class FakeJevClient:
    def __init__(self, responses=None, default=None):
        self.calls = []
        self._responses = list(responses or [])
        self._default = default

    def systemone(self, state, questions, *, meta=None):
        self.calls.append({"state": state, "questions": list(questions), "meta": meta})
        result = self._responses.pop(0) if self._responses else self._default
        if result is None:
            return JevResult(answers=())
        return result

    def systemone_batch(self, states, questions, *, meta=None):
        return [self.systemone(state, questions, meta=meta) for state in states]
