# JEV OpenAI-SDK Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `OpenAiJevClient` that queries the halogen-flash-server decision models via the documented OpenAI Decisions pattern (`chat.completions` + `json_schema` enum + `logprobs`), make it the default JEV transport, and fix three wire-contract bugs in the legacy `LayaJevClient` (base_url double-prefix, nonexistent batch route, `min_confidence` on the wire).

**Architecture:** The openai SDK client (already constructed with `max_retries=0` and wrapped by the retry loop from the 2026-11-15 retry plan) becomes the transport for both services. `OpenAiJevClient` composes `OpenAiCompatibleLLM` and issues one chat-completion per question through a new thin public `raw_completion()` method, reusing the existing retry/Retry-After/evidence-recording loop verbatim (no extraction, no circular imports). `JevSettings.transport` selects `chat` (default) or `systemone` (legacy httpx). The legacy client keeps working against real Laya servers with its three bugs fixed.

**Tech Stack:** Python 3.14, `openai` SDK 2.53.0, `httpx`, `respx`, `pytest`.

---

## Context (verified findings — read first)

- **Upstream contract** (peonist-ai/halogen-flash-server `docs/NPU.md` + `docs/api.md`):
  - Decisions via `POST /v1/chat/completions`: `model="decider-0.8b"`, `messages=[{"role":"user","content":<state>}]`, `response_format={"type":"json_schema","json_schema":{"name":...,"description":<question>,"schema":{"enum":[...]}}}`, `logprobs=True, top_logprobs=N`. `top_logprobs` yields every option's log probability in one pass; content is the most likely option "as JSON in the schema's shape". Choice options: 2–10. Sampling params accepted and ignored.
  - `/v1/systemone` request: `model`, `state`, `questions` (dict of `type`/`instructions`/`criteria`). **No batch route exists** (api.md route list; unknown routes → 404). Unknown keys on a request are refused with 422 (d3 models, since 0.18.24) — so `min_confidence` must not go on the wire.
- **Current code:** `clients/jev.py:60-61` puts `min_confidence` in the payload; `:87` posts `/v1/decide/batch`; `http.py:62` passes `base_url` straight to `httpx.Client(base_url=...)` while posting `/v1/systemone` — a base_url ending in `/v1` (the OpenAI SDK convention used everywhere for this server) yields `/v1/v1/systemone` → 404. `clients/llm.py` has `_retry_after_seconds`/`_MAX_BACKOFF_SECONDS`/`_RETRYABLE_STATUSES` and a `_post(body, meta)` retry loop that takes an arbitrary chat-completions body dict and returns `_SdkResponse`.
- **Client-side min_confidence:** verified — `pipeline/verify.py:33`, `classify.py:45`, `extract.py:94-106` apply the reliability gate client-side. Removing the wire field is safe.
- **Existing tests that break (handled in Tasks 3–4):** `tests/unit/clients/test_jev.py` lines ~58-122 assert `/v1/decide/batch` behaviour; `tests/integration/test_orchestrator.py` `_settings()` (lines ~16-24) mocks `…/v1/systemone` and its batching test asserts `batch.call_count == 2`.
- **Live probe:** `localhost:8731` was unreachable from the dev shell; the smoke-test step is optional and must not block.

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/smeargle/clients/retry.py` | Modify | New home for `MAX_BACKOFF_SECONDS`, `RETRYABLE_STATUSES`, `retry_after_seconds` (moved from llm.py) |
| `src/smeargle/clients/llm.py` | Modify | Import retry primitives from `retry.py`; add public `raw_completion(body, meta)` delegating to `_post` |
| `src/smeargle/clients/jev_openai.py` | Create | `OpenAiJevClient` — Decisions-pattern JEV transport over `OpenAiCompatibleLLM.raw_completion` |
| `src/smeargle/clients/jev.py` | Modify | Legacy fixes: no batch route, no `min_confidence` on wire |
| `src/smeargle/clients/http.py` | Modify | `normalize_base_url` / `ensure_v1_suffix` helpers; apply normalise in `build_client` |
| `src/smeargle/config.py` | Modify | `JevSettings.transport: Literal["chat","systemone"] = "chat"` |
| `src/smeargle/cli.py` | Modify | `--jev-transport` option |
| `src/smeargle/pipeline/run.py` | Modify | `_build_jev` selects transport |
| `docs/superpowers/specs/2026-10-01-smeargle-design.md` | Modify | §8.2 amendment + §18 register updates |
| Tests | Modify/Create | `tests/unit/clients/test_retry.py`, `test_jev_openai.py` (new), `test_jev.py`, `tests/unit/test_config.py`, `tests/integration/test_orchestrator.py` |

## Task Dependency / Parallelism

- Task 1 → Task 2 → Task 4 (sequential: primitives → client → wiring).
- Task 3 (legacy fixes) is independent of 1/2 → may run in parallel with Task 1.
- Task 5 (spec) independent → parallel.
- Task 6 (review + verification) last.

---

## Task 1: Move retry primitives to retry.py; add `raw_completion`

**Agent:** `python-pro`. **Files:** Modify `src/smeargle/clients/retry.py`, `src/smeargle/clients/llm.py`; Test `tests/unit/clients/test_retry.py`

- [ ] **Step 1:** In `retry.py`, add (module level, after existing imports; add `from datetime import datetime, timezone` and `from email.utils import parsedate_to_datetime`, and `import openai` under `TYPE_CHECKING`):

```python
MAX_BACKOFF_SECONDS = 60.0
RETRYABLE_STATUSES = frozenset({408, 429, *range(500, 600)})


