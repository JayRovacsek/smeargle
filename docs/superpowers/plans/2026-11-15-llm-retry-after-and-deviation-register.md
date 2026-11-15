# LLM Retry-After + Spec Deviation Register Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the `openai` SDK as the LLM transport but make its retry loop honour `Retry-After` with exponential backoff capped at 60s, and amend the design spec to record every intentionally-maintained deviation (original intent vs current implementation).

**Architecture:** Two independent work streams. (1) A code change confined to `src/smeargle/clients/llm.py` and its unit tests: extend the existing app-level retry wrapper (the SDK's own retries are disabled via `max_retries=0`) to parse `Retry-After` headers from SDK status errors and raise the backoff ceiling from 8s to 60s. (2) A documentation change confined to `docs/superpowers/specs/2026-10-01-smeargle-design.md`: a new deviation register section plus a small inline amendment to §8.1. The streams touch disjoint files and run in parallel.

**Tech Stack:** Python 3.14, `openai` SDK 2.53.0, `httpx`, `respx` (tests), `pytest`. Markdown spec amendment.

---

## Context (verified findings — read first)

- `src/smeargle/pipeline/run.py:266-271` constructs `openai.OpenAI(..., max_retries=0)`. The SDK's native retry mechanism (which in 2.53.0 does parse `retry-after-ms`, `retry-after` seconds, and HTTP-date forms — see `openai/_base_client.py:768-785`) is therefore **disabled by design**, because the app-level loop in `llm.py:_post` must record every attempt in the `attempts` table (spec §8.3). Enabling SDK retries would lose per-attempt evidence. **Decision (user-approved): keep `max_retries=0` and extend the existing try/except wrapper.**
- `src/smeargle/clients/llm.py:233-243` — current `backoff()` uses `0.5 * 2**(attempt-1)` capped at `8.0` with full jitter, and never reads response headers. `openai.RateLimitError` and `openai.APIStatusError` expose `.response` (an `httpx.Response`), whose `headers` carry `Retry-After`.
- `src/smeargle/clients/retry.py:33-38` already has a `_retry_after()` parser for the JEV path; the LLM wrapper mirrors its header precedence but keeps its own 60s ceiling. **`retry.py` is NOT modified** (out of scope; JEV behaviour unchanged).
- `tests/unit/clients/test_llm.py` uses `@respx.mock` with a real `openai.OpenAI(base_url="https://llm.example", api_key="sk-test", max_retries=0)` client (see `_client()` helper at lines 21-26) and a `sleep=` injection hook on `OpenAiCompatibleLLM` for capturing delays.
- All other audit findings (JEV `/v1/decide/batch` shared-questions wire format, noul probability fallback, `--*-base-url` flag naming, `--no-redact` toggle, `--jev-max-len`/`--jev-head-max-len` flag gap, `is_valid` facade validation, layout extras) are **confirmed intentional**; Task 2 documents them. Specifically for the facade: `instance.is_valid` is preferred over `instance.validate()` because looser validation of incoming data is desired.

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/smeargle/clients/llm.py` | Modify | Add `_MAX_BACKOFF_SECONDS = 60.0`, `_retry_after_seconds()` helper, extend `backoff()` to accept the exception and honour the header |
| `tests/unit/clients/test_llm.py` | Modify | Add retry-semantics unit tests (5 new tests) |
| `docs/superpowers/specs/2026-10-01-smeargle-design.md` | Modify | New §18 deviation register + one inline amendment to §8.1 |

## Task Dependency / Parallelism

- **Task 1** (code) and **Task 2** (docs) are independent → dispatch simultaneously.
- **Task 3** (code review) depends on Task 1. **Task 4** (verification) depends on Tasks 1 and 3.

---

## Task 1: LLM retry — honour Retry-After, cap backoff at 60s

**Agent:** `python-pro` (or `general`). **Files:**
- Modify: `src/smeargle/clients/llm.py`
- Test: `tests/unit/clients/test_llm.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/clients/test_llm.py` (reuse the existing `_client()` helper, `URL`, `_chat()` helpers and `respx` pattern):

```python
@respx.mock
def test_rate_limit_honours_retry_after_seconds_header():
    respx.post(URL).mock(
        side_effect=[
            httpx.Response(429, headers={"retry-after": "30"}, json={"error": "slow down"}),
            httpx.Response(200, json=_chat('{"requirements": []}')),
        ]
    )
    sleeps = []
    _client(retries=2, structured_output=False, sleep=sleeps.append).complete_json(
        wire.ExtractionResponseModel, [{"role": "user", "content": "hi"}]
    )
    assert sleeps == [30.0]


@respx.mock
def test_rate_limit_prefers_retry_after_ms_over_retry_after():
    respx.post(URL).mock(
        side_effect=[
            httpx.Response(
                429,
                headers={"retry-after-ms": "1500", "retry-after": "30"},
                json={"error": "slow down"},
            ),
            httpx.Response(200, json=_chat('{"requirements": []}')),
        ]
    )
    sleeps = []
    _client(retries=2, structured_output=False, sleep=sleeps.append).complete_json(
        wire.ExtractionResponseModel, [{"role": "user", "content": "hi"}]
    )
    assert sleeps == [1.5]


@respx.mock
def test_retry_after_value_is_capped_at_max_backoff():
    respx.post(URL).mock(
        side_effect=[
            httpx.Response(429, headers={"retry-after": "120"}, json={"error": "slow down"}),
            httpx.Response(200, json=_chat('{"requirements": []}')),
        ]
    )
    sleeps = []
    _client(retries=2, structured_output=False, sleep=sleeps.append).complete_json(
        wire.ExtractionResponseModel, [{"role": "user", "content": "hi"}]
    )
    assert sleeps == [60.0]


@respx.mock
def test_exponential_backoff_sequence_capped_at_60s():
    responses = [httpx.Response(503) for _ in range(9)]
    responses[-1] = httpx.Response(200, json=_chat('{"requirements": []}'))
    respx.post(URL).mock(side_effect=responses)
    sleeps = []
    _client(retries=8, structured_output=False, sleep=sleeps.append).complete_json(
        wire.ExtractionResponseModel, [{"role": "user", "content": "hi"}]
    )
    # 0.5, 1, 2, 4, 8, 16, 32, 64 -> final delay capped at 60 (rng=None, no jitter)
    assert sleeps == [0.5, 1, 2, 4, 8, 16, 32, 60]


@respx.mock
def test_retry_after_http_date_header_is_parsed():
    when = formatdate(time.time() + 45, usegmt=True)
    respx.post(URL).mock(
        side_effect=[
            httpx.Response(503, headers={"retry-after": when}, json={"error": "unavailable"}),
            httpx.Response(200, json=_chat('{"requirements": []}')),
        ]
    )
    sleeps = []
    _client(retries=2, structured_output=False, sleep=sleeps.append).complete_json(
        wire.ExtractionResponseModel, [{"role": "user", "content": "hi"}]
    )
    assert 40.0 <= sleeps[0] <= 45.0
```

Add `from email.utils import formatdate` and `import time` to the test file imports (alongside the existing `json`, `httpx`, `openai`, `pytest`, `respx` imports).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/clients/test_llm.py -v -k "retry_after or exponential_backoff_sequence"`
Expected: FAIL — `test_rate_limit_honours_retry_after_seconds_header` sleeps `0.5 * 2**0` instead of `30.0`; `test_exponential_backoff_sequence_capped_at_60s` yields `64` not `60`; ms-preference and date tests fail for the same reason.

- [ ] **Step 3: Implement the retry wrapper changes**

In `src/smeargle/clients/llm.py`:

3a. Extend imports (after line 7, keeping stdlib grouping):

```python
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
```

3b. Add the constant next to the existing module constants (after line 22, `_RETRYABLE_STATUSES`):

```python
_MAX_BACKOFF_SECONDS = 60.0
```

3c. Add the helper as a module-level function (before `class OpenAiCompatibleLLM`), mirroring the SDK's own header precedence (`retry-after-ms` → `retry-after` seconds → HTTP-date), matching `retry.py`'s intent:

```python
def _retry_after_seconds(exc: openai.APIStatusError) -> Optional[float]:
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

3d. Replace the existing `backoff` closure (lines 233-243) with a version that accepts the exception, honours the header (no jitter — the server asked for that delay), and caps both paths at `_MAX_BACKOFF_SECONDS`:

```python
        def backoff(attempt_no: int, exc: Optional[openai.APIStatusError] = None) -> None:
            retry_after = _retry_after_seconds(exc) if exc is not None else None
            if retry_after is not None:
                delay = min(_MAX_BACKOFF_SECONDS, retry_after)
            else:
                delay = min(_MAX_BACKOFF_SECONDS, 0.5 * (2 ** (attempt_no - 1)))
                if self._rng is not None:
                    delay = self._rng.uniform(0.0, delay)
            _logger.warning(
                "llm retry %s %s attempt %s",
                call_type, item_ref, attempt_no + 1,
                extra={"smeargle": {
                    "stage": stage, "item_ref": item_ref, "call_type": call_type,
                    "model": self._model, "attempt_no": attempt_no + 1,
                }},
            )
            self._sleep(delay)
```

3e. Update the two retry call sites that have a response-bearing exception to pass it through:
- `except openai.RateLimitError as exc:` branch (line 251): `backoff(attempt_no)` → `backoff(attempt_no, exc)`
- `except openai.APIStatusError as exc:` branch (line 271): `backoff(attempt_no)` → `backoff(attempt_no, exc)`
- `except openai.APIConnectionError as exc:` branch (line 286): **unchanged** (`backoff(attempt_no)` — no response to read).

- [ ] **Step 4: Run the full client test file**

Run: `python -m pytest tests/unit/clients/test_llm.py -v`
Expected: all tests PASS (existing retry/evidence tests unaffected).

- [ ] **Step 5: Commit**

Per AGENTS.md, use the message-file workflow (separate commands, never chained):

1. Write `.tmp/commit-msg.txt`:

```
feat(clients): honour retry-after and cap llm backoff at 60s

the openai sdk client is constructed with max_retries=0 so every attempt
can be recorded as evidence, which disables the sdk's native retry-after
handling. replicate the sdk's header precedence (retry-after-ms, seconds,
http-date) in the existing wrapper and raise the exponential ceiling from
8s to 60s.

