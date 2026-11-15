"""JEV transport over the OpenAI Decisions pattern (halogen NPU, docs/NPU.md)."""

from __future__ import annotations

import json
import math
from typing import Any, Optional, Sequence

from smeargle.clients.llm import OpenAiCompatibleLLM
from smeargle.clients.ports import CallMeta
from smeargle.domain.jev import JevAnswer, JevQuestion, JevResult
from smeargle.errors import ServiceError

_NOUL_OPTIONS = ["no", "yes"]


class OpenAiJevClient:
    """Implements the JevClient protocol via chat completions with logprobs.

    Each question becomes one chat-completion: the question text goes in
    ``response_format.json_schema.description``, the options in its ``enum``,
    and the per-option probabilities come back in ``top_logprobs`` in one
    pass. HTTP, retry (Retry-After, 60s cap), and evidence recording are
    delegated to the wrapped LLM client's shared loop.
    """

    def __init__(
        self,
        llm: OpenAiCompatibleLLM,
        *,
        model: str,
        min_confidence: Optional[float] = None,
    ) -> None:
        self._llm = llm
        self._model = model
        # accepted for transport-parity with LayaJevClient; gating happens in the pipeline
        self._min_confidence = min_confidence
        self.call_count = 0

    def systemone(
        self, state: str, questions: Sequence[JevQuestion], *, meta: Optional[CallMeta] = None
    ) -> JevResult:
        answers = [self._ask(state, index, question, meta) for index, question in enumerate(questions)]
        return JevResult(answers=tuple(answers))

    def systemone_batch(
        self,
        states: Sequence[str],
        questions: Sequence[JevQuestion],
        *,
        meta: Optional[CallMeta] = None,
    ) -> list[JevResult]:
        return [self.systemone(state, questions, meta=meta) for state in states]

    def _ask(self, state: str, index: int, question: JevQuestion, meta: Optional[CallMeta]) -> JevAnswer:
        options = list(question.options) if question.kind == "choice" else list(_NOUL_OPTIONS)
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "user", "content": state}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": f"q{index}",
                    "description": question.question,
                    "schema": {"enum": options},
                },
            },
            "logprobs": True,
            "top_logprobs": len(options),
        }
        response = self._llm.raw_completion(body, meta)
        if response.status_code is not None and response.status_code >= 400:
            raise ServiceError(f"JEV decision request failed: HTTP {response.status_code}")
        self.call_count += 1
        return self._to_answer(question, options, response)

    def _to_answer(self, question: JevQuestion, options: list[str], response: Any) -> JevAnswer:
        choice = response._response.choices[0]
        option = self._chosen(choice, options)
        probabilities = self._probabilities(choice, options)
        confidence = probabilities.get(option, max(probabilities.values(), default=0.0))
        return JevAnswer(
            question=question.question,
            answer=option,
            answer_confidence=confidence,
            confidence=None,
        )

    @staticmethod
    def _chosen(choice: Any, options: list[str]) -> str:
        content = str(getattr(choice.message, "content", "") or "").strip()
        try:
            parsed = json.loads(content)
        except ValueError:
            parsed = content
        if isinstance(parsed, dict):
            parsed = next(iter(parsed.values()), "")
        candidate = str(parsed).strip().strip('"')
        return candidate if candidate in options else (options[0] if options else "")

    @staticmethod
    def _probabilities(choice: Any, options: list[str]) -> dict[str, float]:
        result: dict[str, float] = {}
        content = getattr(getattr(choice, "logprobs", None), "content", None)
        for entry in content or []:
            for token in getattr(entry, "top_logprobs", None) or []:
                text = str(token.token).strip().strip('"')
                if text in options and text not in result:
                    try:
                        result[text] = math.exp(float(token.logprob))
                    except (OverflowError, ValueError):
                        pass
        return result