def retry_after_seconds(exc: "openai.APIStatusError") -> Optional[float]:
    """Extract a retry delay from an SDK status error's response headers.

    Mirrors the openai SDK's own header precedence: ``retry-after-ms``
    (milliseconds), then ``retry-after`` (seconds, allowing nonstandard
    floats), then ``retry-after`` as an HTTP-date. Returns ``None`` when no
    usable header is present.
    """
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    ms = headers.get("retry-after-ms")
    if ms is not None:
        try:
            return max(0.0, float(ms) / 1000.0)
        except ValueError:
            pass
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
```

Note: `retry.py` already has a private `_retry_after(response)` used by `RetryPolicy.delay` (different input: an `httpx.Response`). Keep it; the new function takes an SDK exception.

- [ ] **Step 2:** In `llm.py`, delete the local `_retry_after_seconds`, `_MAX_BACKOFF_SECONDS`, `_RETRYABLE_STATUSES` definitions and import them: `from smeargle.clients.retry import MAX_BACKOFF_SECONDS, RETRYABLE_STATUSES, retry_after_seconds` (update the three usages in `backoff`/`_post`). Keep `_MODES`, `_MAX_REPAIRS`, `_SdkResponse`, `_dump_response`, `_transport_error` in `llm.py` — the retry loop stays where it is.
- [ ] **Step 3:** Add the public delegate on `OpenAiCompatibleLLM` (immediately before `_post`):

```python
    def raw_completion(self, body: dict[str, Any], meta: Optional[CallMeta]) -> "_SdkResponse":
        """Issue a chat-completions request with the shared retry/recording loop.

        Used by :class:`smeargle.clients.jev_openai.OpenAiJevClient` so JEV
        decisions share the exact retry, Retry-After, and evidence semantics.
        """
        return self._post(body, meta)
```

- [ ] **Step 4:** Add direct unit tests to `tests/unit/clients/test_retry.py` for `retry_after_seconds` (seconds header, ms preference, date header, missing response → None, garbage → None) constructing `openai.APIStatusError(status_code=429, body=None, response=httpx.Response(429, headers=...))`.
- [ ] **Step 5:** Run `python -m pytest tests/unit/clients -q` — all pass.
- [ ] **Step 6:** Commit (message-file workflow, `refactor(clients): move retry primitives to retry.py and expose raw_completion`, stage only touched files, `Assisted-by: halogen-qwen3.8-flash-next via OpenCode`).

## Task 2: `OpenAiJevClient` (Decisions pattern)

**Agent:** `python-pro`. **Files:** Create `src/smeargle/clients/jev_openai.py`; Test `tests/unit/clients/test_jev_openai.py`

- [ ] **Step 1: Write failing tests** (respx pattern like `test_llm.py`; `_client()` helper builds `OpenAiJevClient(OpenAiCompatibleLLM(openai.OpenAI(base_url="https://llm.example", api_key="sk-test", max_retries=0), model="decider-0.8b", retries=2, structured_output=False), model="decider-0.8b")`):
  - `test_noul_question_builds_enum_schema_request` — mock 200 with logprobs; assert request body has `response_format.json_schema.schema.enum == ["no","yes"]`, `description == question text`, `logprobs is True`, `top_logprobs == 2`, `messages == [{"role":"user","content":state}]`.
  - `test_choice_question_uses_options_as_enum` — options from `JevQuestion(kind="choice", options=("MUST","SHOULD"))` → enum equals options; `top_logprobs == len(options)`.
  - `test_multi_question_request_issues_one_call_per_question` — two questions → 2 HTTP calls; result has 2 answers.
  - `test_answer_confidence_from_top_logprobs` — mocked top_logprobs `[{token:'"yes"', logprob: ln(0.8)}, {token:'"no"', logprob: ln(0.2)}]`, content `'"yes"'` → answer "yes", answer_confidence ≈ 0.8.
  - `test_content_object_shape_parsed` — content `'{"result": "yes"}'` parses to "yes".
  - `test_batch_loops_states` — `systemone_batch(["a","b"], qs)` → 2 calls, 2 results.
- [ ] **Step 2:** Run — fail (module missing).
- [ ] **Step 3: Implement** `jev_openai.py`:

```python
"""JEV transport over the OpenAI Decisions pattern (halogen NPU, docs/NPU.md)."""