Assisted-by: <actual model name> via OpenCode
```

Replace `<actual model name>` with the real model identifier in use.

2. `git add src/smeargle/clients/llm.py tests/unit/clients/test_llm.py`
3. `git commit -F .tmp/commit-msg.txt`
4. `rm .tmp/commit-msg.txt`

---

## Task 2: Amend design spec with deviation register

**Agent:** `general` (docs). **Files:**
- Modify: `docs/superpowers/specs/2026-10-01-smeargle-design.md`

**Do not touch any file outside the spec.** Content below is final — transcribe with light formatting only.

- [ ] **Step 1: Inline amendment to §8.1**

Immediately after the paragraph ending `...explicitly declared untrusted data (prompt-injection defence).` (end of §8.1, before `### 8.2 JEV client`), insert:

```markdown
> **Amended 2026-11-15 (intentional deviation):** the transport is the official
> `openai` Python SDK rather than a hand-rolled `httpx.Client`, but it is
> constructed with `max_retries=0` so the application-level loop below still
> observes and records every attempt. The loop honours `Retry-After`
> (`retry-after-ms` → `retry-after` seconds → HTTP-date, matching the SDK's own
> precedence) and caps exponential backoff at 60 seconds.
```

- [ ] **Step 2: Append the deviation register as new §18**