from __future__ import annotations

import json
import math
from typing import Any, Optional, Sequence

from smeargle.clients.llm import OpenAiCompatibleLLM
from smeargle.clients.ports import CallMeta
from smeargle.domain.jev import JevAnswer, JevQuestion, JevResult

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
```

Check `JevQuestion`'s actual field names in `domain/jev.py` first (`question`/`kind`/`options`) and adapt if they differ. `min_confidence` is accepted but applied nowhere here (verify/classify stages already gate client-side).
- [ ] **Step 4:** Run tests — pass.
- [ ] **Step 5:** Commit (`feat(clients): add openai-sdk jev transport via decisions pattern`, Assisted-by trailer, message-file workflow).

## Task 3: Legacy `LayaJevClient` fixes

**Agent:** `python-pro`. **Files:** Modify `src/smeargle/clients/jev.py`, `src/smeargle/clients/http.py`; Test `tests/unit/clients/test_jev.py`

- [ ] **Step 1:** `http.py`: add

```python
def normalize_base_url(base_url: str) -> str:
    """Strip a trailing ``/v1`` (OpenAI SDK convention) so paths like
    ``/v1/systemone`` do not double-prefix into ``/v1/v1/systemone``."""
    trimmed = base_url.rstrip("/")
    if trimmed.endswith("/v1"):
        trimmed = trimmed[: -len("/v1")]
    return trimmed


def ensure_v1_suffix(base_url: str) -> str:
    """Append ``/v1`` when absent (openai SDK convention)."""
    trimmed = base_url.rstrip("/")
    return trimmed if trimmed.endswith("/v1") else trimmed + "/v1"
```

Apply `normalize_base_url` inside `build_client`.
- [ ] **Step 2:** `jev.py`: `systemone_batch` no longer posts `/v1/decide/batch` — always loop `self.systemone(...)` per state (delete the batch branch, `_batches`, `_BATCH_LIMIT`, and the stale comment; keep `batch`/`batch_size` constructor params accepted-but-unused for CLI compatibility). Remove `min_confidence` from the `systemone` payload (keep constructor param; it is a client-side gate).
- [ ] **Step 3:** Update `tests/unit/clients/test_jev.py`: **rewrite or remove the now-obsolete batch-route tests** — `test_systemone_batch_maps_results_to_states`, `test_batch_short_result_array_raises_service_error`, `test_batch_non_object_body_raises_service_error`, `test_batch_size_clamps_to_64_and_omits_min_confidence` (lines ~58-122) — replacing them with a single `test_batch_loops_per_state_calls` asserting each state produces one `/v1/systemone` call (no `/v1/decide/batch`) and results map 1:1. Add `test_base_url_v1_suffix_is_normalised` (base_url `https://x/v1` → request URL `https://x/v1/systemone`); assert no `min_confidence` key in any request body.
- [ ] **Step 4:** Run `python -m pytest tests/unit/clients -q` — pass.
- [ ] **Step 5:** Commit (`fix(clients): correct laya jev wire contract — no batch route, no min-confidence on wire, base-url normalisation`).

## Task 4: Config, CLI, and transport selection