Append after the §17 Decisions log table (end of file):

```markdown
## 18. Deviation register (amended 2026-11-15)

Each entry records the original intent, the current implementation, and the
decision to maintain the deviation. These were reviewed and confirmed
intentional; the register exists so the spec and code agree on the delta.

| # | Area | Original intent | Current implementation | Status |
|---|---|---|---|---|
| D1 | §8.1 LLM transport | Hand-rolled `httpx.Client` delegating to `retry.request_with_retry` | Official `openai` SDK (`max_retries=0`) with an app-level retry wrapper; Retry-After honoured, backoff capped at 60s | Maintained (see §8.1 amendment, plan 2026-11-15) |
| D2 | §8.2 JEV batch endpoint | `POST {jev}/v1/systemone/batch` with per-`(state, questions)` items | `POST {jev}/v1/decide/batch` with a shared `questions` dict applied to all `states`; DTOs use the keyed `q0..qN` discriminated-union shape | Maintained — matches the reference Laya server's actual batch route |
| D3 | §8.2 noul probability | The returned probability **is** the response's `answer_confidence` | Prefers the `noul` field; falls back to `confidence`, then `0.0`; the `yes`/`no` label is synthesised at the 0.5 midpoint | Maintained |
| D4 | §6/§12 flag naming | `--llm-endpoint` / `--jev-endpoint` (config `endpoint`) | `--llm-base-url` / `--jev-base-url` (config `base_url`), consistently across CLI, config, and tests | Maintained |
| D5 | §6/§15 redaction | Secrets are redacted before any persistence, no opt-out | `--redact/--no-redact` toggle (default on) plus `Execution.redact` config field | Maintained |
| D6 | §12 JEV options | `--jev-max-len` / `--jev-head-max-len` CLI flags | Config fields `jev.max_len` / `jev.head_max_len` exist; no CLI flags expose them | Maintained (documented gap) |
| D7 | §11.6 facade validation | `instance.validate()` (full metaschema validation) | `instance.is_valid` (lighter parse/required-fields check) | Intentional — looser validation of incoming data is desired |
| D8 | §4/§5 layout extras | No `console.py`; `JevResult` in `clients/ports.py`; no `Ledger` in `domain/` | `console.py` (Rich console), `domain/jev.py` (Jev* values), `Ledger` in `domain/run.py` | Maintained |
| D9 | Misc hardening | — | `FatalServiceError`/`StoreError` classes, `CUSTOM_NS` prop namespace, staging-directory publish in `pipeline/assemble.py`, `record_attempt` upsert, `db.transaction` catching `BaseException` | Maintained |
```