**Agent:** `general`. **Files:** Modify `src/smeargle/config.py`, `src/smeargle/cli.py`, `src/smeargle/pipeline/run.py`, `tests/integration/test_orchestrator.py`; Test `tests/unit/test_config.py`

- [ ] **Step 1:** `config.py` `JevSettings`: add `transport: Literal["chat", "systemone"] = "chat"`.
- [ ] **Step 2:** `cli.py`: add `--jev-transport` to the JEV option group (same style as siblings), wire into `jev_overrides` when not None.
- [ ] **Step 3:** `run.py` `_build_jev`: when `settings.jev.transport == "chat"`, build `openai.OpenAI(base_url=ensure_v1_suffix(settings.jev.base_url), api_key=token or "placeholder", timeout=settings.jev.timeout, max_retries=0)`, wrap in `OpenAiCompatibleLLM(..., structured_output=False)`, then `OpenAiJevClient(llm, model=settings.jev.model or "decider-0.8b", min_confidence=settings.jev.min_confidence)`; return `(client, jev)`. Else keep the httpx path.
- [ ] **Step 4:** Config test: default transport is `"chat"`; `SMEARGLE_JEV__TRANSPORT=systemone` env override works. (`config_snapshot` already serialises the whole jev group via `model_dump`, so `transport` lands in `config_hash` automatically — just verify, no code change.)
- [ ] **Step 5:** **Pin existing integration tests to the legacy transport:** update the `_settings()` helper in `tests/integration/test_orchestrator.py` (lines ~16-24) and any other integration helper that constructs `JevSettings` to pass `transport="systemone"`, so their existing `/v1/systemone` respx mocks keep working. Update `test_jev_batching_issues_one_batch_call_for_verification_and_classification` (~line 462-501) to expect per-state calls instead of `batch.call_count == 2` on `/v1/decide/batch`. (Their subject is the pipeline, not the transport; chat transport is covered by the new unit tests.)
- [ ] **Step 6:** Run unit suite — pass.
- [ ] **Step 7:** Commit (`feat(clients): select jev transport via config with chat default`).

## Task 5: Spec update (parallel with Tasks 1–4)

**Agent:** `general`. **Files:** Modify `docs/superpowers/specs/2026-10-01-smeargle-design.md` only.

- [ ] **Step 1:** Append to §8.2 (after the existing text):

```markdown
> **Amended 2026-11-15 (intentional deviation):** against the halogen
> decision server, the default transport is now the OpenAI Decisions pattern
> (`/v1/chat/completions` with a `json_schema` enum and `logprobs`), selected
> by `jev.transport` (`chat` default, `systemone` legacy). The legacy
> `systemone` transport no longer posts `/v1/decide/batch` (the server has no
> batch route) and no longer sends `min_confidence` on the wire — it is
> applied client-side only.
```

- [ ] **Step 2:** In §18, update D2's Status to `Superseded 2026-11-15 — batch route removed; see D10` and append row:

```markdown
| D10 | §8.2 JEV transport | httpx-only Laya SystemOne client | OpenAiJevClient (chat completions + logprobs) as default; legacy client retained for SystemOne servers | Maintained |
```

- [ ] **Step 3:** Commit (message-file workflow):

```
docs(specs): record jev chat-completions transport decision

amend §8.2 and the deviation register for the openai-sdk decision transport
and the removal of the unsupported batch route and wire min_confidence.

Assisted-by: halogen-qwen3.8-flash-next via OpenCode
```

## Task 6: Review and verification

- [ ] Code review of the Tasks 1–4 diff (`code-reviewer-comprehensive`), focusing on: verbatim-ness of the `raw_completion` delegation, protocol conformance of `OpenAiJevClient`, no behaviour change for `systemone` transport users beyond the three fixes.
- [ ] `python -m pytest tests/unit -q` and `python -m pytest tests/integration -q` — all pass.
- [ ] **User-dependent:** live smoke test against the running server (`--jev-base-url http://localhost:8731/v1` with default chat transport). Cannot run in the sandbox (network unreachable); flag to the user.

---

## Out of scope (explicit)

- No changes to `--jev-batch-size` semantics or the verify/classify gate logic.
- No removal of `--jev-batch`/`--jev-batch-size` CLI flags (accepted, unused by chat transport).
- `flake.nix` pre-existing modification stays untouched.