- [ ] **Step 3: Commit**

Message file `.tmp/commit-msg.txt`:

```
docs(specs): record intentional deviations in design spec

add a deviation register (§18) and an §8.1 amendment so the spec reflects
the confirmed-intentional deltas reviewed in the 2026-11-15 audit: openai
sdk transport, jev batch endpoint/format, noul fallback, base-url naming,
redaction toggle, missing max-len flags, looser facade validation, and
layout extras.

Assisted-by: <actual model name> via OpenCode
```

1. `git add docs/superpowers/specs/2026-10-01-smeargle-design.md`
2. `git commit -F .tmp/commit-msg.txt`
3. `rm .tmp/commit-msg.txt`

---

## Task 3: Code review of Task 1 changes

**Agent:** `code-reviewer-comprehensive`. **Depends on:** Task 1. Read-only review of the diff (`git diff HEAD~1 -- src/smeargle/clients/llm.py tests/unit/clients/test_llm.py` or the working tree if uncommitted).

- [ ] Verify: header precedence matches the SDK's own logic; `None`-response handling; no jitter applied to server-directed delays; `APIConnectionError` path untouched; attempt/evidence recording unchanged; tests deterministic (no real sleeping); no regression in existing retry tests.
- [ ] Output findings; fix only 🔴 critical issues, then amend the same commit via `git commit --amend -F .tmp/commit-msg.txt` (message-file workflow) if changes were needed.

## Task 4: Full-suite verification

**Depends on:** Tasks 1 and 3.

- [ ] Run: `python -m pytest tests/unit -q`
- [ ] Run: `python -m pytest tests/integration -q -m "not e2e"` (or the full integration suite)
- [ ] Expected: all pass. Report pass/fail counts; do not silence failures — route them back to Task 1's owner.

---

## Out of scope (explicit)

- `src/smeargle/clients/retry.py` — unchanged (JEV path keeps its 8s cap).
- No changes to `run.py` client construction (`max_retries=0` stays).
- No renames of `--*-base-url` flags; no removal of `--no-redact`; no facade change to `validate()`; no new `--jev-max-len` flags. All confirmed intentional and covered by the register.
