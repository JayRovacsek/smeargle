# smeargle Phase 4 (OSCAL Output + CLI Completion) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Phase 1–3 ledger into the complete, runnable `smeargle` tool: assemble and emit every OSCAL 1.2.3 artifact plus the evidence export from the SQLite ledger, enforce the §11.6 integrity gate and §11.7 determinism, and finish the §12 CLI (`run`, `extract`, `map`, `resume`, `validate`, `status`) with exit codes 0–8.

**Architecture:** `pipeline/assemble.py` owns Stage 6: it reads the ledger through `RunStore` and builds a frozen `domain.run.Ledger` view. `oscal_build/emit.py` is a pure assembler (`Ledger` + `Clock` + `IdFactory` → artifact dicts), then writes the fixed §11 layout and exports evidence. `requirements_catalog.py`, `profile.py`, `mapping.py`, and `rationale.py` are pure builders; `oscal_build/facade.py` remains the only module importing `oscal`. The CLI orchestrators in `pipeline/run.py` compose the existing Phase 3 stage functions with the new assembler and drive the §12.1 run/resume UX.

**Tech Stack:** Python 3.11 (PEP 621 `src/` layout), stdlib `dataclasses`/`json`/`sqlite3`/`zlib`, Typer + Pydantic v2 (config/DTO only), `httpx` (sync, thread-pool), the pinned `oscal` 3.2.2 facade, pytest, ruff, mypy, Nix (`nix develop`/`nix build`).

---

## Phase Boundary (read first)

Phase 4 is the **final** phase. It consumes the ledger written by Phases 1–3 and produces the operator-visible tool. It must not re-implement extraction, retrieval, verification, or classification; it composes them.

- **In scope:** §11.1–§11.7 assembly and integrity; §11.5 evidence export; §12 CLI completion and exit codes; §12.1 run/resume UX and pre-flight estimates; §15 exit-6 gap stamping; nomination cap and JEV-batching verification; `extract` partial assemble.
- **Out of scope:** new loaders/adapters, changing thresholds or prompt semantics, OCR, control-id namespacing, any new flake input.

Phase 3 stops at Stage 5 and writes only ledger rows; `extract`/`map` return a clean usage error. Phase 4 must preserve every Phase 1–3 public symbol it touches; the only new symbols are deliberate additions listed in the interface table below.

## Reference Documents

- Spec: `docs/superpowers/specs/2026-10-01-smeargle-design.md` (authoritative).
- `docs/superpowers/plans/2026-10-02-smeargle-1-foundation.md`
- `docs/superpowers/plans/2026-10-02-smeargle-2-runstore-loaders-adapters.md`
- `docs/superpowers/plans/2026-10-02-smeargle-3-pipeline-clients.md`

### Phase 1–3 interface assumptions (verified against the prior plans)

Plan 4 calls the symbols below. Every verified signature matches the prior plan text; the **Status** column flags what does *not* exist yet and must be added by this plan.

| Symbol | Verified signature (source) | Plan 4 call sites | Status |
|---|---|---|---|
| `Settings.load` / groups | `Settings.load(config_file=None, overrides=None)`; `settings.llm/.jev/.mapping/.execution` (P1 T7) | `cli.py`, orchestrators | exists |
| `Settings.mapping.nomination_cap` | `int = 0` (P1 T7) | `run.py`, `cli.py` | exists (unused) |
| `Settings.llm.temperature` | `float = 0.0` (P1 T7) | `config_snapshot` | exists |
| `errors.EXIT_*`, `SmeargleError` subclasses, `exit_code_for` | P1 T2 | `cli.py`, `emit.py` | exists |
| `FatalServiceError(ServiceError)` | P3 T6 | `run.py`, `cli.py` | exists |
| `GapsError`, `IntegrityError`, `AbortedError`, `UsageError` | P1 T2 | `cli.py`, `emit.py` | exists |
| `Clock.now_utc`, `IdFactory.uuid_for(kind, stable_key)` | P1 T4/T5 | all builders | exists |
| `Document`, `Requirement`, `Control`, `DomainIndex`, `CandidatePair`, `MappingRecord`, `Keyword`, `Relationship`, `POSITIVE_RELATIONSHIPS` | P1 T6 | builders | exists |
| `Ledger` | **does not exist** | builders, `assemble.py` | **add to `domain/run.py`** |
| `facade.validate/load_document/serialise_json/configure_support_file` | P2 T2 | `emit.py`, `cli.py` | exists |
| `facade.write_document(path, model, document)` | **does not exist** | `emit.py` | **add** |
| `RunStore.open/get_run/list_catalogs/list_controls/list_documents/list_requirements/list_candidate_pairs/list_mappings/list_evidence/counts/get_stage/set_run_status/find_runs_by_fingerprint/record_attempt` | P2 T5–T7, P3 T9 | `assemble.py`, `run.py`, `cli.py` | exists |
| `RunStore.list_pair_rows(run_id)` | **does not exist** (needed for `classify_status`/`relation`/confidence columns) | `assemble.py` | **add** |
| `RunStore.list_attempts(run_id)` | **does not exist** (durable per-item failures for exit 6) | `assemble.py` | **add** |
| `pipeline.load.run_load`, `pipeline.index.ingest_catalogs` | P2 T12/T13 | `run.py` | exists |
| `pipeline.index.cached_domain_index(store, content_sha256, model_id, prompt_hash)`, `indexing.PROMPT_HASH` | P3 T13/T2 | `assemble.py` | exists |
| `pipeline.run.run_extract/run_index_llm/run_retrieve/run_verify/run_classify`, `RunResult`, `config_snapshot`, `compute_fingerprint` | P3 T12–T17 | `run.py` | exists |
| `pipeline.run_pipeline` | P3 T17 | `cli.py` | exists (modify) |
| `retrieve.nominate_controls` / `retrieve_requirement` | P3 T14 | `run.py` | exists (add `cap`) |
| Prompt hashes: `extraction.PROMPT_HASH`, `indexing.PROMPT_HASH`, `retrieval.DOMAIN_PROMPT_HASH`, `retrieval.NOMINATION_PROMPT_HASH` | P3 T2 | `assemble.py` | exists |
| `clients.ports.CallMeta`, `clients.llm.OpenAiCompatibleLLM`, `clients.jev.LayaJevClient`, `clients.http.build_client`, `clients.http.load_bearer_token` | P3 T3/T5/T7/T8 | `run.py` | exists |
| `pipeline.executor.Writer/EvidenceBus/persist_sorted` | P3 T11 | `run.py` | exists |
| `store.run_store.CatalogRow`, `DB_FILENAME` | P2 T5 / P2 T15 | `run.py`, `cli.py` | exists |
| `tests/support/schemas.validate_against_schema(model, document)`, `SCHEMA_FILES` | P2 T3 | Phase 4 tests | exists |
| `tests/fakes.servers.FakeHttpService/llm_responder/jev_responder` | P3 T20 | Phase 4 e2e | exists |
| `tests/fakes.clients.FakeLLMClient/FakeJevClient` | P3 T12 | Phase 4 tests | exists |

The one substantive reconciliation: **`list_candidate_pairs` returns `CandidatePair` and drops the `classify_status`/`relation`/`confidence_percentage`/`confidence_category` columns**, so `rationale.json` (spec §11.4) cannot be built from it. Plan 4 therefore adds `RunStore.list_pair_rows` (raw rows) rather than widening the Phase 1 `CandidatePair` value. `rationale.json` is a non-OSCAL sidecar, so no schema change is required.

## Global Conventions For Every Task

- **Every Python invocation MUST be an explicit Nix shell command.** Never run bare `pytest`, `python`, `ruff`, `mypy`, or `smeargle`; always wrap them, for example `nix develop -c pytest -q`, `nix develop -c ruff check src tests`, `nix develop -c mypy src`, `nix develop -c python -m smeargle ...`. The **only** direct commands are `nix build`/`nix build .#smeargle` and the real built binary (`./result/bin/smeargle`). Run every command from the repository root.
- **Only the already-pinned `nixpkgs` + `flake-utils` inputs exist.** Do not add a flake input, a `flake.lock` change, or a package outside the Phase 2 overlay.
- **Temporary files live inside the project**, under `.tmp/` (git-ignored), and are cleaned up afterwards. Never use `/tmp`, `$TMPDIR`, or any OS-managed transient path.
- **DRY / YAGNI:** implement exactly what the task specifies. Do not add fields, helpers, or abstractions "for later".
- **TDD:** write the failing test, run it, watch it fail for the stated reason, write the minimal implementation, run it green, commit.
- **Commits:** Conventional Commits, all lowercase, imperative mood, no trailing period, ≤ 140 characters. Every commit carries the mandatory `Assisted-by: DeepSeek Flash via OpenCode` trailer. Never `git push`.
- Do not add comments to code unless a docstring is shown in the plan.
- **EN-AU spelling** in all prose, comments, and docstrings.

## File Structure (responsibilities locked before tasks)

```
src/smeargle/domain/run.py                             # modify: add frozen Ledger view
src/smeargle/oscal_build/common.py                     # create: shared metadata/timestamp/truncate helpers
src/smeargle/oscal_build/facade.py                     # modify: add write_document()
src/smeargle/oscal_build/requirements_catalog.py       # create: §11.1 builder (pure)
src/smeargle/oscal_build/profile.py                    # create: §11.2 builder (pure)
src/smeargle/oscal_build/mapping.py                    # create: §11.3 builder (pure)
src/smeargle/oscal_build/rationale.py                  # create: §11.4 builder (pure)
src/smeargle/oscal_build/emit.py                       # create: assembly driver, write layout, evidence, integrity gate
src/smeargle/pipeline/assemble.py                      # create: Stage 6 orchestration over RunStore
src/smeargle/pipeline/run.py                           # modify: assemble hook, estimates, gap counting, extract/map/resume orchestrators
src/smeargle/pipeline/retrieve.py                      # modify: nomination cap
src/smeargle/store/run_store.py                        # modify: list_pair_rows + list_attempts
src/smeargle/cli.py                                    # modify: full run/extract/map/resume/validate/status + options + exit codes
tests/support/ledger.py                                # create: builder fixtures shared by Phase 4 tests
tests/support/artifacts.py                             # create: write + validate every artifact (metaschema + vendored)
tests/unit/domain/test_ledger.py                       # create
tests/unit/oscal_build/test_facade_write.py            # create
tests/unit/oscal_build/test_requirements_catalog.py    # create
tests/unit/oscal_build/test_profile.py                 # create
tests/unit/oscal_build/test_mapping.py                 # create
tests/unit/oscal_build/test_rationale.py               # create
tests/unit/oscal_build/test_emit.py                    # create: integrity gate + determinism
tests/unit/oscal_build/test_evidence_export.py         # create
tests/unit/pipeline/test_assemble.py                   # create
tests/unit/store/test_run_store_phase4.py              # create
tests/unit/test_cli.py                                 # modify: temperature/nomination-cap options (Task 1)
tests/unit/test_cli_phase4.py                          # create: run/extract/map/resume/status behaviour
tests/unit/pipeline/test_retrieve.py                   # modify: nomination cap coverage (Task 14)
tests/integration/test_orchestrator.py                 # modify: Phase 4 orchestrator + JEV batching integration (Tasks 11/14)
tests/integration/test_phase4_output.py                # create: full-run output validates vs vendored schemas + determinism
tests/integration/test_artifact_validation.py          # create: artifact schema/metaschema + adversarial + determinism (Task 15)
tests/e2e/test_phase4_run.py                           # create: installed binary vs in-thread fake servers
```

**Dependency direction (spec §4, enforced by Phase 2's guard test):** `cli → config / pipeline / clients / store → domain`; `oscal_build → domain / errors / observability` (never `store` / `config` / `clients` / `pipeline`); `pipeline → clients / prompts / store / oscal_build / domain`; `domain → (nothing project-internal beyond `smeargle.domain`)`. `oscal_build/facade.py` remains the only module importing `oscal`, and no Pydantic enters `domain/`.

> **Contract note (deliberate widening):** Phase 2's shorthand "`oscal_build → domain` (only)" is widened to allow the pure leaf modules `smeargle.errors` (typed failures such as `IntegrityError`/`CatalogError`) and `smeargle.observability.redact` (defence-in-depth redaction in the evidence export). Both import nothing project-internal, so the assembler stays free of I/O, `store`, `config`, and `clients`; the Phase 2 guard (only `facade.py` imports `oscal`; no Pydantic in `domain/`) is unchanged. Reimplementing redaction locally was rejected to avoid drift from the single central redactor.

## Phase 4 test-count ledger

Each task's "Expected" line equals that task's net-new test count; the running total counts only Phase 4 tests.

| Task | New tests | Phase 4 running total |
|---|---|---|
| 1 (temperature hashing + nomination-cap option) | 2 | 2 |
| 2 (`facade.write_document` + `common.py`) | 2 | 4 |
| 3 (`domain.run.Ledger`) | 1 | 5 |
| 4 (`requirements_catalog.py`) | 4 | 9 |
| 5 (`profile.py`) | 4 | 13 |
| 6 (`mapping.py`) | 5 | 18 |
| 7 (`rationale.py`) | 5 | 23 |
| 8 (evidence export) | 3 | 26 |
| 9 (`emit.assemble` + integrity gate) | 7 | 33 |
| 10 (`RunStore` Phase 4 queries + `pipeline.assemble` Stage 6) | 8 | 41 |
| 11 (orchestrators + Phase 4 output integration) | 7 | 48 |
| 12 (CLI run/extract/map/resume) | 8 | 56 |
| 13 (CLI validate/status) | 3 | 59 |
| 14 (nomination cap + JEV batching) | 2 | 61 |
| 15 (artifact validation + determinism) | 4 | 65 |
| 16 (Phase 4 e2e acceptance) | 2 | 67 |

Phase 4 adds **67** net-new tests. (Task 9 has 7 `test_emit.py` bodies. Task 10 counts its 3 `RunStore` bodies plus the 5 `pipeline.assemble` bodies, including the new gate-before-write ordering test. Task 11 counts the 4 orchestrator additions plus the 3 remaining `test_phase4_output.py` bodies, after the duplicated byte-level reassembly test was removed. Task 12 counts 7 pipeline tests plus the new exit-code-7 gate-failure test.)

---

## Task 1: Fold `--llm-temperature` into `config_hash` and wire `--nomination-cap`

**Files:**
- Modify: `src/smeargle/cli.py`
- Test: `tests/unit/test_cli.py`

**Spec traceability:** §6 (`nomination_cap` = 0 disabled; temperature folded into `config_hash`), §12 (mapping option group includes `--nomination-cap`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cli.py`:

```python
def _phase4_settings(tmp_path):
    from smeargle.config import Settings

    settings = Settings.load()
    settings.state_dir = tmp_path / "state"
    settings.output = tmp_path / "out"
    settings.llm.endpoint = "https://llm.example"
    settings.jev.endpoint = "https://jev.example"
    return settings


def test_llm_temperature_is_folded_into_config_hash(tmp_path):
    from smeargle.pipeline import run as run_pipeline

    digest_a = run_pipeline.config_hash(
        run_pipeline.redact(run_pipeline.config_snapshot(_phase4_settings(tmp_path)))
    )
    settings_b = _phase4_settings(tmp_path)
    settings_b.llm.temperature = 0.7
    digest_b = run_pipeline.config_hash(
        run_pipeline.redact(run_pipeline.config_snapshot(settings_b))
    )
    assert digest_a != digest_b


def test_nomination_cap_option_is_accepted(tmp_path, capsys):
    document = tmp_path / "a.txt"
    document.write_text("MUST x", encoding="utf-8")
    catalog = tmp_path / "c.json"
    catalog.write_text('{"catalog": {"securityControls": []}}', encoding="utf-8")
    code = main(
        [
            "--state-dir", str(tmp_path / "s"), "--output", str(tmp_path / "o"),
            "--nomination-cap", "5",
            "run", "-i", str(document), "-c", str(catalog),
        ]
    )
    assert code == 2
    assert "--llm-endpoint" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `nix develop -c pytest tests/unit/test_cli.py -k "temperature or nomination_cap" -v`
Expected: `test_nomination_cap_option_is_accepted` fails with `Error: No such option: --nomination-cap`; the temperature test passes (temperature is already in `LlmSettings.model_dump`). This task proves it stays folded and adds the cap option.

- [ ] **Step 3: Add the option and override**

In `src/smeargle/cli.py`, add to the `root` signature after `category_medium`:

```python
    nomination_cap: Optional[int] = typer.Option(None, "--nomination-cap"),
```

Add `nomination_cap` to the existing `mapping_overrides` dict literal in `root`:

```python
            "category_high": category_high, "category_medium": category_medium,
            "nomination_cap": nomination_cap,
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `nix develop -c pytest tests/unit/test_cli.py -k "temperature or nomination_cap" -v`
Expected: `2 passed`. Phase 4 new tests: **2** (running total **2**).

- [ ] **Step 5: Commit**

```bash
git add src/smeargle/cli.py tests/unit/test_cli.py
git commit -m "feat(cli): add nomination cap option and assert temperature hashing" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 2: `facade.write_document` and shared artifact helpers

**Files:**
- Modify: `src/smeargle/oscal_build/facade.py`
- Create: `src/smeargle/oscal_build/common.py`
- Test: `tests/unit/oscal_build/test_facade_write.py`

**Spec traceability:** §4 (`facade.py` is the only `oscal` importer), §11 (validate then write), §11.7 (deterministic timestamps).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/oscal_build/test_facade_write.py`:

```python
import json
from datetime import datetime, timezone

import pytest

from smeargle.domain.clock import FrozenClock
from smeargle.oscal_build import common, facade

GOOD = {
    "catalog": {
        "uuid": "11111111-1111-4111-8111-111111111111",
        "metadata": {
            "title": "t", "last-modified": "2026-01-01T00:00:00Z",
            "version": "1.0.0", "oscal-version": "1.2.3",
        },
    }
}


def test_write_document_validates_and_writes_meta_helpers(tmp_path):
    facade.configure_support_file(tmp_path / "support.db")
    target = tmp_path / "out" / "catalog.json"
    facade.write_document(target, "catalog", GOOD)
    assert json.loads(target.read_text(encoding="utf-8"))["catalog"]["uuid"] == (
        "11111111-1111-4111-8111-111111111111"
    )
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert common.metadata("t", clock=clock)["last-modified"] == "2026-01-01T00:00:00Z"
    assert common.truncate("a\nb\tc") == "a b c"


def test_write_document_rejects_invalid_and_leaves_no_file(tmp_path):
    from smeargle.errors import CatalogError

    facade.configure_support_file(tmp_path / "support.db")
    target = tmp_path / "bad.json"
    with pytest.raises(CatalogError):
        facade.write_document(target, "catalog", {"catalog": {"uuid": "nope"}})
    assert not target.exists()
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `nix develop -c pytest tests/unit/oscal_build/test_facade_write.py -v`
Expected: `AttributeError: module 'smeargle.oscal_build.facade' has no attribute 'write_document'`.

- [ ] **Step 3: Write the implementation**

Create `src/smeargle/oscal_build/common.py`:

```python
"""Shared frozen-clock helpers for OSCAL artifact builders (spec 11)."""

from __future__ import annotations

from typing import Any

from smeargle.domain.clock import Clock

OSCAL_VERSION = "1.2.3"


def oscal_timestamp(clock: Clock) -> str:
    return clock.now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")


def metadata(title: str, *, clock: Clock) -> dict[str, Any]:
    return {
        "title": title,
        "last-modified": oscal_timestamp(clock),
        "version": "1.0.0",
        "oscal-version": OSCAL_VERSION,
    }


def truncate(text: str, limit: int = 80) -> str:
    flat = " ".join(text.split())
    if not flat:
        return "requirement"
    if len(flat) <= limit:
        return flat
    return flat[: limit - 3].rstrip() + "..."
```

Append to `src/smeargle/oscal_build/facade.py` after `serialise_json`:

```python
def write_document(path: Path, model: str, document: Mapping[str, Any]) -> None:
    """Validate then write an OSCAL model as pretty JSON (spec 11)."""
    text = serialise_json(model, document)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
```

`serialise_json` validates first, so an invalid document raises `CatalogError` before the file is created.

- [ ] **Step 4: Run the tests and see them pass**

Run: `nix develop -c pytest tests/unit/oscal_build/test_facade_write.py -v`
Expected: `2 passed`. Phase 4 new tests: **2** (running total **4**).

- [ ] **Step 5: Commit**

```bash
git add src/smeargle/oscal_build/common.py src/smeargle/oscal_build/facade.py tests/unit/oscal_build/test_facade_write.py
git commit -m "feat(oscal): add write_document and shared artifact helpers" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 3: Frozen `Ledger` assembly view

**Files:**
- Modify: `src/smeargle/domain/run.py`
- Test: `tests/unit/domain/test_ledger.py`

**Spec traceability:** §11 ("Assembly is a pure function of the ledger plus the injected `Clock`/`IdFactory`"), §5 (frozen, hashable dataclasses; domain imports only domain).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/domain/test_ledger.py`:

```python
from smeargle.domain.requirements import Keyword, Requirement
from smeargle.domain.run import Ledger


def test_ledger_is_frozen_hashable_and_defaults():
    requirement = Requirement(
        "run-1", "req-1", "doc-1", 0, "The system MUST log.", "The system MUST log.",
        Keyword.MUST, "proposed", "passed", 0.9, "MUST", "nominated",
    )
    ledger = Ledger(
        run_id="run-1", documents=({"doc_id": "doc-1"},), requirements=(requirement,),
        catalogs=(), controls=(), pairs=(), mappings=(), evidence=(),
        domains={"c-1": "access"}, failures=(), run={"run_id": "run-1"},
    )
    assert ledger.run_id == "run-1"
    assert ledger.requirements[0].keyword is Keyword.MUST
    assert hash(ledger) == hash(ledger)
    assert ledger.failures == ()
```

- [ ] **Step 2: Run the test and see it fail**

Run: `nix develop -c pytest tests/unit/domain/test_ledger.py -v`
Expected: collection error — `ImportError: cannot import name 'Ledger' from 'smeargle.domain.run'`.

- [ ] **Step 3: Write the implementation**

Replace the import block of `src/smeargle/domain/run.py` with:

```python
"""Run-scoped domain values and the frozen assembly ledger (spec 5, 11)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from smeargle.domain.controls import Control
from smeargle.domain.requirements import Requirement
```

Append after `RunConfig`:

```python
@dataclass(frozen=True, slots=True, eq=False)
class Ledger:
    run_id: str
    documents: tuple[Mapping[str, Any], ...]
    requirements: tuple[Requirement, ...]
    catalogs: tuple[Mapping[str, Any], ...]
    controls: tuple[Control, ...]
    pairs: tuple[Mapping[str, Any], ...]
    mappings: tuple[Mapping[str, Any], ...]
    evidence: tuple[Mapping[str, Any], ...]
    domains: Mapping[str, str] = field(default_factory=dict)
    failures: tuple[Mapping[str, Any], ...] = ()
    run: Mapping[str, Any] = field(default_factory=dict)

    def __hash__(self) -> int:
        return hash(self.run_id)
```

`eq=False` stops the generated `__hash__` from walking the nested `Mapping`/`list` values (which are unhashable and would raise `TypeError`); the explicit `__hash__` gives a stable run-scoped hash while the payload rows stay plain dicts for the builders. `Ledger` is a one-run transport value, so identity comparison is sufficient (the frozen dataclasses it contains remain value-comparable individually).

- [ ] **Step 4: Run the test and the domain guard**

Run: `nix develop -c pytest tests/unit/domain/test_ledger.py tests/unit/test_dependencies.py -v`
Expected: `2 passed`. Phase 4 new tests: **1** (running total **5**).

- [ ] **Step 5: Commit**

```bash
git add src/smeargle/domain/run.py tests/unit/domain/test_ledger.py
git commit -m "feat(domain): add frozen ledger assembly view" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 4: `requirements_catalog.py` (§11.1)

**Files:**
- Create: `src/smeargle/oscal_build/requirements_catalog.py`
- Create: `tests/support/ledger.py`
- Test: `tests/unit/oscal_build/test_requirements_catalog.py`

**Spec traceability:** §11.1 (metadata with `last-modified`/`oscal-version`; one group per source document `doc-<doc_id>`; one control per accepted requirement with `id == req_id`, `keyword`/`requirement-source` props, `part[name=statement]`, `link rel=reference` to the document back-matter resource; per-document back-matter; fail fast on `req_id` collision).

- [ ] **Step 1: Create the shared builder fixtures**

Create `tests/support/ledger.py`:

```python
"""Shared ledger fixtures for Phase 4 artifact tests."""

from __future__ import annotations

from datetime import datetime, timezone

from smeargle.domain.clock import FrozenClock
from smeargle.domain.ids import UuidIdFactory
from smeargle.domain.requirements import Keyword, Requirement
from smeargle.domain.run import Ledger

FROZEN = datetime(2026, 1, 1, tzinfo=timezone.utc)
CLOCK = FrozenClock(FROZEN)
IDS = UuidIdFactory()
RUN_1 = "run-1"


def document(doc_id="d1", *, content_sha256="a" * 64, ordinal=0,
             path="/in/spec.txt", uri="file:///in/spec.txt"):
    return {
        "run_id": RUN_1, "doc_id": doc_id, "ordinal": ordinal, "path": path, "uri": uri,
        "external_id": None, "media_type": "text/plain", "content_sha256": content_sha256,
        "size_bytes": 10, "status": "loaded",
    }


def catalog(catalog_id="c1", *, content_sha256="b" * 64, ordinal=0,
            path="/in/vendor.json", uri="file:///in/vendor.json"):
    return {
        "run_id": RUN_1, "catalog_id": catalog_id, "ordinal": ordinal, "uri": uri,
        "path": path, "external_id": None, "content_sha256": content_sha256,
        "oscal_version": "1.2.3", "status": "loaded",
    }


def requirement(req_id="req-1", *, doc_id="d1", ordinal=0,
                text="The system MUST encrypt data at rest.", keyword=Keyword.MUST,
                gate="passed", retrieve="nominated", gate_noul_prob=0.9):
    return Requirement(
        RUN_1, req_id, doc_id, ordinal, text, text, keyword, "proposed", gate,
        gate_noul_prob, keyword.value if keyword else None, retrieve,
    )


def pair_row(pair_id="pair-1", *, req_id="req-1", catalog_id="c1", control_id="c-1.1",
             verify="passed", noul=0.9, classify="done", relation="subset-of",
             percentage=0.85, category="high"):
    return {
        "run_id": RUN_1, "pair_id": pair_id, "req_id": req_id, "catalog_id": catalog_id,
        "control_id": control_id, "verify_status": verify, "noul_prob": noul,
        "mapped_threshold": 0.5, "classify_status": classify, "relation": relation,
        "confidence_percentage": percentage, "confidence_category": category,
    }


def mapping_row(req_id="req-1", *, catalog_id="c1", control_id="c-1.1",
                relation="subset-of", percentage=0.85, category="high"):
    return {
        "run_id": RUN_1, "map_uuid": IDS.uuid_for(
            "map", f"{RUN_1}:{req_id}:{catalog_id}:{control_id}"
        ),
        "req_id": req_id, "catalog_id": catalog_id, "control_id": control_id,
        "relation": relation, "confidence_percentage": percentage,
        "confidence_category": category, "rationale": None,
    }


def run_block(**overrides):
    base = {
        "run_id": RUN_1, "fingerprint": "fp", "config_hash": "ch",
        "created_at": "2026-01-01T00:00:00+00:00", "finished_at": "2026-01-01T00:00:00+00:00",
        "status": "mapped", "oscal_version": "1.2.3", "config": {},
    }
    base.update(overrides)
    return base


def ledger(**overrides):
    base = dict(
        run_id=RUN_1, documents=(document(),), requirements=(requirement(),),
        catalogs=(catalog(),), controls=(), pairs=(pair_row(),),
        mappings=(mapping_row(),), evidence=(), domains={"c-1.1": "access"},
        failures=(), run=run_block(),
    )
    base.update(overrides)
    return Ledger(**base)
```

- [ ] **Step 2: Write the failing tests**

Create `tests/unit/oscal_build/test_requirements_catalog.py`:

```python
from support.ledger import CLOCK, IDS, document, ledger, requirement

from smeargle.errors import IntegrityError
from smeargle.oscal_build import requirements_catalog


def _build(**overrides):
    return requirements_catalog.build(ledger(**overrides), clock=CLOCK, id_factory=IDS)


def test_groups_by_document_with_props_and_statement():
    catalog = _build()["catalog"]
    assert catalog["metadata"]["oscal-version"] == "1.2.3"
    assert catalog["metadata"]["last-modified"] == "2026-01-01T00:00:00Z"
    (group,) = catalog["groups"]
    assert group["id"] == "doc-d1"
    (control,) = group["controls"]
    assert control["id"] == "req-1"
    props = {prop["name"]: prop["value"] for prop in control["props"]}
    assert props["keyword"] == "MUST"
    assert props["requirement-source"] == "d1"
    assert control["parts"][0]["name"] == "statement"
    assert control["parts"][0]["prose"] == "The system MUST encrypt data at rest."


def test_control_link_resolves_to_document_back_matter_resource():
    catalog = _build()["catalog"]
    resource_uuid = catalog["back-matter"]["resources"][0]["uuid"]
    href = catalog["groups"][0]["controls"][0]["links"][0]["href"]
    assert href == f"#{resource_uuid}"
    assert catalog["back-matter"]["resources"][0]["rlinks"][0]["href"] == "file:///in/spec.txt"


def test_only_accepted_requirements_are_emitted():
    assert len(_build()["catalog"]["groups"][0]["controls"]) == 1

    # A run with no accepted requirement still emits one group per source document (with no
    # "controls" key) plus a back-matter resource per document, so §11.1 "links each source
    # document" holds and the catalog stays schema-valid (groups/controls minItems 1).
    zero_source = ledger(
        requirements=(requirement(gate="rejected", retrieve=None),), mappings=(), pairs=(),
    )
    rejected = requirements_catalog.build(zero_source, clock=CLOCK, id_factory=IDS)["catalog"]
    (group,) = rejected["groups"]
    assert "controls" not in group
    assert rejected["back-matter"]["resources"]


def test_documents_are_content_sorted_and_req_id_collision_fails_fast():
    first = document("d2", content_sha256="0" * 64, path="/in/a.txt", uri="file:///in/a.txt")
    second = document("d1", content_sha256="f" * 64, path="/in/b.txt", uri="file:///in/b.txt")
    catalog = _build(
        documents=(first, second),
        requirements=(
            requirement("req-b", doc_id="d2", text="B MUST be."),
            requirement("req-a", doc_id="d1", text="A MUST be."),
        ),
    )["catalog"]
    # §11.7 orders by ascending content_sha256, so "0"*64 (doc-d2) precedes "f"*64 (doc-d1).
    assert [group["id"] for group in catalog["groups"]] == ["doc-d2", "doc-d1"]

    with_dupe = ledger(requirements=(requirement("req-1"), requirement("req-1", ordinal=1)))
    try:
        requirements_catalog.build(with_dupe, clock=CLOCK, id_factory=IDS)
    except IntegrityError:
        pass
    else:
        raise AssertionError("expected IntegrityError for colliding req_id")
```

- [ ] **Step 3: Run the tests and see them fail**

Run: `nix develop -c pytest tests/unit/oscal_build/test_requirements_catalog.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'smeargle.oscal_build.requirements_catalog'`.

- [ ] **Step 4: Write the implementation**

Create `src/smeargle/oscal_build/requirements_catalog.py`:

```python
"""Build the §11.1 requirements catalog from the ledger (pure)."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from smeargle.domain.clock import Clock
from smeargle.domain.ids import IdFactory
from smeargle.domain.requirements import Requirement
from smeargle.domain.run import Ledger
from smeargle.errors import IntegrityError
from smeargle.oscal_build.common import metadata, truncate


def _check_unique(requirements: Iterable[Requirement]) -> None:
    # §11.1 requires req_id collisions anywhere in the run to fail fast, not only among
    # the accepted requirements.
    seen: set[str] = set()
    for requirement in requirements:
        if requirement.req_id in seen:
            raise IntegrityError(f"duplicate requirement id '{requirement.req_id}'")
        seen.add(requirement.req_id)


def _group_title(document: Mapping[str, Any]) -> str:
    return document["path"] or document["uri"] or f"doc-{document['doc_id']}"


def _doc_props(document: Mapping[str, Any]) -> list[dict[str, str]]:
    return [
        {"name": "source-path", "value": document["path"] or document["doc_id"]},
        {"name": "source-uri", "value": document["uri"] or document["doc_id"]},
        {"name": "document-id", "value": document["doc_id"]},
        {"name": "content-sha256", "value": document["content_sha256"]},
    ]


def _control(requirement: Requirement, resource_uuid: str) -> dict[str, Any]:
    keyword = requirement.keyword.value if requirement.keyword else "MUST"
    return {
        "id": requirement.req_id,
        "title": truncate(requirement.text),
        "props": [
            {"name": "keyword", "value": keyword},
            {"name": "requirement-source", "value": requirement.doc_id},
        ],
        "parts": [
            {"id": f"{requirement.req_id}-statement", "name": "statement",
             "prose": requirement.text}
        ],
        "links": [{"rel": "reference", "href": f"#{resource_uuid}"}],
    }


def build(ledger: Ledger, *, clock: Clock, id_factory: IdFactory) -> dict[str, Any]:
    _check_unique(ledger.requirements)
    accepted = [r for r in ledger.requirements if r.gate_status == "passed"]
    by_doc: dict[str, list[Requirement]] = {}
    for requirement in accepted:
        by_doc.setdefault(requirement.doc_id, []).append(requirement)

    groups: list[dict[str, Any]] = []
    resources: list[dict[str, Any]] = []
    for document in sorted(ledger.documents, key=lambda d: (d["content_sha256"], d["doc_id"])):
        doc_id = document["doc_id"]
        resource_uuid = id_factory.uuid_for("document-resource", f"{ledger.run_id}:{doc_id}")
        group: dict[str, Any] = {
            "id": f"doc-{doc_id}", "title": _group_title(document),
            "props": _doc_props(document),
        }
        if by_doc.get(doc_id):
            # `controls` must be omitted (not empty) when there are no accepted
            # requirements: the catalog schema gives it minItems 1, while a group that
            # carries only title/props is still schema-valid.
            group["controls"] = [
                _control(requirement, resource_uuid)
                for requirement in sorted(by_doc[doc_id], key=lambda r: (r.ordinal, r.req_id))
            ]
        groups.append(group)
        resources.append(
            {"uuid": resource_uuid, "title": _group_title(document),
             "rlinks": [{"href": document["uri"] or document["path"]}]}
        )

    catalog: dict[str, Any] = {
        "uuid": id_factory.uuid_for("requirements-catalog", ledger.run_id),
        "metadata": metadata(f"smeargle requirements ({ledger.run_id})", clock=clock),
    }
    if groups:
        catalog["groups"] = groups
    if resources:
        catalog["back-matter"] = {"resources": resources}
    return {"catalog": catalog}
```

- [ ] **Step 5: Run the tests and see them pass**

Run: `nix develop -c pytest tests/unit/oscal_build/test_requirements_catalog.py -v`
Expected: `4 passed`. Phase 4 new tests: **4** (running total **9**).

- [ ] **Step 6: Commit**

```bash
git add src/smeargle/oscal_build/requirements_catalog.py tests/support/ledger.py tests/unit/oscal_build/test_requirements_catalog.py
git commit -m "feat(oscal): build requirements catalog from ledger" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 5: `profile.py` (§11.2)

**Files:**
- Create: `src/smeargle/oscal_build/profile.py`
- Test: `tests/unit/oscal_build/test_profile.py`

**Spec traceability:** §11.2 (one `import` per normalised catalog with `include-all`; per mapped control one `alters[]` keyed by `control-id`, one `add` per mapped requirement ordered by requirement id, each with `mapped-requirement` + `confidence-category group=` props and a `link rel=reference` into the requirements-catalog back-matter resource; back-matter resources for requirements-catalog, rationale, and mapping-collection when emitted; unmapped controls get no `add`).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/oscal_build/test_profile.py`:

```python
from support.ledger import CLOCK, IDS, catalog, ledger, mapping_row

from smeargle.oscal_build import profile


def _build(**overrides):
    mapping_present = overrides.pop("mapping_present", True)
    return profile.build(
        ledger(**overrides), mapping_present=mapping_present, clock=CLOCK, id_factory=IDS
    )


def test_imports_one_include_all_per_catalog():
    assert _build()["profile"]["imports"] == [{"href": "catalogs/vendor.json", "include-all": {}}]


def test_alters_keyed_by_control_id_with_one_add_per_requirement():
    body = _build(
        mappings=(mapping_row("req-2"), mapping_row("req-1", control_id="c-1.1")),
    )["profile"]
    (alter,) = body["modify"]["alters"]
    assert alter["control-id"] == "c-1.1"
    assert [add["props"][0]["value"] for add in alter["adds"]] == ["req-1", "req-2"]
    first = alter["adds"][0]
    assert first["props"][1] == {
        "name": "confidence-category", "value": "high", "group": "req-1",
    }
    resource_uuid = IDS.uuid_for("artifact-resource", "run-1:requirements-catalog.json")
    assert first["links"][0] == {
        "rel": "reference", "href": f"#{resource_uuid}", "resource-fragment": "req-1",
    }


def test_modify_omitted_when_nothing_is_mapped_but_imports_remain():
    body = _build(mappings=())["profile"]
    assert "modify" not in body
    assert body["imports"]


def test_mapping_resource_only_when_collection_is_emitted():
    titles = [r["title"] for r in _build()["profile"]["back-matter"]["resources"]]
    assert titles == ["requirements-catalog.json", "rationale.json", "mapping-collection.json"]
    without = profile.build(
        ledger(mappings=(), catalogs=(catalog(),)), mapping_present=False,
        clock=CLOCK, id_factory=IDS,
    )["profile"]
    assert [r["title"] for r in without["back-matter"]["resources"]] == [
        "requirements-catalog.json", "rationale.json",
    ]
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `nix develop -c pytest tests/unit/oscal_build/test_profile.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'smeargle.oscal_build.profile'`.

- [ ] **Step 3: Write the implementation**

Create `src/smeargle/oscal_build/profile.py`:

```python
"""Build the §11.2 tailoring profile from the ledger (pure)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from smeargle.domain.clock import Clock
from smeargle.domain.ids import IdFactory
from smeargle.domain.run import Ledger
from smeargle.oscal_build.common import metadata


def _resource(id_factory: IdFactory, run_id: str, name: str) -> dict[str, Any]:
    return {
        "uuid": id_factory.uuid_for("artifact-resource", f"{run_id}:{name}"),
        "title": name,
        "rlinks": [{"href": name}],
    }


def build(ledger: Ledger, *, mapping_present: bool, clock: Clock,
          id_factory: IdFactory) -> dict[str, Any]:
    catalogs = sorted(ledger.catalogs, key=lambda c: (c["content_sha256"], c["catalog_id"]))
    imports = [
        {"href": f"catalogs/{Path(catalog['path']).stem}.json", "include-all": {}}
        for catalog in catalogs
    ]

    requirements_resource = id_factory.uuid_for(
        "artifact-resource", f"{ledger.run_id}:requirements-catalog.json"
    )
    resources = [
        _resource(id_factory, ledger.run_id, "requirements-catalog.json"),
        _resource(id_factory, ledger.run_id, "rationale.json"),
    ]
    if mapping_present:
        resources.append(_resource(id_factory, ledger.run_id, "mapping-collection.json"))

    by_control: dict[str, list[Mapping[str, Any]]] = {}
    for mapping in ledger.mappings:
        by_control.setdefault(mapping["control_id"], []).append(mapping)

    alters: list[dict[str, Any]] = []
    for control_id in sorted(by_control):
        rows = sorted(by_control[control_id], key=lambda m: (m["req_id"], m["control_id"]))
        adds = [
            {
                "props": [
                    {"name": "mapped-requirement", "value": row["req_id"]},
                    {"name": "confidence-category", "value": row["confidence_category"],
                     "group": row["req_id"]},
                ],
                "links": [
                    {"rel": "reference", "href": f"#{requirements_resource}",
                     "resource-fragment": row["req_id"]}
                ],
            }
            for row in rows
        ]
        alters.append({"control-id": control_id, "adds": adds})

    document: dict[str, Any] = {
        "uuid": id_factory.uuid_for("profile", ledger.run_id),
        "metadata": metadata(f"smeargle profile ({ledger.run_id})", clock=clock),
        "imports": imports,
        "back-matter": {"resources": resources},
    }
    if alters:
        document["modify"] = {"alters": alters}
    return {"profile": document}
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `nix develop -c pytest tests/unit/oscal_build/test_profile.py -v`
Expected: `4 passed`. Phase 4 new tests: **4** (running total **13**).

- [ ] **Step 5: Commit**

```bash
git add src/smeargle/oscal_build/profile.py tests/unit/oscal_build/test_profile.py
git commit -m "feat(oscal): build tailoring profile from ledger" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 6: `mapping.py` (§11.3)

**Files:**
- Create: `src/smeargle/oscal_build/mapping.py`
- Test: `tests/unit/oscal_build/test_mapping.py`

**Spec traceability:** §11.3 (one `mapping` per catalog with `target-resource` = normalised catalog and `source-resource` = requirements catalog; five positive relationships only; `confidence-score.percentage` from the Stage-5 `answer_confidence`; provenance with `method: automation` and a concrete `mapping-description`; per-catalog `source-gap-summary` only when that catalog has an unmapped accepted requirement; omit the collection entirely on a globally zero-relation run), §16 (relationship enum enforced explicitly).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/oscal_build/test_mapping.py`:

```python
from support.ledger import CLOCK, IDS, catalog, ledger, mapping_row, requirement

from smeargle.oscal_build import mapping


def _build(**overrides):
    return mapping.build(ledger(**overrides), clock=CLOCK, id_factory=IDS)


def test_one_mapping_per_catalog_with_normalised_target():
    document = _build()["mapping-collection"]
    (entry,) = document["mappings"]
    assert entry["target-resource"] == {"type": "catalog", "href": "catalogs/vendor.json"}
    assert entry["source-resource"] == {"type": "catalog", "href": "requirements-catalog.json"}
    assert document["provenance"]["method"] == "automation"
    assert document["provenance"]["mapping-description"]


def test_map_entry_uses_percentage_and_positive_relationship():
    (map_entry,) = _build()["mapping-collection"]["mappings"][0]["maps"]
    assert map_entry["relationship"] == "subset-of"
    assert map_entry["confidence-score"] == {"percentage": 0.85}
    assert map_entry["sources"] == [{"type": "control", "id-ref": "req-1"}]
    assert map_entry["targets"] == [{"type": "control", "id-ref": "c-1.1"}]
    assert map_entry["uuid"] == mapping_row()["map_uuid"]


def test_zero_relation_run_omits_the_collection():
    assert _build(mappings=()) is None


def test_catalog_without_relations_emits_no_mapping_object():
    second = catalog("c2", content_sha256="c" * 64, path="/in/other.json")
    document = _build(catalogs=(catalog(), second))["mapping-collection"]
    assert [e["target-resource"]["href"] for e in document["mappings"]] == [
        "catalogs/vendor.json"
    ]


def test_source_gap_summary_lists_unmapped_accepted_requirements():
    document = _build(
        requirements=(requirement("req-1"), requirement("req-2", text="The system MUST log.")),
    )["mapping-collection"]
    gap = document["mappings"][0]["source-gap-summary"]
    assert gap["unmapped-controls"] == [{"with-ids": ["req-2"]}]
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `nix develop -c pytest tests/unit/oscal_build/test_mapping.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'smeargle.oscal_build.mapping'`.

- [ ] **Step 3: Write the implementation**

Create `src/smeargle/oscal_build/mapping.py`:

```python
"""Build the §11.3 mapping collection from the ledger (pure)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional

from smeargle.domain.clock import Clock
from smeargle.domain.ids import IdFactory
from smeargle.domain.mapping import POSITIVE_RELATIONSHIPS
from smeargle.domain.run import Ledger
from smeargle.errors import IntegrityError
from smeargle.oscal_build.common import metadata


def _map_entry(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "uuid": row["map_uuid"],
        "relationship": row["relation"],
        "confidence-score": {"percentage": row["confidence_percentage"]},
        "sources": [{"type": "control", "id-ref": row["req_id"]}],
        "targets": [{"type": "control", "id-ref": row["control_id"]}],
    }


def _description(ledger: Ledger, mappings: list[dict[str, Any]]) -> str:
    relations = sum(len(entry["maps"]) for entry in mappings)
    controls = {mapping["control_id"] for mapping in ledger.mappings}
    requirements = {mapping["req_id"] for mapping in ledger.mappings}
    return (
        f"Automated semantic mapping of {len(requirements)} requirement(s) to "
        f"{len(controls)} control(s) across {len(mappings)} catalog(s); "
        f"{relations} relationship(s) asserted by LLM retrieval and JEV verification."
    )


def build(ledger: Ledger, *, clock: Clock,
          id_factory: IdFactory) -> Optional[dict[str, Any]]:
    if not ledger.mappings:
        return None

    valid = {relation.value for relation in POSITIVE_RELATIONSHIPS}
    for row in ledger.mappings:
        if row["relation"] not in valid:
            raise IntegrityError(
                f"relation '{row['relation']}' is not one of the five positive OSCAL values"
            )

    by_catalog: dict[str, list[Mapping[str, Any]]] = {}
    for row in ledger.mappings:
        by_catalog.setdefault(row["catalog_id"], []).append(row)

    accepted = sorted({r.req_id for r in ledger.requirements if r.gate_status == "passed"})
    mappings: list[dict[str, Any]] = []
    for catalog in sorted(ledger.catalogs, key=lambda c: (c["content_sha256"], c["catalog_id"])):
        catalog_id = catalog["catalog_id"]
        rows = by_catalog.get(catalog_id)
        if not rows:
            continue
        stem = Path(catalog["path"]).stem
        entry: dict[str, Any] = {
            "uuid": id_factory.uuid_for("mapping", f"{ledger.run_id}:{catalog_id}"),
            "source-resource": {"type": "catalog", "href": "requirements-catalog.json"},
            "target-resource": {"type": "catalog", "href": f"catalogs/{stem}.json"},
            "maps": [
                _map_entry(row)
                for row in sorted(rows, key=lambda m: (m["req_id"], m["control_id"]))
            ],
        }
        mapped = {row["req_id"] for row in rows}
        unmapped = [req_id for req_id in accepted if req_id not in mapped]
        if unmapped:
            entry["source-gap-summary"] = {
                "uuid": id_factory.uuid_for(
                    "gap-summary", f"{ledger.run_id}:{catalog_id}"
                ),
                "unmapped-controls": [{"with-ids": [req_id]} for req_id in unmapped],
            }
        mappings.append(entry)

    if not mappings:
        return None

    collection = {
        "uuid": id_factory.uuid_for("mapping-collection", ledger.run_id),
        "metadata": metadata(
            f"smeargle mapping collection ({ledger.run_id})", clock=clock
        ),
        "provenance": {
            "method": "automation",
            "matching-rationale": "semantic",
            "status": "draft",
            "mapping-description": _description(ledger, mappings),
        },
        "mappings": mappings,
    }
    return {"mapping-collection": collection}
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `nix develop -c pytest tests/unit/oscal_build/test_mapping.py -v`
Expected: `5 passed`. Phase 4 new tests: **5** (running total **18**).

- [ ] **Step 5: Commit**

```bash
git add src/smeargle/oscal_build/mapping.py tests/unit/oscal_build/test_mapping.py
git commit -m "feat(oscal): build mapping collection from ledger" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 7: `rationale.py` (§11.4)

**Files:**
- Create: `src/smeargle/oscal_build/rationale.py`
- Test: `tests/unit/oscal_build/test_rationale.py`

**Spec traceability:** §11.4 (run block with redacted config; per-requirement status/reason; run-level `unmapped_requirements` and `rejected_candidates`; per-pair pointers with both the `noul` probability and the `choice` answer/entropy numbers; summary counts), §10 (the entropy-based `choice` confidence is recorded but does not drive any score).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/oscal_build/test_rationale.py`:

```python
from support.ledger import CLOCK, IDS, ledger, pair_row, requirement, run_block

from smeargle.oscal_build import rationale


def _build(**overrides):
    return rationale.build(ledger(**overrides), clock=CLOCK, id_factory=IDS)


def test_run_block_carries_identity_and_redacted_config():
    document = _build(run=run_block(config={"llm": {"endpoint": "https://llm"}}))
    assert document["run"]["run_id"] == "run-1"
    assert document["run"]["config"]["llm"]["endpoint"] == "https://llm"
    assert document["summary"]["generated_at"] == "2026-01-01T00:00:00Z"


def test_per_requirement_reports_mapped_and_unmapped_reasons():
    document = _build(
        requirements=(
            requirement("req-1"),
            requirement("req-2", text="The system MUST log.", retrieve="none"),
        ),
        pairs=(pair_row(),),
    )
    by_id = {item["req_id"]: item for item in document["requirements"]}
    assert by_id["req-1"]["status"] == "mapped"
    assert by_id["req-2"]["status"] == "unmapped"
    assert by_id["req-2"]["reason"] == "no nominated candidates"
    assert document["unmapped_requirements"] == [
        {"req_id": "req-2", "doc_id": "d1", "reason": "no nominated candidates"}
    ]


def test_rejected_candidates_are_retained_separately():
    document = _build(
        requirements=(
            requirement("req-1"),
            requirement("req-9", text="Bad", gate="rejected", retrieve=None,
                        gate_noul_prob=0.1),
        ),
    )
    assert all(item["req_id"] != "req-9" for item in document["requirements"])
    (rejected,) = document["rejected_candidates"]
    assert rejected["req_id"] == "req-9"
    assert rejected["gate_noul_prob"] == 0.1


def test_all_skipped_classifications_report_the_suppression_reason():
    document = _build(
        pairs=(pair_row(classify="skipped", relation=None, percentage=None, category=None),),
        mappings=(),
    )
    assert document["unmapped_requirements"][0]["reason"] == (
        "all candidate classifications suppressed by jev-min-confidence"
    )


def test_pair_evidence_holds_noul_and_choice_numbers_and_counts():
    evidence = (
        {"stage": "classify", "item_ref": "pair:pair-1", "call_type": "jev_choice",
         "response": {"answers": [{"answer": "subset-of", "answer_confidence": 0.85,
                                   "confidence": 0.42}]}},
    )
    document = _build(evidence=evidence)
    (pair,) = document["pairs"]
    assert pair["noul_prob"] == 0.9
    assert pair["choice"] == {"answer": "subset-of", "answer_confidence": 0.85,
                              "confidence": 0.42}
    assert pair["evidence"] == {"stage": "classify", "item_ref": "pair:pair-1",
                                "call_type": "jev_choice"}
    assert document["summary"]["mapped"] == 1
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `nix develop -c pytest tests/unit/oscal_build/test_rationale.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'smeargle.oscal_build.rationale'`.

- [ ] **Step 3: Write the implementation**

Create `src/smeargle/oscal_build/rationale.py`:

```python
"""Build the §11.4 non-OSCAL rationale process record (pure)."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from smeargle.domain.clock import Clock
from smeargle.domain.ids import IdFactory
from smeargle.domain.requirements import Requirement
from smeargle.domain.run import Ledger
from smeargle.oscal_build.common import oscal_timestamp


def _choice_evidence(
    evidence: tuple[Mapping[str, Any], ...], pair_id: str
) -> Optional[Mapping[str, Any]]:
    for row in evidence:
        if (
            row.get("stage") == "classify"
            and row.get("call_type") == "jev_choice"
            and row.get("item_ref") == f"pair:{pair_id}"
        ):
            return row
    return None


def _choice_numbers(
    evidence: tuple[Mapping[str, Any], ...], pair_row: Mapping[str, Any]
) -> dict[str, Any]:
    row = _choice_evidence(evidence, pair_row["pair_id"])
    answer: Mapping[str, Any] = {}
    if row is not None:
        answers = (row.get("response") or {}).get("answers") or []
        answer = answers[0] if answers else {}
    return {
        "answer": answer.get("answer", pair_row["relation"]),
        "answer_confidence": answer.get("answer_confidence",
                                        pair_row["confidence_percentage"]),
        "confidence": answer.get("confidence"),
    }


def _reason(requirement: Requirement, pairs: list[Mapping[str, Any]]) -> str:
    if not pairs:
        return "no nominated candidates"
    verify = {pair["verify_status"] for pair in pairs}
    classify = {pair["classify_status"] for pair in pairs}
    if verify and verify <= {"rejected"}:
        return "all candidates rejected by JEV verification"
    if classify and classify <= {"skipped"}:
        return "all candidate classifications suppressed by jev-min-confidence"
    if classify and classify <= {"unmapped"}:
        return "all passed candidates classified no-relationship or unparseable"
    return "no mapping produced"


def _pair_rationale(pair: Mapping[str, Any]) -> str:
    if pair["classify_status"] == "done":
        return (
            f"JEV 'noul' probability {pair['noul_prob']} cleared the mapped threshold; "
            f"JEV classified the pair as '{pair['relation']}' with answer confidence "
            f"{pair['confidence_percentage']} ({pair['confidence_category']})."
        )
    return (
        f"JEV 'noul' probability {pair['noul_prob']}; pair ended "
        f"'{pair['classify_status']}'."
    )


def build(ledger: Ledger, *, clock: Clock, id_factory: IdFactory) -> dict[str, Any]:
    del id_factory
    mapped_ids = {mapping["req_id"] for mapping in ledger.mappings}
    pairs_by_req: dict[str, list[Mapping[str, Any]]] = {}
    for pair in ledger.pairs:
        pairs_by_req.setdefault(pair["req_id"], []).append(pair)

    accepted = [r for r in ledger.requirements if r.gate_status == "passed"]
    rejected = [r for r in ledger.requirements if r.gate_status != "passed"]

    requirements: list[dict[str, Any]] = []
    unmapped: list[dict[str, Any]] = []
    for requirement in sorted(accepted, key=lambda r: (r.ordinal, r.req_id)):
        mapped = requirement.req_id in mapped_ids
        reason = "at least one mapping emitted" if mapped else _reason(
            requirement, pairs_by_req.get(requirement.req_id, [])
        )
        requirements.append(
            {
                "req_id": requirement.req_id, "doc_id": requirement.doc_id,
                "text": requirement.text,
                "keyword": requirement.keyword.value if requirement.keyword else None,
                "gate_status": requirement.gate_status,
                "gate_noul_prob": requirement.gate_noul_prob,
                "gate_choice": requirement.gate_choice,
                "status": "mapped" if mapped else "unmapped",
                "reason": reason,
            }
        )
        if not mapped:
            unmapped.append({"req_id": requirement.req_id, "doc_id": requirement.doc_id,
                             "reason": reason})

    rejected_candidates = [
        {"req_id": item.req_id, "doc_id": item.doc_id, "text": item.text,
         "gate_noul_prob": item.gate_noul_prob, "gate_choice": item.gate_choice}
        for item in sorted(rejected, key=lambda r: (r.ordinal, r.req_id))
    ]

    pairs: list[dict[str, Any]] = []
    for pair in sorted(ledger.pairs, key=lambda p: p["pair_id"]):
        pairs.append(
            {
                "pair_id": pair["pair_id"], "req_id": pair["req_id"],
                "catalog_id": pair["catalog_id"], "control_id": pair["control_id"],
                "domain": ledger.domains.get(pair["control_id"]),
                "verify_status": pair["verify_status"], "noul_prob": pair["noul_prob"],
                "classify_status": pair["classify_status"], "relation": pair["relation"],
                "confidence_percentage": pair["confidence_percentage"],
                "confidence_category": pair["confidence_category"],
                "choice": _choice_numbers(ledger.evidence, pair),
                "rationale": _pair_rationale(pair),
                # Stage 3 persists the nominated pairs but not the LLM domain-selection /
                # nomination rationale, so the retrieval rationale is recorded as an
                # explicit null (a documented omission) rather than invented. The pair's
                # `domain` label and the classify evidence pointer carry what is known.
                "retrieval_rationale": None,
                "evidence": {"stage": "classify", "item_ref": f"pair:{pair['pair_id']}",
                             "call_type": "jev_choice"},
            }
        )

    failures = [dict(row) for row in ledger.failures]
    return {
        "run": dict(ledger.run),
        "requirements": requirements,
        "unmapped_requirements": unmapped,
        "rejected_candidates": rejected_candidates,
        "pairs": pairs,
        "failures": failures,
        "summary": {
            "requirements": len(ledger.requirements), "accepted": len(accepted),
            "rejected": len(rejected), "mapped": len(mapped_ids),
            "unmapped": len(unmapped), "pairs": len(ledger.pairs),
            "mappings": len(ledger.mappings), "failures": len(failures),
            "generated_at": oscal_timestamp(clock),
        },
    }
```

**Known §11.4 deviation (retained deliberately):** each pair carries a derived prose `rationale` plus an explicit `retrieval_rationale: null`. §11.4 asks for the retrieval rationale and a prose rationale; because Phase 3's Stage 3 stores only the nominated `CandidatePair` rows and does not persist the LLM domain-selection/nomination rationale, `retrieval_rationale` records that omission explicitly rather than fabricating one. The prose `rationale` is derived from the ledger's `noul`/`choice` outcomes, and the per-pair `evidence` pointer locates the underlying classify call.

- [ ] **Step 4: Run the tests and see them pass**

Run: `nix develop -c pytest tests/unit/oscal_build/test_rationale.py -v`
Expected: `5 passed`. Phase 4 new tests: **5** (running total **23**).

- [ ] **Step 5: Commit**

```bash
git add src/smeargle/oscal_build/rationale.py tests/unit/oscal_build/test_rationale.py
git commit -m "feat(oscal): build rationale process record from ledger" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 8: Evidence export (§11.5)

**Files:**
- Create: `src/smeargle/oscal_build/emit.py` (evidence export portion only)
- Test: `tests/unit/oscal_build/test_evidence_export.py`

**Spec traceability:** §11.5 (one record per call preserving `stage`, `item_ref`, `call_type`, `attempt_no`, `http_status`, `request_sha256`, `prompt_hash`; secrets redacted).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/oscal_build/test_evidence_export.py`:

```python
import json

from smeargle.oscal_build import emit


def _record(**overrides):
    base = {
        "evidence_id": "e1", "run_id": "run-1", "stage": "extract",
        "item_ref": "gate:req-1", "call_type": "jev_gate", "attempt_no": 1,
        "http_status": 200, "request_sha256": "abc", "prompt_hash": "p1",
        "request": {"api_key": "[REDACTED]", "prompt": "hi"},
        "response": {"answer": "ok"},
    }
    base.update(overrides)
    return base


def test_exports_one_record_per_call_with_metadata(tmp_path):
    (path,) = emit.export_evidence((_record(),), tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["stage"] == "extract"
    assert payload["item_ref"] == "gate:req-1"
    assert payload["call_type"] == "jev_gate"
    assert payload["attempt_no"] == 1
    assert payload["http_status"] == 200
    assert payload["request_sha256"] == "abc"
    assert payload["prompt_hash"] == "p1"


def test_export_filenames_are_deterministic_and_sanitised(tmp_path):
    first = emit.export_evidence((_record(),), tmp_path / "a")
    second = emit.export_evidence((_record(),), tmp_path / "b")
    assert first[0].name == second[0].name
    assert ":" not in first[0].name and "/" not in first[0].name
    # The same (stage, item_ref, call_type, attempt_no) with different request_sha256
    # (repair-loop / fallback attempts) must not overwrite each other.
    distinct = emit.export_evidence(
        (_record(request_sha256="abc"), _record(request_sha256="def")), tmp_path / "c"
    )
    assert len({path.name for path in distinct}) == 2


def test_export_redacts_secrets_again_as_defence_in_depth(tmp_path):
    (path,) = emit.export_evidence(
        (_record(request={"authorization": "Bearer leaked"}),), tmp_path
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["request"]["authorization"] == "[REDACTED]"
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `nix develop -c pytest tests/unit/oscal_build/test_evidence_export.py -v`
Expected: `ImportError: cannot import name 'emit' from 'smeargle.oscal_build'`.

- [ ] **Step 3: Write the implementation**

Create `src/smeargle/oscal_build/emit.py` (this task adds only the evidence portion; Task 9 appends):

```python
"""Assemble, write, and gate the §11 output layout (pure builders + gate)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from smeargle.observability import redact

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _evidence_name(record: Mapping[str, Any]) -> str:
    # `request_sha256` distinguishes repair-loop / fallback rows that share the same
    # (stage, item_ref, call_type, attempt_no); dropping it would overwrite records.
    stem = "-".join(
        [
            str(record.get("stage", "stage")),
            str(record.get("item_ref", "item")),
            str(record.get("call_type", "call")),
            str(record.get("attempt_no", 0)),
            str(record.get("request_sha256", "")),
        ]
    )
    return _UNSAFE.sub("-", stem).strip("-") + ".json"


def export_evidence(evidence: Sequence[Mapping[str, Any]], output: Path) -> list[Path]:
    directory = Path(output) / "evidence"
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for record in evidence:
        payload = {
            "stage": record.get("stage"),
            "item_ref": record.get("item_ref"),
            "call_type": record.get("call_type"),
            "attempt_no": record.get("attempt_no"),
            "http_status": record.get("http_status"),
            "request_sha256": record.get("request_sha256"),
            "prompt_hash": record.get("prompt_hash"),
            "request": redact(record.get("request")),
            "response": redact(record.get("response")),
        }
        path = directory / _evidence_name(record)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8"
        )
        written.append(path)
    return written
```

Compression is a **run-store implementation detail, not an export format**: the `evidence.request_json`/`response_json` columns hold zlib-compressed, already-redacted blobs (Phase 2 `RunStore.record_evidence`). `pipeline/assemble._decompress` inflates them into the `request`/`response` values on the `Ledger`, and `export_evidence` writes those values as plain (uncompressed) pretty JSON under `evidence/`. The second `redact(...)` call is defence-in-depth, not the only redaction. Exported files therefore satisfy §11.5's "raw LLM/JEV request/response records ... (redacted), one record per call" while remaining human-readable; no downstream consumer needs zlib.

- [ ] **Step 4: Run the tests and see them pass**

Run: `nix develop -c pytest tests/unit/oscal_build/test_evidence_export.py -v`
Expected: `3 passed`. Phase 4 new tests: **3** (running total **26**).

- [ ] **Step 5: Commit**

```bash
git add src/smeargle/oscal_build/emit.py tests/unit/oscal_build/test_evidence_export.py
git commit -m "feat(oscal): export redacted evidence records" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 9: `emit.assemble`, `write_assembly`, and the §11.6 integrity gate

**Files:**
- Modify: `src/smeargle/oscal_build/emit.py`
- Test: `tests/unit/oscal_build/test_emit.py`

**Spec traceability:** §11.6 (accepted coverage, import coverage, `#uuid` resolution, absolute/fragment link rules, globally unique control ids, metaschema validation; the `extract` partial gate validates only the requirements catalog), §11.7 (documents/catalogs sorted by `content_sha256`; all UUIDs from `IdFactory`; deterministic timestamps; a globally zero-relation run omits `mapping-collection.json`).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/oscal_build/test_emit.py`:

```python
import json

import pytest

from support.ledger import CLOCK, IDS, catalog, ledger, mapping_row, requirement

from smeargle.errors import IntegrityError
from smeargle.oscal_build import emit, facade


@pytest.fixture(autouse=True)
def _support(tmp_path):
    facade.configure_support_file(tmp_path / "support.db")


def _assemble(**overrides):
    return emit.assemble(ledger(**overrides), clock=CLOCK, id_factory=IDS)


def test_assembly_contains_every_document_and_gate_passes(tmp_path):
    assembly = _assemble()
    emit.integrity_gate(assembly, ledger())
    written = emit.write_assembly(assembly, tmp_path)
    assert sorted(path.name for path in written) == [
        "mapping-collection.json", "profile.json", "rationale.json",
        "requirements-catalog.json",
    ]


def test_zero_accepted_run_emits_empty_groups_and_passes_gate(tmp_path):
    # No accepted requirement: the requirements catalog still has one (control-less) group
    # per source document and a back-matter resource per document; write_assembly and the
    # integrity gate both accept it, and mapping-collection.json is omitted.
    source = ledger(
        requirements=(requirement(gate="rejected", retrieve=None),), mappings=(), pairs=(),
    )
    assembly = emit.assemble(source, clock=CLOCK, id_factory=IDS)
    assert assembly.mapping_collection is None
    (group,) = assembly.requirements_catalog["catalog"]["groups"]
    assert "controls" not in group
    emit.integrity_gate(assembly, source)
    written = emit.write_assembly(assembly, tmp_path)
    assert "mapping-collection.json" not in {path.name for path in written}


def test_gate_rejects_accepted_requirement_missing_from_every_artifact():
    source = ledger(
        requirements=(requirement("req-1"), requirement("req-2", text="MUST log.")),
        mappings=(mapping_row("req-1"),), catalogs=(catalog(),),
    )
    assembly = emit.assemble(source, clock=CLOCK, id_factory=IDS)
    # Strip req-2 from BOTH the per-catalog gap summary and the run-level list so it is
    # genuinely absent from every artifact before the gate runs.
    mapping_collection = json.loads(json.dumps(assembly.mapping_collection))
    for entry in mapping_collection["mapping-collection"]["mappings"]:
        entry.pop("source-gap-summary", None)
    assembly = emit.Assembly(
        requirements_catalog=assembly.requirements_catalog, profile=assembly.profile,
        mapping_collection=mapping_collection,
        rationale=dict(assembly.rationale, unmapped_requirements=[]),
        unmapped_requirements=(), failures=0,
    )
    with pytest.raises(IntegrityError):
        emit.integrity_gate(assembly, source)


def test_gate_rejects_unresolved_fragment_reference():
    assembly = _assemble()
    broken = json.loads(json.dumps(assembly.requirements_catalog))
    broken["catalog"]["groups"][0]["controls"][0]["links"][0]["href"] = "#deadbeef"
    broken = emit.Assembly(
        requirements_catalog=broken, profile=assembly.profile,
        mapping_collection=assembly.mapping_collection, rationale=assembly.rationale,
        unmapped_requirements=assembly.unmapped_requirements, failures=0,
    )
    with pytest.raises(IntegrityError):
        emit.integrity_gate(broken, ledger())


def test_gate_rejects_relative_reference_link_not_absolute():
    assembly = _assemble()
    broken = json.loads(json.dumps(assembly.profile))
    broken["profile"]["modify"]["alters"][0]["adds"][0]["links"][0]["href"] = "not-a-uri"
    broken = emit.Assembly(
        requirements_catalog=assembly.requirements_catalog, profile=broken,
        mapping_collection=assembly.mapping_collection, rationale=assembly.rationale,
        unmapped_requirements=assembly.unmapped_requirements, failures=0,
    )
    with pytest.raises(IntegrityError):
        emit.integrity_gate(broken, ledger())


def test_gate_rejects_duplicate_control_ids():
    from smeargle.domain.controls import Control

    source = ledger(
        catalogs=(catalog(), catalog("c2", content_sha256="c" * 64)),
        controls=(Control("run-1", "c1", "c-1", "t", "x", "", ""),
                  Control("run-1", "c2", "c-1", "t", "x", "", "")),
    )
    assembly = emit.assemble(source, clock=CLOCK, id_factory=IDS)
    with pytest.raises(IntegrityError):
        emit.integrity_gate(assembly, source)


def test_partial_assembly_emits_only_the_requirements_catalog(tmp_path):
    assembly = emit.assemble(
        ledger(mappings=(), pairs=(), requirements=(requirement(),)),
        clock=CLOCK, id_factory=IDS, partial=True,
    )
    assert assembly.profile is None and assembly.mapping_collection is None
    assert assembly.rationale == {}
    emit.integrity_gate(assembly, ledger(), partial=True)
    assert [path.name for path in emit.write_assembly(assembly, tmp_path)] == [
        "requirements-catalog.json"
    ]
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `nix develop -c pytest tests/unit/oscal_build/test_emit.py -v`
Expected: `AttributeError: module 'smeargle.oscal_build.emit' has no attribute 'assemble'`.

- [ ] **Step 3: Write the implementation**

Append to `src/smeargle/oscal_build/emit.py`:

```python
from dataclasses import dataclass
from urllib.parse import urlsplit

from smeargle.domain.clock import Clock
from smeargle.domain.ids import IdFactory
from smeargle.domain.run import Ledger
from smeargle.errors import CatalogError, IntegrityError
from smeargle.oscal_build import (
    facade,
    mapping as mapping_builder,
    profile as profile_builder,
    rationale as rationale_builder,
    requirements_catalog as requirements_builder,
)


@dataclass(frozen=True, slots=True)
class Assembly:
    requirements_catalog: Mapping[str, Any]
    profile: Mapping[str, Any] | None
    mapping_collection: Mapping[str, Any] | None
    rationale: Mapping[str, Any]
    unmapped_requirements: tuple[str, ...]
    failures: int
    partial: bool = False

    @property
    def gaps(self) -> int:
        return len(self.unmapped_requirements) + self.failures


def assemble(ledger: Ledger, *, clock: Clock, id_factory: IdFactory,
             partial: bool = False) -> Assembly:
    requirements_catalog = requirements_builder.build(
        ledger, clock=clock, id_factory=id_factory
    )
    if partial:
        return Assembly(requirements_catalog, None, None, {}, (), len(ledger.failures),
                        partial=True)
    mapping_collection = mapping_builder.build(ledger, clock=clock, id_factory=id_factory)
    profile = profile_builder.build(
        ledger, mapping_present=mapping_collection is not None, clock=clock,
        id_factory=id_factory,
    )
    rationale = rationale_builder.build(ledger, clock=clock, id_factory=id_factory)
    unmapped = tuple(item["req_id"] for item in rationale["unmapped_requirements"])
    return Assembly(requirements_catalog, profile, mapping_collection, rationale,
                    unmapped, len(ledger.failures))


def write_assembly(assembly: Assembly, output: Path) -> list[Path]:
    output = Path(output)
    written: list[Path] = []
    target = output / "requirements-catalog.json"
    facade.write_document(target, "catalog", assembly.requirements_catalog)
    written.append(target)
    if assembly.profile is not None:
        target = output / "profile.json"
        facade.write_document(target, "profile", assembly.profile)
        written.append(target)
    if assembly.mapping_collection is not None:
        target = output / "mapping-collection.json"
        facade.write_document(target, "mapping-collection", assembly.mapping_collection)
        written.append(target)
    if assembly.rationale:
        target = output / "rationale.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(assembly.rationale, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        written.append(target)
    return written


def _resources(document: Mapping[str, Any], key: str) -> list[Any]:
    return ((document.get(key) or {}).get("back-matter") or {}).get("resources") or []


def _iter_links(node: Any):
    if isinstance(node, Mapping):
        if "href" in node:
            yield node
        for value in node.values():
            yield from _iter_links(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_links(value)


def _resource_uuids(assembly: Assembly) -> set[str]:
    uuids: set[str] = set()
    for document, key in (
        (assembly.requirements_catalog, "catalog"),
        (assembly.profile, "profile"),
        (assembly.mapping_collection, "mapping-collection"),
    ):
        if document is not None:
            for resource in _resources(document, key):
                if resource.get("uuid"):
                    uuids.add(resource["uuid"])
    return uuids


def _control_ids(document: Mapping[str, Any]) -> set[str]:
    # Only catalog controls (never groups or other id+title nodes) can be the target of a
    # `resource-fragment`, so restrict the walk to `controls` arrays.
    ids: set[str] = set()

    def walk_controls(controls: Any) -> None:
        if not isinstance(controls, list):
            return
        for control in controls:
            if not isinstance(control, Mapping):
                continue
            if "id" in control:
                ids.add(str(control["id"]))
            walk_controls(control.get("controls"))

    def walk_groups(groups: Any) -> None:
        if not isinstance(groups, list):
            return
        for group in groups:
            if not isinstance(group, Mapping):
                continue
            walk_controls(group.get("controls"))
            walk_groups(group.get("groups"))

    catalog = document.get("catalog") or {}
    walk_controls(catalog.get("controls"))
    walk_groups(catalog.get("groups"))
    return ids


def _gap_summary_ids(assembly: Assembly) -> set[str]:
    ids: set[str] = set()
    if assembly.mapping_collection is None:
        return ids
    for entry in assembly.mapping_collection["mapping-collection"]["mappings"]:
        summary = entry.get("source-gap-summary") or {}
        for select in summary.get("unmapped-controls", []):
            ids.update(select.get("with-ids", []))
    return ids


def _mapped_ids(assembly: Assembly) -> set[str]:
    ids: set[str] = set()
    if assembly.mapping_collection is None:
        return ids
    for entry in assembly.mapping_collection["mapping-collection"]["mappings"]:
        for map_entry in entry["maps"]:
            ids.update(source["id-ref"] for source in map_entry["sources"])
    return ids


def _validate(model: str | None, document: Mapping[str, Any] | None) -> None:
    if model is None or document is None:
        return
    try:
        facade.validate(model, document)
    except CatalogError as exc:
        raise IntegrityError(str(exc)) from exc


def integrity_gate(assembly: Assembly, ledger: Ledger, *, partial: bool = False) -> None:
    _validate("catalog", assembly.requirements_catalog)
    _check_fragments(assembly)
    _check_unique_control_ids(ledger)
    if partial:
        return
    _validate("profile", assembly.profile)
    _validate("mapping-collection", assembly.mapping_collection)
    _check_accepted_coverage(assembly, ledger)
    _check_imports(assembly, ledger)


def _check_accepted_coverage(assembly: Assembly, ledger: Ledger) -> None:
    represented = _mapped_ids(assembly) | _gap_summary_ids(assembly) | set(
        assembly.unmapped_requirements
    )
    for requirement in ledger.requirements:
        if requirement.gate_status == "passed" and requirement.req_id not in represented:
            raise IntegrityError(
                f"accepted requirement '{requirement.req_id}' is not represented"
            )


def _check_imports(assembly: Assembly, ledger: Ledger) -> None:
    if assembly.profile is None:
        return
    imports = assembly.profile["profile"]["imports"]
    expected = {
        f"catalogs/{Path(catalog['path']).stem}.json" for catalog in ledger.catalogs
    }
    imported = {entry.get("href") for entry in imports}
    if imported != expected:
        raise IntegrityError(
            f"profile imports {sorted(imported)} do not cover catalogs {sorted(expected)}"
        )
    for entry in imports:
        if not entry.get("include-all"):
            raise IntegrityError("every profile import must include-all")


def _check_fragments(assembly: Assembly) -> None:
    uuids = _resource_uuids(assembly)
    req_ids = _control_ids(assembly.requirements_catalog)
    for document, key in (
        (assembly.requirements_catalog, "catalog"),
        (assembly.profile, "profile"),
        (assembly.mapping_collection, "mapping-collection"),
    ):
        if document is None:
            continue
        for link in _iter_links(document):
            href = str(link.get("href", ""))
            if link.get("rel") == "reference":
                if href.startswith("#"):
                    if href[1:] not in uuids:
                        raise IntegrityError(f"fragment reference '{href}' does not resolve")
                elif not urlsplit(href).scheme:
                    raise IntegrityError(f"link href '{href}' is not an absolute URI")
            elif href.startswith("#") and href[1:] not in uuids:
                raise IntegrityError(f"fragment reference '{href}' does not resolve")
            fragment = link.get("resource-fragment")
            if fragment is not None and fragment not in req_ids:
                raise IntegrityError(
                    f"resource-fragment '{fragment}' does not resolve in the requirements catalog"
                )


def _check_unique_control_ids(ledger: Ledger) -> None:
    seen: set[str] = set()
    for control in ledger.controls:
        if control.control_id in seen:
            raise IntegrityError(f"duplicate control id '{control.control_id}'")
        seen.add(control.control_id)
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `nix develop -c pytest tests/unit/oscal_build/test_emit.py -v`
Expected: `7 passed`. Phase 4 new tests: **7** (running total **33**).

- [ ] **Step 5: Run ruff and commit**

Run: `nix develop -c ruff check src/smeargle/oscal_build`
Expected: `All checks passed!`

```bash
git add src/smeargle/oscal_build/emit.py tests/unit/oscal_build/test_emit.py
git commit -m "feat(oscal): assemble artifacts and enforce integrity gate" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 10: `RunStore` Phase 4 queries and Stage 6 `pipeline/assemble.py`

**Files:**
- Modify: `src/smeargle/store/run_store.py`
- Create: `src/smeargle/pipeline/assemble.py`
- Test: `tests/unit/store/test_run_store_phase4.py`
- Test: `tests/unit/pipeline/test_assemble.py`

**Spec traceability:** §11 (assembly reads the ledger), §7 (candidate pairs carry classify columns; attempts are durable evidence), §11.7 (domain/family labels resolved from the cached `domain_index`).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/store/test_run_store_phase4.py`:

```python
from smeargle.domain.mapping import CandidatePair
from smeargle.domain.requirements import Keyword, Requirement
from smeargle.store.run_store import RunStore


def test_list_pair_rows_returns_classify_columns(tmp_path):
    with RunStore.open(tmp_path) as store:
        store.create_run("run-1", "fp", "ch")
        store.add_candidate_pair(
            CandidatePair("run-1", "pair-1", "req-1", "c-1", "c-1.1", "passed", 0.9)
        )
        store.set_pair_classify(
            "run-1", "pair-1", classify_status="done", relation="subset-of",
            confidence_percentage=0.85, confidence_category="high",
        )
        (row,) = store.list_pair_rows("run-1")
        assert row["classify_status"] == "done"
        assert row["relation"] == "subset-of"
        assert row["confidence_percentage"] == 0.85
        assert row["confidence_category"] == "high"


def test_list_attempts_returns_rows_in_stable_order(tmp_path):
    with RunStore.open(tmp_path) as store:
        store.create_run("run-1", "fp", "ch")
        for ref in ("pair-2", "pair-1"):
            store.record_attempt(
                run_id="run-1", stage="verify", item_ref=ref, call_type="jev_noul",
                attempt_no=0, error_class="per_item_failure", error="boom",
            )
        assert [row["item_ref"] for row in store.list_attempts("run-1")] == [
            "pair-1", "pair-2"
        ]


def test_add_requirement_still_typed_for_ledger(tmp_path):
    with RunStore.open(tmp_path) as store:
        store.create_run("run-1", "fp", "ch")
        store.add_requirement_if_absent(
            Requirement("run-1", "req-1", "d1", 0, "MUST x", "MUST x", Keyword.MUST,
                        "proposed", "passed", 0.9, "MUST", "nominated")
        )
        (requirement,) = store.list_requirements("run-1")
        assert requirement.req_id == "req-1"
```

Create `tests/unit/pipeline/test_assemble.py`:

```python
import json
import zlib

import pytest

from support.ledger import CLOCK, IDS

from smeargle.domain.controls import Control
from smeargle.domain.mapping import CandidatePair, MappingRecord, Relationship
from smeargle.domain.requirements import Keyword, Requirement
from smeargle.errors import IntegrityError
from smeargle.pipeline import assemble
from smeargle.store.run_store import CatalogRow, RunStore


def _settings(tmp_path):
    from smeargle.config import Settings

    settings = Settings.load()
    settings.state_dir = tmp_path / "state"
    settings.output = tmp_path / "out"
    settings.llm.model = "test-model"
    return settings


def _seed(store):
    store.create_run("run-1", "fp", "ch")
    store.add_document(
        type("D", (), {
            "run_id": "run-1", "doc_id": "d1", "ordinal": 0, "path": "/in/spec.txt",
            "uri": "file:///in/spec.txt", "external_id": None, "media_type": "text/plain",
            "content_sha256": "a" * 64, "size_bytes": 3, "text": "x",
        })()
    )
    store.add_requirement_if_absent(
        Requirement("run-1", "req-1", "d1", 0, "MUST x", "MUST x", Keyword.MUST,
                    "proposed", "passed", 0.9, "MUST", "nominated")
    )
    store.add_catalog(CatalogRow(
        run_id="run-1", catalog_id="cat-1", ordinal=0, uri="file:///in/vendor.json",
        path="/in/vendor.json", external_id=None, content_sha256="b" * 64,
        oscal_version="1.2.3", status="loaded",
    ))
    store.add_control(Control("run-1", "cat-1", "c-1.1", "Policy", "text", "access", "Access"))
    store.add_candidate_pair(
        CandidatePair("run-1", "pair-1", "req-1", "cat-1", "c-1.1", "passed", 0.9),
        mapped_threshold=0.5,
    )
    store.set_pair_classify(
        "run-1", "pair-1", classify_status="done", relation="subset-of",
        confidence_percentage=0.85, confidence_category="high",
    )
    store.add_mapping(
        MappingRecord("run-1", "req-1", "cat-1", "c-1.1", Relationship.SUBSET_OF, 0.85, "high")
    )
    store.record_evidence(
        run_id="run-1", stage="classify", item_ref="pair:pair-1", call_type="jev_choice",
        request={"api_key": "secret"}, response={"answers": []}, attempt_no=1,
    )


def test_run_assemble_reads_ledger_writes_layout_and_exports_evidence(tmp_path):
    settings = _settings(tmp_path)
    with RunStore.open(settings.state_dir, clock=CLOCK, id_factory=IDS) as store:
        _seed(store)
        result = assemble.run_assemble(
            store, "run-1", settings.output, clock=CLOCK, id_factory=IDS,
            settings=settings, config={"llm": {"model": "test-model"}},
        )
    assert result.gaps == 0
    assert (settings.output / "requirements-catalog.json").exists()
    assert (settings.output / "rationale.json").exists()
    assert list((settings.output / "evidence").glob("*.json"))


def test_run_assemble_partial_stops_at_the_requirements_catalog(tmp_path):
    settings = _settings(tmp_path)
    with RunStore.open(settings.state_dir, clock=CLOCK, id_factory=IDS) as store:
        _seed(store)
        result = assemble.run_assemble(
            store, "run-1", settings.output, clock=CLOCK, id_factory=IDS,
            settings=settings, config={}, partial=True,
        )
    assert result.profile is None
    assert (settings.output / "requirements-catalog.json").exists()
    assert not (settings.output / "rationale.json").exists()


def test_run_assemble_counts_per_item_failure_attempts_as_gaps(tmp_path):
    settings = _settings(tmp_path)
    with RunStore.open(settings.state_dir, clock=CLOCK, id_factory=IDS) as store:
        _seed(store)
        store.record_attempt(
            run_id="run-1", stage="verify", item_ref="pair-1", call_type="jev_noul",
            attempt_no=0, error_class="per_item_failure", error="boom",
        )
        result = assemble.run_assemble(
            store, "run-1", settings.output, clock=CLOCK, id_factory=IDS,
            settings=settings, config={},
        )
    assert result.failures == 1
    assert result.gaps == 1


def test_run_assemble_checks_integrity_before_writing_any_assemble_artifact(tmp_path, monkeypatch):
    # This covers the real §3 write-ordering invariant: assemble-owned artifacts and
    # evidence (requirements-catalog/profile/mapping-collection/rationale + evidence/) are
    # written only after the gate passes. Stage 2 catalogs are written by `ingest_catalogs`
    # earlier and are outside this invariant.
    settings = _settings(tmp_path)
    with RunStore.open(settings.state_dir, clock=CLOCK, id_factory=IDS) as store:
        _seed(store)
        checked: list[str] = []

        def boom(assembly, ledger, *, partial=False):
            checked.append("gate")
            raise IntegrityError("broken output")

        monkeypatch.setattr(assemble.emit, "integrity_gate", boom)
        with pytest.raises(IntegrityError):
            assemble.run_assemble(
                store, "run-1", settings.output, clock=CLOCK, id_factory=IDS,
                settings=settings, config={},
            )
    assert checked == ["gate"]
    assert not (settings.output / "requirements-catalog.json").exists()
    assert not (settings.output / "rationale.json").exists()
    assert not (settings.output / "evidence").exists()


def test_decompress_round_trips_compressed_evidence():
    blob = zlib.compress(json.dumps({"answers": [{"answer": "yes"}]}).encode())
    decoded = assemble._decompress(
        {"request_json": zlib.compress(b"{}"), "response_json": blob}
    )
    assert decoded["response"] == {"answers": [{"answer": "yes"}]}
    assert decoded["request"] == {}
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `nix develop -c pytest tests/unit/store/test_run_store_phase4.py tests/unit/pipeline/test_assemble.py -v`
Expected: `AttributeError: 'RunStore' object has no attribute 'list_pair_rows'` and `ModuleNotFoundError: No module named 'smeargle.pipeline.assemble'`.

- [ ] **Step 3: Write the implementation**

Append to `src/smeargle/store/run_store.py` inside `class RunStore`:

```python
    def list_pair_rows(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM candidate_pairs WHERE run_id = ? ORDER BY pair_id", (run_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    def list_attempts(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM attempts WHERE run_id = ? ORDER BY stage, item_ref,"
            " call_type, attempt_no",
            (run_id,),
        ).fetchall()
        return [dict(row) for row in rows]
```

Create `src/smeargle/pipeline/assemble.py`:

```python
"""Stage 6: read the ledger and assemble the §11 output (spec 11)."""

from __future__ import annotations

import json
import zlib
from pathlib import Path
from typing import Any, Mapping

from smeargle.config import Settings
from smeargle.domain.clock import Clock
from smeargle.domain.ids import IdFactory
from smeargle.domain.run import Ledger
from smeargle.oscal_build import emit
from smeargle.pipeline import index
from smeargle.prompts import indexing as indexing_prompt
from smeargle.store.run_store import RunStore


def _decompress(row: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(row)
    for key, name in (("request_json", "request"), ("response_json", "response")):
        blob = record.get(key)
        record[name] = json.loads(zlib.decompress(blob)) if blob else None
    return record


def _domains(store: RunStore, catalogs: list[dict[str, Any]],
             settings: Settings) -> dict[str, str]:
    model_id = settings.llm.model or "default"
    domains: dict[str, str] = {}
    for catalog in sorted(catalogs, key=lambda c: (c["content_sha256"], c["catalog_id"])):
        cached = index.cached_domain_index(
            store, catalog["content_sha256"], model_id, indexing_prompt.PROMPT_HASH
        )
        if cached is None:
            continue
        for domain, control_ids in cached.domains.items():
            for control_id in control_ids:
                domains[control_id] = domain
    return domains


def build_ledger(store: RunStore, run_id: str, *, settings: Settings,
                 config: Mapping[str, Any]) -> Ledger:
    run = dict(store.get_run(run_id) or {})
    run["config"] = dict(config)
    catalogs = store.list_catalogs(run_id)
    failures = tuple(
        row for row in store.list_attempts(run_id)
        if row.get("error_class") == "per_item_failure"
    )
    return Ledger(
        run_id=run_id,
        documents=tuple(store.list_documents(run_id)),
        requirements=tuple(store.list_requirements(run_id)),
        catalogs=tuple(catalogs),
        controls=tuple(store.list_controls(run_id)),
        pairs=tuple(store.list_pair_rows(run_id)),
        mappings=tuple(store.list_mappings(run_id)),
        evidence=tuple(_decompress(row) for row in store.list_evidence(run_id)),
        domains=_domains(store, catalogs, settings),
        failures=failures,
        run=run,
    )


def run_assemble(
    store: RunStore,
    run_id: str,
    output: Path,
    *,
    clock: Clock,
    id_factory: IdFactory,
    settings: Settings,
    config: Mapping[str, Any],
    partial: bool = False,
) -> emit.Assembly:
    ledger = build_ledger(store, run_id, settings=settings, config=config)
    assembly = emit.assemble(ledger, clock=clock, id_factory=id_factory, partial=partial)
    # §3 order: assemble → integrity gate (validate everything) → write outputs/export
    # evidence. A gate failure (exit 7) must leave NO assemble-owned artifacts or evidence
    # on disk (requirements-catalog/profile/mapping-collection/rationale + evidence/), so
    # nothing here is written until the gate has passed. Phase 2's Stage 2 `ingest_catalogs`
    # already wrote output/catalogs/*.json before assembly; that pre-assembly output is
    # external to this invariant and is deliberately not rolled back.
    emit.integrity_gate(assembly, ledger, partial=partial)
    emit.write_assembly(assembly, Path(output))
    emit.export_evidence(ledger.evidence, Path(output))
    return assembly
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `nix develop -c pytest tests/unit/store/test_run_store_phase4.py tests/unit/pipeline/test_assemble.py -v`
Expected: `8 passed` (3 store + 5 assemble). Phase 4 new tests: **8** (running total **41**).

- [ ] **Step 5: Commit**

```bash
git add src/smeargle/store/run_store.py src/smeargle/pipeline/assemble.py tests/unit/store/test_run_store_phase4.py tests/unit/pipeline/test_assemble.py
git commit -m "feat(pipeline): add stage 6 assemble over the ledger" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 11: Orchestrator completion — estimates, gap stamping, `extract`/`map`/`resume`

**Files:**
- Modify: `src/smeargle/pipeline/run.py`
- Modify: `src/smeargle/pipeline/retrieve.py`
- Modify: `src/smeargle/errors.py` (only if `UsageError` is not already exported — it is)
- Test: `tests/integration/test_orchestrator.py` (extend)
- Test: `tests/integration/test_phase4_output.py`

**Spec traceability:** §3 (stage pipeline), §12.1 (pre-flight estimate after Stage 1 and Stage 3; resume), §15 (per-item failures recorded; exit-6 gap stamping), §10 Stage 3 (nomination cap), §11.7 (determinism). This task adds the four orchestrator integration tests plus the three remaining `tests/integration/test_phase4_output.py` bodies.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_orchestrator.py`. The module already defines `_settings`, `_fixtures`, `_chat`, and `_answers`; add a fully-mapped route helper and call it in every new test. (Do **not** reuse the module's existing `_jev_router`: it answers `MUST` to every `choice`, so the Stage-5 classification would be unparseable and no mapping would be emitted.)

```python
def _mock_pipeline():
    def chat_router(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        if "extract normative requirements" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"requirements": [
                {"text": "The system MUST encrypt data at rest.", "keyword": "MUST"}]})))
        if "classify security controls" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"labels": [
                {"control_id": "c-1.1", "domain": "access", "family": "Access"}]})))
        if "control domains" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"domains": ["access"]})))
        return httpx.Response(200, json=_chat(json.dumps({"control_ids": ["c-1.1"]})))

    def jev_router(request):
        question = json.loads(request.content)["questions"][0]
        if question["kind"] == "noul":
            return httpx.Response(200, json=_answers(("yes", 0.9)))
        if "MUST" in question.get("options", []):
            return httpx.Response(200, json=_answers(("MUST", 0.9)))
        return httpx.Response(200, json=_answers(("subset-of", 0.85)))

    respx.post("https://llm.example/v1/chat/completions").mock(side_effect=chat_router)
    respx.post("https://jev.example/v1/systemone").mock(side_effect=jev_router)


@respx.mock
def test_run_pipeline_emits_artifacts_and_reports_zero_gaps(tmp_path):
    _mock_pipeline()
    settings = _settings(tmp_path)
    document, catalog = _fixtures(tmp_path)
    seen = []
    result = run_pipeline.run_pipeline(
        state_dir=settings.state_dir, output=settings.output,
        input_paths=[document], catalog_paths=[catalog], settings=settings,
        clock=FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        id_factory=UuidIdFactory(), run_id="run-out",
        estimate=lambda kind, count: seen.append((kind, count)),
    )
    assert result.gaps == 0
    assert (settings.output / "requirements-catalog.json").exists()
    assert ("requirements", 1) in seen and any(kind == "candidates" for kind, _ in seen)


@respx.mock
def test_run_extract_only_writes_partial_output(tmp_path):
    _mock_pipeline()
    settings = _settings(tmp_path)
    document, _catalog = _fixtures(tmp_path)
    result = run_pipeline.run_extract_only(
        state_dir=settings.state_dir, output=settings.output, input_paths=[document],
        settings=settings, clock=FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        id_factory=UuidIdFactory(), run_id="run-x",
    )
    assert (settings.output / "requirements-catalog.json").exists()
    assert not (settings.output / "profile.json").exists()
    assert result.run_id == "run-x"


@respx.mock
def test_run_map_completes_an_extract_only_run(tmp_path):
    _mock_pipeline()
    settings = _settings(tmp_path)
    document, catalog = _fixtures(tmp_path)
    run_pipeline.run_extract_only(
        state_dir=settings.state_dir, output=settings.output, input_paths=[document],
        settings=settings, clock=FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        id_factory=UuidIdFactory(), run_id="run-map",
    )
    result = run_pipeline.run_map(
        state_dir=settings.state_dir, output=settings.output, catalog_paths=[catalog],
        settings=settings, clock=FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        id_factory=UuidIdFactory(), run_id="run-map",
    )
    assert result.run_id == "run-map"
    assert (settings.output / "profile.json").exists()


@respx.mock
def test_resume_run_reuses_recorded_documents(tmp_path):
    _mock_pipeline()
    settings = _settings(tmp_path)
    document, catalog = _fixtures(tmp_path)
    run_pipeline.run_pipeline(
        state_dir=settings.state_dir, output=settings.output,
        input_paths=[document], catalog_paths=[catalog], settings=settings,
        clock=FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        id_factory=UuidIdFactory(), run_id="run-resume",
    )
    result = run_pipeline.resume_run(
        state_dir=settings.state_dir, output=settings.output, settings=settings,
        clock=FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        id_factory=UuidIdFactory(), run_id="run-resume",
    )
    assert result.run_id == "run-resume"
```

Create `tests/integration/test_phase4_output.py`:

```python
import json
from datetime import datetime, timezone

import httpx
import respx

from support.schemas import validate_against_schema

from smeargle.config import Settings
from smeargle.domain.clock import FrozenClock
from smeargle.domain.ids import UuidIdFactory
from smeargle.oscal_build import facade
from smeargle.pipeline import run as run_pipeline


def _clock():
    return FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc))


def _settings(tmp_path):
    settings = Settings.load()
    settings.state_dir = tmp_path / "state"
    settings.output = tmp_path / "out"
    settings.llm.endpoint = "https://llm.example"
    settings.llm.model = "test-model"
    settings.jev.endpoint = "https://jev.example"
    settings.jev.model = "jev-model"
    return settings


def _fixtures(tmp_path):
    document = tmp_path / "spec.txt"
    document.write_text("The system MUST encrypt data at rest.", encoding="utf-8")
    catalog = tmp_path / "vendor.json"
    catalog.write_text(
        json.dumps({"catalog": {"name": "V", "securityControls": [
            {"controlId": "1.1", "title": "Policy", "family": "Access"}]}}),
        encoding="utf-8",
    )
    return document, catalog


def _chat(content):
    return {"choices": [{"message": {"content": json.dumps(content)}}]}


def _answers(answer, confidence):
    return {"answers": [{"question": "q", "answer": answer, "answer_confidence": confidence}]}


def _mock_endpoints():
    def llm(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        if "extract normative requirements" in prompt:
            return httpx.Response(200, json=_chat({"requirements": [
                {"text": "The system MUST encrypt data at rest.", "keyword": "MUST"}]}))
        if "classify security controls" in prompt:
            return httpx.Response(200, json=_chat({"labels": [
                {"control_id": "c-1.1", "domain": "access", "family": "Access"}]}))
        if "control domains" in prompt:
            return httpx.Response(200, json=_chat({"domains": ["access"]}))
        return httpx.Response(200, json=_chat({"control_ids": ["c-1.1"]}))

    respx.post("https://llm.example/v1/chat/completions").mock(side_effect=llm)
    respx.post("https://jev.example/v1/systemone").mock(side_effect=[
        httpx.Response(200, json=_answers("yes", 0.9)),
        httpx.Response(200, json=_answers("MUST", 0.9)),
        httpx.Response(200, json=_answers("yes", 0.9)),
        httpx.Response(200, json=_answers("subset-of", 0.85)),
    ])


@respx.mock
def test_full_run_output_validates_against_vendored_schemas(tmp_path):
    facade.configure_support_file(tmp_path / "support.db")
    _mock_endpoints()
    settings = _settings(tmp_path)
    document, catalog = _fixtures(tmp_path)
    result = run_pipeline.run_pipeline(
        state_dir=settings.state_dir, output=settings.output,
        input_paths=[document], catalog_paths=[catalog], settings=settings,
        clock=_clock(), id_factory=UuidIdFactory(), run_id="run-a",
    )
    assert result.gaps == 0
    validate_against_schema(
        "catalog", json.loads((settings.output / "requirements-catalog.json").read_text())
    )
    validate_against_schema(
        "profile", json.loads((settings.output / "profile.json").read_text())
    )
    validate_against_schema(
        "mapping-collection",
        json.loads((settings.output / "mapping-collection.json").read_text()),
    )
    assert json.loads((settings.output / "rationale.json").read_text())["run"]["run_id"] == "run-a"


def test_vendored_schema_rejects_adversarial_mapping():
    import jsonschema_rs
    import pytest

    with pytest.raises(jsonschema_rs.ValidationError):
        validate_against_schema(
            "mapping-collection",
            {"mapping-collection": {"uuid": "not-a-uuid", "metadata": {},
                                    "provenance": {}, "mappings": []}},
        )


def test_assembly_is_value_identical_for_the_same_ledger(tmp_path):
    from support.ledger import CLOCK, IDS, ledger

    from smeargle.oscal_build import emit

    source = ledger()
    first = emit.assemble(source, clock=CLOCK, id_factory=IDS)
    second = emit.assemble(source, clock=CLOCK, id_factory=IDS)
    for key in ("requirements_catalog", "profile", "mapping_collection", "rationale"):
        assert json.dumps(getattr(first, key), sort_keys=True) == json.dumps(
            getattr(second, key), sort_keys=True
        )
```

> The byte-level reassembly proof is kept once, in Task 15's
> `test_reassembling_the_same_ledger_is_byte_identical`; this task keeps only the
> in-memory dict-equality check to avoid duplicating it.

- [ ] **Step 2: Run the tests and see them fail**

Run: `nix develop -c pytest tests/integration/test_phase4_output.py -v`
Expected: `test_assembly_is_value_identical_for_the_same_ledger` passes immediately (it only exercises `emit`); the full-run test fails because `run_pipeline` does not yet assemble.

- [ ] **Step 3: Write the implementation**

First, modify `src/smeargle/pipeline/retrieve.py` — replace `nominate_controls` and add `cap` to `retrieve_requirement`:

```python
def nominate_controls(
    llm: LLMClient, requirement: str, controls: Sequence[Control], *,
    cap: int = 0, meta: Optional[CallMeta] = None,
) -> list[str]:
    known = {control.control_id for control in controls}
    listing = [{"id": control.control_id, "text": control.text} for control in controls]
    messages = [
        {"role": "user", "content": retrieval_prompt.render_nomination(requirement, listing)}
    ]
    response = llm.complete_json(NominationResponseModel, messages, meta=meta)
    nominated: list[str] = []
    for control_id in response.control_ids:
        if control_id in known and control_id not in nominated:
            nominated.append(control_id)
    if cap > 0:
        nominated = nominated[:cap]
    return nominated
```

Then replace `retrieve_requirement` with the full body below so the `cap` thread-through is explicit:

```python
def retrieve_requirement(
    llm: LLMClient,
    requirement: Requirement,
    domain_index: DomainIndex,
    controls: Sequence[Control],
    *,
    meta_prefix: str,
    cap: int = 0,
) -> list[tuple[str, str]]:
    mapping = domain_controls(domain_index, controls)
    chosen = relevant_domains(
        llm,
        requirement.text,
        list(mapping),
        meta=CallMeta(
            stage="retrieve", item_ref=f"{meta_prefix}:domains", call_type="llm_domains",
            prompt_hash=retrieval_prompt.DOMAIN_PROMPT_HASH,
        ),
    )
    by_id = {control.control_id: control for control in controls}
    nominated: list[tuple[str, str]] = []
    for domain in chosen:
        control_ids = nominate_controls(
            llm,
            requirement.text,
            mapping[domain],
            cap=cap,
            meta=CallMeta(
                stage="retrieve", item_ref=f"{meta_prefix}:nominated:{domain}",
                call_type="llm_nomination",
                prompt_hash=retrieval_prompt.NOMINATION_PROMPT_HASH,
            ),
        )
        for control_id in control_ids:
            control = by_id[control_id]
            pair = (control.catalog_id, control.control_id)
            if pair not in nominated:
                nominated.append(pair)
    return nominated
```

Then modify `src/smeargle/pipeline/run.py`:

1. Extend the existing Phase 3 import lines rather than appending duplicates (ruff `I001`/`F811`): add `Callable` to the existing `from typing import Any, Iterable, Optional, Sequence`, add `UsageError` to the existing `from smeargle.errors import FatalServiceError, ServiceError`, and add `assemble as assemble_stage` to the existing `from smeargle.pipeline import (...)` block. Then widen `RunResult`:

```python
from typing import Any, Callable, Iterable, Optional, Sequence

from smeargle.errors import FatalServiceError, ServiceError, UsageError
from smeargle.pipeline import (
    assemble as assemble_stage,
    classify,
    extract,
    index,
    load,
    retrieve,
    verify,
    work,
)
```

```python
@dataclass(frozen=True, slots=True)
class RunResult:
    run_id: str
    fingerprint: str
    config_hash: str
    document_count: int
    requirement_count: int
    candidate_count: int
    output: Optional[Path] = None
    gaps: int = 0
    unmapped_count: int = 0
    failure_count: int = 0
```

2. Add the failure recorder and assemble helper:

```python
def _record_failures(writer, run_id: str, stage: str, call_type: str, results) -> int:
    count = 0
    for key, _value, error in results:
        if error is None:
            continue
        count += 1

        def op(store, key=key, error=error):
            store.record_attempt(
                run_id=run_id, stage=stage, item_ref=str(key), call_type=call_type,
                attempt_no=0, error_class="per_item_failure", error=str(error),
                duration_ms=0,
            )

        writer.call(op)
    return count


def _assemble_out(writer, run_id, output, *, settings, clock, id_factory, config, partial):
    return writer.call(
        lambda store: assemble_stage.run_assemble(
            store, run_id, output, clock=clock, id_factory=id_factory,
            settings=settings, config=config, partial=partial,
        )
    )
```

3. Replace `run_extract`, `run_retrieve`, `run_verify`, and `run_classify` with the complete functions below. Each returns `int` (its per-item failure count) so `run_pipeline` can sum it into `RunResult.failure_count`/`gaps` and the §15 exit-6 accounting is durable. `run_index_llm` keeps its Phase 3 `bool` return contract and is unchanged; the existing Phase 3 imports already provide `CandidatePair`, `pair_id_for`, `req_id_for`, and `replace`.

```python
def run_extract(
    writer: Writer, run_id: str, *, settings: Settings, pool: ThreadPoolExecutor,
    llm, jev,
) -> int:
    failures = 0
    writer.call(lambda store: work.claim_stage(store, run_id, "extract"))
    documents = writer.call(lambda store: work.pending_documents(store, run_id))
    jobs: list[tuple[Any, Any]] = []
    payloads: dict[Any, Any] = {}
    for document in documents:
        _media_type, text = loader_registry.load_document(Path(document["path"]))
        chunks = extract.chunk_text(
            text,
            chunk_size=settings.execution.chunk_size,
            overlap=settings.execution.chunk_overlap,
        )
        for position, chunk in enumerate(chunks):
            ref = work.chunk_ref(document["doc_id"], position)
            stage = f"extract:{ref}"
            if writer.call(
                lambda store, stage=stage: work.stage_complete(store, run_id, stage)
            ):
                continue
            key = (document["ordinal"], position)
            writer.call(lambda store, stage=stage: work.claim_stage(store, run_id, stage))
            meta = CallMeta(
                stage="extract", item_ref=ref, call_type="llm_extract",
                prompt_hash=extraction_prompt.PROMPT_HASH,
            )
            jobs.append((key, lambda chunk=chunk, meta=meta: extract.propose_chunk(llm, chunk, meta=meta)))
            payloads[key] = (document, position, chunk, stage)

    proposals: list[tuple[Any, str, Requirement]] = []
    completed: list[Any] = []
    chunk_results = _fan_out(pool, jobs)
    failures += _record_failures(writer, run_id, "extract", "llm_extract", chunk_results)
    for key, outcome, error in chunk_results:
        if error is not None:
            continue
        completed.append(key)
        document, position, _chunk, _stage = payloads[key]
        for order, (text, keyword, _rationale) in enumerate(outcome):
            normalised = extract.normalise_text(text)
            req_id = req_id_for(document["content_sha256"], normalised)
            requirement = Requirement(
                run_id=run_id, req_id=req_id, doc_id=document["doc_id"], ordinal=0,
                text=text, normalized_text=normalised, keyword=keyword,
                extract_status="proposed", gate_status=None, gate_noul_prob=None,
                gate_choice=None, retrieve_status=None,
            )
            proposals.append(((document["ordinal"], position, order), req_id, requirement))

    unique: dict[str, Requirement] = {}
    for _key, req_id, requirement in sorted(proposals, key=lambda item: item[0]):
        unique.setdefault(req_id, requirement)
    ordered = [replace(requirement, ordinal=index) for index, requirement in enumerate(unique.values())]
    persist_sorted(
        writer, [(requirement.req_id, requirement) for requirement in ordered],
        lambda store, requirement: store.add_requirement_if_absent(requirement),
    )
    for key in sorted(completed):
        _document, _position, _chunk, stage = payloads[key]
        writer.call(lambda store, stage=stage: work.complete_stage(store, run_id, stage))

    gate_requirements = writer.call(lambda store: work.pending_gate(store, run_id))
    gate_jobs: list[tuple[Any, Any]] = []
    for requirement in gate_requirements:
        meta = CallMeta(stage="extract", item_ref=f"gate:{requirement.req_id}", call_type="jev_gate")
        gate_jobs.append(
            (
                requirement.req_id,
                lambda requirement=requirement, meta=meta: (
                    requirement,
                    extract.gate_requirement(
                        jev, requirement,
                        threshold=settings.mapping.extract_gate_threshold,
                        min_confidence=settings.jev.min_confidence, meta=meta,
                    ),
                ),
            )
        )
    gate_results = _fan_out(pool, gate_jobs)
    failures += _record_failures(writer, run_id, "extract", "jev_gate", gate_results)

    def apply_gate(store, item) -> None:
        requirement, outcome = item
        store.set_requirement_gate(
            run_id, requirement.req_id, gate_status=outcome.gate_status,
            gate_noul_prob=outcome.gate_noul_prob, gate_choice=outcome.gate_choice,
            keyword=outcome.keyword.value if outcome.keyword else None,
            extract_status=outcome.extract_status,
        )

    persist_sorted(
        writer,
        [(key, item) for key, item, error in gate_results if error is None],
        apply_gate,
    )
    writer.call(lambda store: work.complete_stage(store, run_id, "extract"))
    return failures


def run_retrieve(
    writer: Writer, run_id: str, *, settings: Settings, pool: ThreadPoolExecutor, llm
) -> int:
    writer.call(lambda store: work.claim_stage(store, run_id, "retrieve"))
    model_id = settings.llm.model or "default"
    indexes = []
    for catalog in writer.call(lambda store: store.list_catalogs(run_id)):
        cached = writer.call(
            lambda store, catalog=catalog: index.cached_domain_index(
                store, catalog["content_sha256"], model_id, indexing_prompt.PROMPT_HASH
            )
        )
        if cached is not None:
            indexes.append(cached)
    domain_index = retrieve.merge_domain_indexes(indexes)
    controls = writer.call(lambda store: store.list_controls(run_id))
    requirements = writer.call(lambda store: work.pending_retrieval(store, run_id))
    jobs = [
        (
            requirement.req_id,
            lambda requirement=requirement: (
                requirement,
                retrieve.retrieve_requirement(
                    llm, requirement, domain_index, controls,
                    meta_prefix=f"req:{requirement.req_id}",
                    cap=settings.mapping.nomination_cap,
                ),
            ),
        )
        for requirement in requirements
    ]
    results = _fan_out(pool, jobs)
    failures = _record_failures(writer, run_id, "retrieve", "llm_nomination", results)

    def apply(store, item) -> None:
        requirement, pairs = item
        if not pairs:
            store.set_requirement_retrieve_status(run_id, requirement.req_id, "none")
            return
        for catalog_id, control_id in pairs:
            store.add_candidate_pair(
                CandidatePair(
                    run_id=run_id,
                    pair_id=pair_id_for(requirement.req_id, catalog_id, control_id),
                    req_id=requirement.req_id, catalog_id=catalog_id, control_id=control_id,
                    verify_status="pending",
                ),
                mapped_threshold=settings.mapping.mapped_threshold,
            )
        store.set_requirement_retrieve_status(run_id, requirement.req_id, "nominated")

    persist_sorted(
        writer,
        [(key, item) for key, item, error in results if error is None],
        apply,
    )
    writer.call(lambda store: work.complete_stage(store, run_id, "retrieve"))
    return failures


def run_verify(
    writer: Writer, run_id: str, *, settings: Settings, pool: ThreadPoolExecutor, jev
) -> int:
    writer.call(lambda store: work.claim_stage(store, run_id, "verify"))
    requirements = {r.req_id: r for r in writer.call(lambda store: store.list_requirements(run_id))}
    controls = {
        (c.catalog_id, c.control_id): c for c in writer.call(lambda store: store.list_controls(run_id))
    }
    pairs = writer.call(lambda store: work.pending_verify(store, run_id))
    items = [
        (pair, requirements[pair.req_id].text, controls[(pair.catalog_id, pair.control_id)].text)
        for pair in pairs
    ]
    persisted: list[tuple[Any, Any]] = []
    failures = 0
    if settings.jev.batch and items:
        batch_jobs = []
        for start in range(0, len(items), settings.jev.batch_size):
            group = items[start : start + settings.jev.batch_size]
            pair_group = [pair for pair, _requirement, _control in group]
            call_items = [(pair.pair_id, requirement, control) for pair, requirement, control in group]
            meta = CallMeta(
                stage="verify", item_ref=f"batch:{pair_group[0].pair_id}", call_type="jev_noul"
            )
            batch_jobs.append(
                (
                    pair_group[0].pair_id,
                    lambda pair_group=pair_group, call_items=call_items, meta=meta: list(
                        zip(
                            pair_group,
                            verify.verify_batch(
                                jev, call_items,
                                threshold=settings.mapping.mapped_threshold,
                                min_confidence=settings.jev.min_confidence, meta=meta,
                            ),
                        )
                    ),
                )
            )
        batch_results = _fan_out(pool, batch_jobs)
        failures += _record_failures(writer, run_id, "verify", "jev_noul", batch_results)
        for _key, value, error in batch_results:
            if error is None:
                persisted.extend((pair.pair_id, (pair, outcome)) for pair, outcome in value)
    else:
        jobs = []
        for pair in pairs:
            meta = CallMeta(stage="verify", item_ref=work.pair_ref(pair.req_id, pair.catalog_id, pair.control_id), call_type="jev_noul")
            jobs.append(
                (
                    pair.pair_id,
                    lambda pair=pair, meta=meta: (
                        pair,
                        verify.verify_pair(
                            jev, requirements[pair.req_id].text, controls[(pair.catalog_id, pair.control_id)].text,
                            threshold=settings.mapping.mapped_threshold,
                            min_confidence=settings.jev.min_confidence, meta=meta,
                        ),
                    ),
                )
            )
        results = _fan_out(pool, jobs)
        failures += _record_failures(writer, run_id, "verify", "jev_noul", results)
        persisted = [(key, item) for key, item, error in results if error is None]

    def apply(store, item) -> None:
        pair, outcome = item
        store.set_pair_verify(
            run_id, pair.pair_id, verify_status=outcome.verify_status, noul_prob=outcome.noul_prob
        )

    persist_sorted(writer, persisted, apply)
    writer.call(lambda store: work.complete_stage(store, run_id, "verify"))
    return failures


def run_classify(
    writer: Writer, run_id: str, *, settings: Settings, pool: ThreadPoolExecutor, jev
) -> int:
    writer.call(lambda store: work.claim_stage(store, run_id, "classify"))
    requirements = {r.req_id: r for r in writer.call(lambda store: store.list_requirements(run_id))}
    controls = {
        (c.catalog_id, c.control_id): c for c in writer.call(lambda store: store.list_controls(run_id))
    }
    pairs = writer.call(lambda store: work.pending_classify(store, run_id))
    items = [
        (pair, requirements[pair.req_id].text, controls[(pair.catalog_id, pair.control_id)].text)
        for pair in pairs
    ]
    persisted: list[tuple[Any, Any]] = []
    failures = 0
    if settings.jev.batch and items:
        batch_jobs = []
        for start in range(0, len(items), settings.jev.batch_size):
            group = items[start : start + settings.jev.batch_size]
            pair_group = [pair for pair, _requirement, _control in group]
            call_items = [(pair.pair_id, requirement, control) for pair, requirement, control in group]
            meta = CallMeta(
                stage="classify", item_ref=f"batch:{pair_group[0].pair_id}", call_type="jev_choice"
            )
            batch_jobs.append(
                (
                    pair_group[0].pair_id,
                    lambda pair_group=pair_group, call_items=call_items, meta=meta: list(
                        zip(
                            pair_group,
                            classify.classify_batch(
                                jev, call_items,
                                min_confidence=settings.jev.min_confidence, meta=meta,
                            ),
                        )
                    ),
                )
            )
        batch_results = _fan_out(pool, batch_jobs)
        failures += _record_failures(writer, run_id, "classify", "jev_choice", batch_results)
        for _key, value, error in batch_results:
            if error is None:
                persisted.extend((pair.pair_id, (pair, outcome)) for pair, outcome in value)
    else:
        jobs = []
        for pair in pairs:
            meta = CallMeta(stage="classify", item_ref=f"pair:{pair.pair_id}", call_type="jev_choice")
            jobs.append(
                (
                    pair.pair_id,
                    lambda pair=pair, meta=meta: (
                        pair,
                        classify.classify_pair(
                            jev, requirements[pair.req_id].text,
                            controls[(pair.catalog_id, pair.control_id)].text,
                            min_confidence=settings.jev.min_confidence, meta=meta,
                        ),
                    ),
                )
            )
        results = _fan_out(pool, jobs)
        failures += _record_failures(writer, run_id, "classify", "jev_choice", results)
        persisted = [(key, item) for key, item, error in results if error is None]

    def apply(store, item) -> None:
        pair, outcome = item
        if outcome.classify_status == "done":
            record = classify.build_mapping_record(
                run_id=run_id, req_id=pair.req_id, catalog_id=pair.catalog_id,
                control_id=pair.control_id, outcome=outcome,
                category_high=settings.mapping.category_high,
                category_medium=settings.mapping.category_medium,
            )
            store.add_mapping(record)
            store.set_pair_classify(
                run_id, pair.pair_id, classify_status="done", relation=outcome.relation.value,
                confidence_percentage=outcome.confidence_percentage,
                confidence_category=record.confidence_category,
            )
        else:
            store.set_pair_classify(run_id, pair.pair_id, classify_status=outcome.classify_status)

    persist_sorted(writer, persisted, apply)
    writer.call(lambda store: work.complete_stage(store, run_id, "classify"))
    return failures
```

4. Replace `run_pipeline` with the complete function:

```python
def run_pipeline(
    *,
    state_dir: Path,
    output: Path,
    input_paths: Sequence[Path],
    catalog_paths: Sequence[Path],
    settings: Settings,
    clock: Clock,
    id_factory: IdFactory,
    run_id: Optional[str] = None,
    estimate: Optional[Callable[[str, int], None]] = None,
) -> RunResult:
    input_paths = [Path(p) for p in input_paths]
    catalog_paths = [Path(p) for p in catalog_paths]
    computed_fingerprint = compute_fingerprint(input_paths, catalog_paths)
    config = redact(_phase3_config_snapshot(settings))
    computed_config_hash = config_hash(config)
    selected = run_id or settings.execution.run_id or id_factory.run_uuid()

    writer = Writer(state_dir, clock=clock, id_factory=id_factory)
    writer.start()
    llm_http = jev_http = None
    failures = 0
    assembly = None
    index_ok = False
    try:
        bus = EvidenceBus(writer, selected)
        llm_http, llm = _build_llm(settings, bus)
        jev_http, jev = _build_jev(settings, bus)
        if writer.call(lambda store: store.get_run(selected)) is None:
            writer.call(lambda store: store.create_run(
                selected, computed_fingerprint, computed_config_hash
            ))
        with ThreadPoolExecutor(max_workers=settings.execution.concurrency) as pool:
            if not writer.call(lambda store: work.stage_complete(store, selected, "load")):
                writer.call(lambda store: load.run_load(store, selected, input_paths))
            if not writer.call(lambda store: work.stage_complete(store, selected, "index")):
                writer.call(lambda store: ingest_catalogs(
                    store, selected, catalog_paths, output,
                    catalog_format=settings.execution.catalog_format,
                    clock=clock, id_factory=id_factory,
                ))
            with ThreadPoolExecutor(max_workers=2) as streams:
                extract_stream = streams.submit(
                    run_extract, writer, selected, settings=settings, pool=pool,
                    llm=llm, jev=jev,
                )
                index_stream = streams.submit(
                    run_index_llm, writer, selected, settings=settings, pool=pool, llm=llm
                )
                failures += extract_stream.result()
                index_ok = index_stream.result()
            requirements = writer.call(lambda store: store.list_requirements(selected))
            accepted = [r for r in requirements if r.gate_status == "passed"]
            if estimate is not None:
                estimate("requirements", len(accepted))
            if index_ok:
                failures += run_retrieve(writer, selected, settings=settings, pool=pool, llm=llm)
                candidate_count = writer.call(lambda store: store.counts(selected))["candidate_pairs"]
                if estimate is not None:
                    estimate("candidates", candidate_count)
                failures += run_verify(writer, selected, settings=settings, pool=pool, jev=jev)
                failures += run_classify(writer, selected, settings=settings, pool=pool, jev=jev)
            else:
                # An incomplete index is a gap and emits no artifacts: never report a
                # successful `run` (mirrors run_map).
                failures += 1
            writer.call(lambda store: store.set_run_status(
                selected, "mapped" if index_ok else "index_incomplete", finished=index_ok
            ))
        if index_ok:
            assembly = _assemble_out(
                writer, selected, Path(output), settings=settings, clock=clock,
                id_factory=id_factory, config=config, partial=False,
            )
        counts = writer.call(lambda store: store.counts(selected))
    finally:
        if llm_http is not None:
            llm_http.close()
        if jev_http is not None:
            jev_http.close()
        writer.stop()

    unmapped = len(assembly.unmapped_requirements) if assembly is not None else 0
    return RunResult(
        run_id=selected, fingerprint=computed_fingerprint,
        config_hash=computed_config_hash, document_count=counts["documents"],
        requirement_count=counts["requirements"], candidate_count=counts["candidate_pairs"],
        output=Path(output) if assembly is not None else None,
        gaps=failures + unmapped, unmapped_count=unmapped, failure_count=failures,
    )
```

5. Add `run_extract_only`, `run_map`, and `resume_run` after `run_pipeline`:

```python
def run_extract_only(
    *,
    state_dir: Path,
    output: Path,
    input_paths: Sequence[Path],
    settings: Settings,
    clock: Clock,
    id_factory: IdFactory,
    run_id: Optional[str] = None,
    estimate: Optional[Callable[[str, int], None]] = None,
) -> RunResult:
    input_paths = [Path(p) for p in input_paths]
    computed_fingerprint = compute_fingerprint(input_paths, [])
    config = redact(_phase3_config_snapshot(settings))
    selected = run_id or settings.execution.run_id or id_factory.run_uuid()
    writer = Writer(state_dir, clock=clock, id_factory=id_factory)
    writer.start()
    llm_http = jev_http = None
    failures = 0
    try:
        bus = EvidenceBus(writer, selected)
        llm_http, llm = _build_llm(settings, bus)
        jev_http, jev = _build_jev(settings, bus)
        if writer.call(lambda store: store.get_run(selected)) is None:
            writer.call(lambda store: store.create_run(
                selected, computed_fingerprint, config_hash(config)
            ))
        with ThreadPoolExecutor(max_workers=settings.execution.concurrency) as pool:
            if not writer.call(lambda store: work.stage_complete(store, selected, "load")):
                writer.call(lambda store: load.run_load(store, selected, input_paths))
            failures += run_extract(
                writer, selected, settings=settings, pool=pool, llm=llm, jev=jev
            )
        if estimate is not None:
            requirements = writer.call(lambda store: store.list_requirements(selected))
            estimate("requirements", len([r for r in requirements if r.gate_status == "passed"]))
        _assemble_out(
            writer, selected, Path(output), settings=settings, clock=clock,
            id_factory=id_factory, config=config, partial=True,
        )
        writer.call(lambda store: store.set_run_status(selected, "extracted", finished=True))
        counts = writer.call(lambda store: store.counts(selected))
    finally:
        if llm_http is not None:
            llm_http.close()
        if jev_http is not None:
            jev_http.close()
        writer.stop()
    return RunResult(
        selected, computed_fingerprint, config_hash(config), counts["documents"],
        counts["requirements"], counts["candidate_pairs"], output=Path(output),
        gaps=failures, failure_count=failures,
    )


def run_map(
    *,
    state_dir: Path,
    output: Path,
    catalog_paths: Sequence[Path],
    settings: Settings,
    clock: Clock,
    id_factory: IdFactory,
    run_id: str,
    estimate: Optional[Callable[[str, int], None]] = None,
) -> RunResult:
    with RunStore.open(state_dir, clock=clock, id_factory=id_factory) as probe:
        row = probe.get_run(run_id)
    if row is None:
        raise UsageError(f"run '{run_id}' does not exist")
    config = redact(_phase3_config_snapshot(settings))
    writer = Writer(state_dir, clock=clock, id_factory=id_factory)
    writer.start()
    llm_http = jev_http = None
    failures = 0
    assembly = None
    try:
        bus = EvidenceBus(writer, run_id)
        llm_http, llm = _build_llm(settings, bus)
        jev_http, jev = _build_jev(settings, bus)
        with ThreadPoolExecutor(max_workers=settings.execution.concurrency) as pool:
            if not writer.call(lambda store: work.stage_complete(store, run_id, "index")):
                writer.call(lambda store: ingest_catalogs(
                    store, run_id, [Path(p) for p in catalog_paths], output,
                    catalog_format=settings.execution.catalog_format,
                    clock=clock, id_factory=id_factory,
                ))
            index_ok = run_index_llm(writer, run_id, settings=settings, pool=pool, llm=llm)
            if index_ok:
                failures += run_retrieve(
                    writer, run_id, settings=settings, pool=pool, llm=llm
                )
                if estimate is not None:
                    estimate("candidates", writer.call(
                        lambda store: store.counts(run_id)
                    )["candidate_pairs"])
                failures += run_verify(writer, run_id, settings=settings, pool=pool, jev=jev)
                failures += run_classify(writer, run_id, settings=settings, pool=pool, jev=jev)
            else:
                # Mirror run_pipeline: an incomplete domain index must not terminalise
                # retrieval or emit a misleading "mapped" run.
                failures += 1
        if index_ok:
            # Set the terminal status before assembling so rationale.run.status is current.
            writer.call(lambda store: store.set_run_status(run_id, "mapped", finished=True))
            assembly = _assemble_out(
                writer, run_id, Path(output), settings=settings, clock=clock,
                id_factory=id_factory, config=config, partial=False,
            )
        else:
            writer.call(lambda store: store.set_run_status(run_id, "index_incomplete"))
        counts = writer.call(lambda store: store.counts(run_id))
    finally:
        if llm_http is not None:
            llm_http.close()
        if jev_http is not None:
            jev_http.close()
        writer.stop()
    unmapped = len(assembly.unmapped_requirements) if assembly is not None else 0
    return RunResult(
        run_id, row["fingerprint"], row["config_hash"], counts["documents"],
        counts["requirements"], counts["candidate_pairs"],
        output=Path(output) if assembly is not None else None,
        gaps=failures + unmapped, unmapped_count=unmapped, failure_count=failures,
    )


def resume_run(
    *,
    state_dir: Path,
    output: Path,
    settings: Settings,
    clock: Clock,
    id_factory: IdFactory,
    run_id: str,
    estimate: Optional[Callable[[str, int], None]] = None,
) -> RunResult:
    with RunStore.open(state_dir, clock=clock, id_factory=id_factory) as store:
        if store.get_run(run_id) is None:
            raise UsageError(f"run '{run_id}' does not exist")
        input_paths = [Path(row["path"]) for row in store.list_documents(run_id)]
        catalog_paths = [Path(row["path"]) for row in store.list_catalogs(run_id)]
    if not input_paths:
        raise UsageError(f"run '{run_id}' has no recorded input documents to resume")
    return run_pipeline(
        state_dir=state_dir, output=output, input_paths=input_paths,
        catalog_paths=catalog_paths, settings=settings, clock=clock,
        id_factory=id_factory, run_id=run_id, estimate=estimate,
    )
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `nix develop -c pytest tests/integration/test_orchestrator.py tests/integration/test_phase4_output.py -v`
Expected: all green, including the four new orchestrator tests and the three `test_phase4_output.py` bodies. Phase 4 new tests: **7** (running total **48**).

- [ ] **Step 5: Commit**

```bash
git add src/smeargle/pipeline/run.py src/smeargle/pipeline/retrieve.py tests/integration/test_orchestrator.py tests/integration/test_phase4_output.py
git commit -m "feat(pipeline): assemble outputs and add extract map resume orchestrators" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 12: CLI `run`, `extract`, `map`, `resume` end-to-end

**Files:**
- Modify: `src/smeargle/cli.py`
- Create: `tests/unit/test_cli_phase4.py`

**Spec traceability:** §12 (subcommands and options; `run` full pipeline; `extract` Stages 0–1 + partial assemble; `map` Stages 2–6 from an existing run; `resume`), §12.1 (fingerprint/config-hash resume prompt, `--run-id`, `--force`, `--yes`, pre-flight estimate), §12.2 (exit codes 0–8), §15 (exit 6).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_cli_phase4.py`:

```python
import json

import httpx
import respx

from smeargle.cli import main


def _fixtures(tmp_path):
    document = tmp_path / "spec.txt"
    document.write_text("The system MUST encrypt data at rest.", encoding="utf-8")
    catalog = tmp_path / "vendor.json"
    catalog.write_text(
        json.dumps({"catalog": {"name": "V", "securityControls": [
            {"controlId": "1.1", "title": "Policy", "family": "Access"}]}}),
        encoding="utf-8",
    )
    return document, catalog


def _chat(content):
    return {"choices": [{"message": {"content": json.dumps(content)}}]}


def _answers(answer, confidence):
    return {"answers": [{"question": "q", "answer": answer, "answer_confidence": confidence}]}


def _mock():
    def llm(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        if "extract normative requirements" in prompt:
            return httpx.Response(200, json=_chat({"requirements": [
                {"text": "The system MUST encrypt data at rest.", "keyword": "MUST"}]}))
        if "classify security controls" in prompt:
            return httpx.Response(200, json=_chat({"labels": [
                {"control_id": "c-1.1", "domain": "access", "family": "Access"}]}))
        if "control domains" in prompt:
            return httpx.Response(200, json=_chat({"domains": ["access"]}))
        return httpx.Response(200, json=_chat({"control_ids": ["c-1.1"]}))

    respx.post("https://llm.example/v1/chat/completions").mock(side_effect=llm)
    respx.post("https://jev.example/v1/systemone").mock(side_effect=[
        httpx.Response(200, json=_answers("yes", 0.9)),
        httpx.Response(200, json=_answers("MUST", 0.9)),
        httpx.Response(200, json=_answers("yes", 0.9)),
        httpx.Response(200, json=_answers("subset-of", 0.85)),
    ])


def _common(tmp_path):
    return [
        "--state-dir", str(tmp_path / "s"), "--output", str(tmp_path / "o"), "--yes",
        "--llm-endpoint", "https://llm.example", "--jev-endpoint", "https://jev.example",
    ]


@respx.mock
def test_run_emits_artifacts_and_prints_estimates(tmp_path, capsys):
    _mock()
    document, catalog = _fixtures(tmp_path)
    code = main(_common(tmp_path) + ["run", "-i", str(document), "-c", str(catalog)])
    out = capsys.readouterr().out
    assert code == 0
    assert "requirement(s)" in out
    assert (tmp_path / "o" / "profile.json").exists()


@respx.mock
def test_extract_then_map_completes_the_run(tmp_path):
    _mock()
    document, catalog = _fixtures(tmp_path)
    base = _common(tmp_path) + ["--run-id", "run-x"]
    assert main(base + ["extract", "-i", str(document)]) == 0
    assert (tmp_path / "o" / "requirements-catalog.json").exists()
    assert not (tmp_path / "o" / "profile.json").exists()
    assert main(base + ["map", "-c", str(catalog)]) == 0
    assert (tmp_path / "o" / "profile.json").exists()


@respx.mock
def test_resume_after_a_completed_run_is_a_no_op(tmp_path):
    _mock()
    document, catalog = _fixtures(tmp_path)
    base = _common(tmp_path) + ["--run-id", "run-r"]
    assert main(base + ["run", "-i", str(document), "-c", str(catalog)]) == 0
    assert main(base + ["resume"]) == 0


@respx.mock
def test_run_exits_six_when_a_requirement_is_unmapped(tmp_path):
    def llm(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        if "extract normative requirements" in prompt:
            return httpx.Response(200, json=_chat({"requirements": [
                {"text": "The system MUST encrypt data at rest.", "keyword": "MUST"}]}))
        if "classify security controls" in prompt:
            return httpx.Response(200, json=_chat({"labels": []}))
        if "control domains" in prompt:
            return httpx.Response(200, json=_chat({"domains": []}))
        return httpx.Response(200, json=_chat({"control_ids": []}))

    respx.post("https://llm.example/v1/chat/completions").mock(side_effect=llm)
    respx.post("https://jev.example/v1/systemone").mock(
        side_effect=[httpx.Response(200, json=_answers("yes", 0.9)),
                     httpx.Response(200, json=_answers("MUST", 0.9))]
    )
    document, catalog = _fixtures(tmp_path)
    code = main(_common(tmp_path) + ["run", "-i", str(document), "-c", str(catalog)])
    assert code == 6


def test_force_and_run_id_are_accepted_options(tmp_path, capsys):
    document, catalog = _fixtures(tmp_path)
    code = main([
        "--state-dir", str(tmp_path / "s"), "--output", str(tmp_path / "o"), "--yes",
        "--run-id", "run-z", "--force",
        "run", "-i", str(document), "-c", str(catalog),
    ])
    assert code == 2
    assert "--llm-endpoint" in capsys.readouterr().err


@respx.mock
def test_map_without_a_run_selector_is_a_usage_error(tmp_path, capsys):
    _mock()
    _document, catalog = _fixtures(tmp_path)
    code = main(_common(tmp_path) + ["map", "-c", str(catalog)])
    assert code == 2
    assert "run" in capsys.readouterr().err.lower()


@respx.mock
def test_resume_without_a_run_selector_is_a_usage_error(tmp_path, capsys):
    _mock()
    assert main(_common(tmp_path) + ["resume"]) == 2
    assert "run" in capsys.readouterr().err.lower()


def test_integrity_failure_exits_seven(tmp_path, monkeypatch):
    # CLI exit-code mapping only: the pipeline is stubbed, so no assembly or IO happens.
    # The real gate-before-write invariant is covered by Task 10's
    # `test_run_assemble_checks_integrity_before_writing_any_assemble_artifact`.
    from smeargle.errors import IntegrityError
    from smeargle.pipeline import run as run_pipeline

    def boom(*_args, **_kwargs):
        raise IntegrityError("broken output")

    monkeypatch.setattr(run_pipeline, "run_pipeline", boom)
    document, catalog = _fixtures(tmp_path)
    code = main(_common(tmp_path) + ["run", "-i", str(document), "-c", str(catalog)])
    assert code == 7
    # The stubbed pipeline writes nothing, so the required output directory is never created.
    assert not (tmp_path / "o").exists()
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `nix develop -c pytest tests/unit/test_cli_phase4.py -v`
Expected: the seven `run`/`extract`/`map`/`resume` tests fail (`run` still only ingests; `extract`/`map`/`resume` still return `not implemented`). `test_integrity_failure_exits_seven` passes immediately: the `SmeargleError` → exit-code mapping is Phase 1 behaviour, so this task adds the regression coverage the completion checklist requires.

- [ ] **Step 3: Write the implementation**

In `src/smeargle/cli.py`, extend the existing imports rather than appending duplicate lines (ruff `I001`/`F811`): add `import sys` to the stdlib block, and add `AbortedError`/`GapsError` to the existing `from smeargle.errors import (...)` block (it already imports `UsageError`, so do not import it twice). The merged block becomes:

```python
import sys
from pathlib import Path
from typing import Optional

import typer

from smeargle import __version__
from smeargle.config import Settings
from smeargle.errors import (
    EXIT_ABORTED,
    EXIT_SUCCESS,
    EXIT_UNEXPECTED,
    AbortedError,
    GapsError,
    SmeargleError,
    UsageError,
    exit_code_for,
)
from smeargle.observability import configure_logging
```

Replace the `run`, `extract`, `map`, and `resume` command bodies with:

```python
def _estimate_printer():
    def printer(kind: str, count: int) -> None:
        if kind == "requirements":
            typer.echo(f"extracted {count} requirement(s)")
        else:
            typer.echo(f"pre-flight estimate: {count} candidate pair(s) to verify")

    return printer


def _select_run_id(settings: Settings, fingerprint: str, config_hash: str) -> Optional[str]:
    if settings.execution.force:
        return None
    with RunStore.open(settings.state_dir) as store:
        matches = store.find_runs_by_fingerprint(fingerprint)
    if not matches:
        return None
    latest = matches[0]
    if settings.execution.run_id:
        return settings.execution.run_id
    if latest["config_hash"] != config_hash:
        typer.echo("warning: resuming across a different config_hash")
    if settings.execution.yes or not sys.stdin.isatty():
        return latest["run_id"]
    choice = typer.prompt("resume / new / cancel", default="resume")
    if choice == "new":
        return None
    if choice == "cancel":
        raise AbortedError("cancelled")
    return latest["run_id"]


def _finish(result: "RunPipelineResult") -> None:
    if result is None:
        return
    typer.echo(
        f"run {result.run_id}: {result.requirement_count} requirement(s),"
        f" {result.candidate_count} candidate pair(s)"
    )
    if result.gaps:
        raise GapsError(f"completed with {result.gaps} gap(s)")


@app.command()
def run(
    ctx: typer.Context,
    input: Optional[List[Path]] = typer.Option(None, "-i", "--input", help="Input document."),
    catalog: Optional[List[Path]] = typer.Option(None, "-c", "--catalog", help="Catalog."),
) -> None:
    """Run the full pipeline (Stages 0-6)."""
    settings = _resolve_settings(ctx)
    input_paths = [Path(p) for p in input] if input else [Path(p) for p in settings.inputs]
    catalog_paths = (
        [Path(p) for p in catalog] if catalog else [Path(p) for p in settings.catalogs]
    )
    if not input_paths:
        raise UsageError("run requires at least one --input")
    if not catalog_paths:
        raise UsageError("run requires at least one --catalog")
    if settings.output is None:
        raise UsageError("run requires --output")
    if not settings.llm.endpoint:
        raise UsageError("run requires --llm-endpoint")
    if not settings.jev.endpoint:
        raise UsageError("run requires --jev-endpoint")

    _configure_oscal(settings)
    fingerprint = run_pipeline.compute_fingerprint(input_paths, catalog_paths)
    config = run_pipeline.redact(run_pipeline._phase3_config_snapshot(settings))
    selected = settings.execution.run_id or _select_run_id(
        settings, fingerprint, run_pipeline.config_hash(config)
    )
    result = run_pipeline.run_pipeline(
        state_dir=settings.state_dir, output=settings.output, input_paths=input_paths,
        catalog_paths=catalog_paths, settings=settings, clock=SystemClock(),
        id_factory=UuidIdFactory(), run_id=selected, estimate=_estimate_printer(),
    )
    _finish(result)


@app.command()
def extract(
    ctx: typer.Context,
    input: Optional[List[Path]] = typer.Option(None, "-i", "--input", help="Input document."),
) -> None:
    """Extract requirements only (Stages 0-1) and emit the partial output."""
    settings = _resolve_settings(ctx)
    input_paths = [Path(p) for p in input] if input else [Path(p) for p in settings.inputs]
    if not input_paths:
        raise UsageError("extract requires at least one --input")
    if settings.output is None:
        raise UsageError("extract requires --output")
    if not settings.llm.endpoint:
        raise UsageError("extract requires --llm-endpoint")
    if not settings.jev.endpoint:
        raise UsageError("extract requires --jev-endpoint")
    _configure_oscal(settings)
    result = run_pipeline.run_extract_only(
        state_dir=settings.state_dir, output=settings.output, input_paths=input_paths,
        settings=settings, clock=SystemClock(), id_factory=UuidIdFactory(),
        run_id=settings.execution.run_id, estimate=_estimate_printer(),
    )
    _finish(result)


@app.command()
def map(
    ctx: typer.Context,
    catalog: Optional[List[Path]] = typer.Option(None, "-c", "--catalog", help="Catalog."),
) -> None:
    """Map an existing run's requirements to catalogs (Stages 2-6)."""
    settings = _resolve_settings(ctx)
    catalog_paths = (
        [Path(p) for p in catalog] if catalog else [Path(p) for p in settings.catalogs]
    )
    if not settings.execution.run_id:
        raise UsageError("map requires --run-id")
    if not catalog_paths:
        raise UsageError("map requires at least one --catalog")
    if settings.output is None:
        raise UsageError("map requires --output")
    if not settings.llm.endpoint:
        raise UsageError("map requires --llm-endpoint")
    if not settings.jev.endpoint:
        raise UsageError("map requires --jev-endpoint")
    _configure_oscal(settings)
    result = run_pipeline.run_map(
        state_dir=settings.state_dir, output=settings.output, catalog_paths=catalog_paths,
        settings=settings, clock=SystemClock(), id_factory=UuidIdFactory(),
        run_id=settings.execution.run_id, estimate=_estimate_printer(),
    )
    _finish(result)


@app.command()
def resume(ctx: typer.Context) -> None:
    """Continue an interrupted run."""
    settings = _resolve_settings(ctx)
    if not settings.execution.run_id:
        raise UsageError("resume requires --run-id")
    if settings.output is None:
        raise UsageError("resume requires --output")
    if not settings.llm.endpoint:
        raise UsageError("resume requires --llm-endpoint")
    if not settings.jev.endpoint:
        raise UsageError("resume requires --jev-endpoint")
    _configure_oscal(settings)
    result = run_pipeline.resume_run(
        state_dir=settings.state_dir, output=settings.output, settings=settings,
        clock=SystemClock(), id_factory=UuidIdFactory(),
        run_id=settings.execution.run_id, estimate=_estimate_printer(),
    )
    _finish(result)
```

Add the `RunPipelineResult` alias near the imports (it is only for the type annotation):

```python
from smeargle.pipeline.run import RunResult as RunPipelineResult  # noqa: F401
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `nix develop -c pytest tests/unit/test_cli_phase4.py -v`
Expected: `8 passed`. Phase 4 new tests: **8** (running total **56**).

- [ ] **Step 5: Run ruff and commit**

Run: `nix develop -c ruff check src/smeargle`
Expected: `All checks passed!`

```bash
git add src/smeargle/cli.py tests/unit/test_cli_phase4.py
git commit -m "feat(cli): implement run extract map resume end to end" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 13: CLI `validate` and `status` completion

**Files:**
- Modify: `src/smeargle/cli.py`
- Test: `tests/unit/test_cli_phase4.py` (append)

**Spec traceability:** §12 (`validate` validates input catalogs and/or emitted artifacts; `status` shows per-stage progress and output presence), §12.2 (exit codes). No `tests/unit/test_cli.py` change is needed: the Phase 3 `run`/`status` tests there already cover the shared globals, and this task's new behaviour lives in `test_cli_phase4.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cli_phase4.py`:

```python
@respx.mock
def test_validate_accepts_every_emitted_artifact(tmp_path, capsys):
    _mock()
    document, catalog = _fixtures(tmp_path)
    assert main(_common(tmp_path) + ["run", "-i", str(document), "-c", str(catalog)]) == 0
    capsys.readouterr()
    code = main([
        "--state-dir", str(tmp_path / "s"), "--output", str(tmp_path / "o"), "validate",
    ])
    out = capsys.readouterr().out
    assert code == 0
    assert "requirements-catalog.json" in out
    assert "profile.json" in out
    assert "rationale.json" in out


@respx.mock
def test_validate_rejects_a_corrupt_artifact(tmp_path, capsys):
    _mock()
    document, catalog = _fixtures(tmp_path)
    assert main(_common(tmp_path) + ["run", "-i", str(document), "-c", str(catalog)]) == 0
    target = tmp_path / "o" / "profile.json"
    target.write_text('{"profile": {"uuid": "nope"}}', encoding="utf-8")
    code = main([
        "--state-dir", str(tmp_path / "s"), "--output", str(tmp_path / "o"), "validate",
    ])
    assert code == 4


@respx.mock
def test_status_reports_artifacts_and_stages(tmp_path, capsys):
    _mock()
    document, catalog = _fixtures(tmp_path)
    assert main(_common(tmp_path) + ["run", "-i", str(document), "-c", str(catalog)]) == 0
    capsys.readouterr()
    code = main(["--state-dir", str(tmp_path / "s"), "--output", str(tmp_path / "o"), "status"])
    out = capsys.readouterr().out
    assert code == 0
    assert "classify" in out
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `nix develop -c pytest tests/unit/test_cli_phase4.py -k "validate or status" -v`
Expected: `validate` does not read `rationale.json` and `status` prints no artifact summary.

- [ ] **Step 3: Write the implementation**

Replace the `validate` and `status` command bodies in `src/smeargle/cli.py`:

```python
@app.command()
def validate(
    ctx: typer.Context,
    catalog: Optional[List[Path]] = typer.Option(None, "-c", "--catalog", help="Catalog."),
) -> None:
    """Validate input catalogs and/or emitted artifacts."""
    settings = _resolve_settings(ctx)
    _configure_oscal(settings)
    targets = (
        [Path(p) for p in catalog] if catalog else [Path(p) for p in settings.catalogs]
    )
    for path in targets:
        parse_catalog(path, settings.execution.catalog_format)
        typer.echo(f"{path}: valid")
    if settings.output is None:
        return
    for name, model in (("requirements-catalog.json", "catalog"),
                        ("profile.json", "profile"),
                        ("mapping-collection.json", "mapping-collection")):
        path = settings.output / name
        if path.exists():
            facade.validate(model, facade.load_document(path))
            typer.echo(f"{path}: valid")
    rationale = settings.output / "rationale.json"
    if rationale.exists():
        json.loads(rationale.read_text(encoding="utf-8"))
        typer.echo(f"{rationale}: valid")
    catalogs_dir = settings.output / "catalogs"
    if catalogs_dir.is_dir():
        for path in sorted(catalogs_dir.glob("*.json")):
            facade.validate("catalog", facade.load_document(path))
            typer.echo(f"{path}: valid")


@app.command()
def status(ctx: typer.Context) -> None:
    """Show per-stage progress, counts, and emitted artifacts."""
    settings = _resolve_settings(ctx)
    if not (settings.state_dir / DB_FILENAME).exists():
        typer.echo("no runs recorded")
        return
    with RunStore.open(settings.state_dir) as store:
        runs = store.list_runs()
        if not runs:
            typer.echo("no runs recorded")
            return
        for row in runs:
            counts = store.counts(row["run_id"])
            summary = " ".join(f"{name}={value}" for name, value in counts.items())
            typer.echo(f"{row['run_id']} {row['status']} {summary}")
            for stage in ("load", "extract", "index", "retrieve", "verify", "classify"):
                stage_row = store.get_stage(row["run_id"], stage)
                if stage_row is not None:
                    typer.echo(f"  {stage}: {stage_row['status']}")
    if settings.output is not None:
        for name in ("requirements-catalog.json", "profile.json",
                     "mapping-collection.json", "rationale.json"):
            if (settings.output / name).exists():
                typer.echo(f"  artifact: {name}")
```

Add `import json` to the `cli.py` imports.

- [ ] **Step 4: Run the tests and see them pass**

Run: `nix develop -c pytest tests/unit/test_cli_phase4.py -v`
Expected: `11 passed` (8 from Task 12 + 3 new). Phase 4 new tests: **3** (running total **59**).

- [ ] **Step 5: Commit**

```bash
git add src/smeargle/cli.py tests/unit/test_cli_phase4.py
git commit -m "feat(cli): complete validate and status for emitted artifacts" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 14: Nomination cap and JEV batching end-to-end

**Files:**
- Test: `tests/unit/pipeline/test_retrieve.py` (append)
- Test: `tests/integration/test_orchestrator.py` (append)

**Spec traceability:** §6/§10 (`nomination_cap` 0 = disabled; retained as a safety valve), §8.2/§12 (`--jev-batch`/`--jev-batch-size`, `systemone_batch` with `states[]` ≤ 64), §12 (the optional surface is wired end-to-end).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/pipeline/test_retrieve.py`:

```python
def test_nomination_cap_truncates_deterministically():
    from fakes.clients import FakeLLMClient

    from smeargle.domain.controls import Control
    from smeargle.pipeline import retrieve

    controls = [
        Control("run-1", "c1", "ac-1", "t", "x", "", ""),
        Control("run-1", "c1", "ac-2", "t", "x", "", ""),
        Control("run-1", "c1", "ac-3", "t", "x", "", ""),
    ]
    llm = FakeLLMClient(responses=[
        {"control_ids": ["ac-3", "ac-1", "ac-2"]},
        {"control_ids": ["ac-3", "ac-1", "ac-2"]},
    ])
    assert retrieve.nominate_controls(llm, "MUST x", controls, cap=2) == ["ac-3", "ac-1"]
    assert retrieve.nominate_controls(llm, "MUST x", controls, cap=0) == [
        "ac-3", "ac-1", "ac-2"
    ]
```

Append to `tests/integration/test_orchestrator.py`:

```python
@respx.mock
def test_jev_batching_issues_one_batch_call_for_verification_and_classification(tmp_path):
    settings = _settings(tmp_path)
    settings.jev.batch = True
    settings.jev.batch_size = 64
    document, catalog = _fixtures(tmp_path)

    def chat_router(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        if "extract normative requirements" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"requirements": [
                {"text": "The system MUST encrypt data at rest.", "keyword": "MUST"}]})))
        if "classify security controls" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"labels": [
                {"control_id": "c-1.1", "domain": "access", "family": "Access"}]})))
        if "control domains" in prompt:
            return httpx.Response(200, json=_chat(json.dumps({"domains": ["access"]})))
        return httpx.Response(200, json=_chat(json.dumps({"control_ids": ["c-1.1"]})))

    respx.post("https://llm.example/v1/chat/completions").mock(side_effect=chat_router)
    batch = respx.post("https://jev.example/v1/systemone/batch").mock(
        side_effect=[
            httpx.Response(200, json={"results": [[
                {"question": "q", "answer": "yes", "answer_confidence": 0.9}]]}),
            httpx.Response(200, json={"results": [[
                {"question": "q", "answer": "subset-of", "answer_confidence": 0.85}]]}),
        ]
    )
    respx.post("https://jev.example/v1/systemone").mock(
        side_effect=[
            httpx.Response(200, json=_answers(("yes", 0.9))),
            httpx.Response(200, json=_answers(("MUST", 0.9))),
        ]
    )
    run_pipeline.run_pipeline(
        state_dir=settings.state_dir, output=settings.output,
        input_paths=[document], catalog_paths=[catalog], settings=settings,
        clock=FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc)),
        id_factory=UuidIdFactory(), run_id="run-batch",
    )
    assert batch.call_count == 2
    assert b'"states"' in batch.calls[0].request.content
```

- [ ] **Step 2: Run the two new tests and confirm they pass**

Run: `nix develop -c pytest tests/unit/pipeline/test_retrieve.py::test_nomination_cap_truncates_deterministically "tests/integration/test_orchestrator.py::test_jev_batching_issues_one_batch_call_for_verification_and_classification" -v`
Expected: `2 passed`. These are verification tests, not red-first tests: the `cap` parameter is already threaded by Task 11 and the `settings.jev.batch` branches were added by Phase 3, so there is no pre-change failure to observe here. A failure indicates a regression in that wiring.

- [ ] **Step 3: Implementation**

No new implementation: `retrieve.nominate_controls(..., cap=...)`, `retrieve.retrieve_requirement(..., cap=...)`, and the `settings.jev.batch` branches in `run_verify`/`run_classify` were added in Task 11 and Phase 3 respectively. This task is the end-to-end verification the spec requires. If the batching test fails, fix `run_verify`/`run_classify` so the batch branches are taken (they are already guarded by `if settings.jev.batch and items:`); do not add a second batching path.

- [ ] **Step 4: Run the full suites and confirm green**

Run: `nix develop -c pytest tests/unit/pipeline/test_retrieve.py tests/integration/test_orchestrator.py -v`
Expected: all green, including the two new tests. Phase 4 new tests: **2** (running total **61**).

- [ ] **Step 5: Commit**

```bash
git add tests/unit/pipeline/test_retrieve.py tests/integration/test_orchestrator.py
git commit -m "test(pipeline): verify nomination cap and jev batching end to end" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 15: Artifact schema validation, adversarial cases, and byte-identical determinism

**Files:**
- Create: `tests/support/artifacts.py`
- Test: `tests/integration/test_artifact_validation.py`

**Spec traceability:** §11.6 (every artifact validated against the bundled metaschema **and** the vendored official OSCAL 1.2.3 JSON Schemas; a globally zero-relation run omits `mapping-collection.json` and that absence is accepted), §11.7 (re-assembling the same stored ledger yields byte-identical artifacts), §14 (adversarial fakes must be rejected, not coerced).

- [ ] **Step 1: Write the failing tests**

Create `tests/support/artifacts.py`:

```python
"""Write-and-validate helpers for emitted artifacts (spec 11.6)."""

from __future__ import annotations

import json
from pathlib import Path

from support.schemas import validate_against_schema

from smeargle.oscal_build import facade

MODELS = {
    "requirements-catalog.json": "catalog",
    "profile.json": "profile",
    "mapping-collection.json": "mapping-collection",
}


def validate_output(output: Path) -> list[str]:
    names: list[str] = []
    for name, model in MODELS.items():
        path = Path(output) / name
        if not path.exists():
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        facade.validate(model, document)
        validate_against_schema(model, document)
        names.append(name)
    rationale = Path(output) / "rationale.json"
    if rationale.exists():
        json.loads(rationale.read_text(encoding="utf-8"))
        names.append("rationale.json")
    return names
```

Create `tests/integration/test_artifact_validation.py`:

```python
import jsonschema_rs
import pytest

from support.artifacts import validate_output
from support.ledger import CLOCK, IDS, ledger, mapping_row, requirement
from support.schemas import validate_against_schema

from smeargle.oscal_build import emit, facade


@pytest.fixture(autouse=True)
def _support(tmp_path):
    facade.configure_support_file(tmp_path / "support.db")


def test_every_artifact_validates_against_metaschema_and_vendored_schema(tmp_path):
    assembly = emit.assemble(ledger(), clock=CLOCK, id_factory=IDS)
    emit.write_assembly(assembly, tmp_path)
    assert sorted(validate_output(tmp_path)) == [
        "mapping-collection.json", "profile.json", "rationale.json",
        "requirements-catalog.json",
    ]


def test_zero_relation_run_omits_mapping_collection_and_still_validates(tmp_path):
    source = ledger(mappings=(), pairs=(), requirements=(requirement(retrieve="none"),))
    assembly = emit.assemble(source, clock=CLOCK, id_factory=IDS)
    emit.write_assembly(assembly, tmp_path)
    names = validate_output(tmp_path)
    assert "mapping-collection.json" not in names
    assert "requirements-catalog.json" in names


def test_adversarial_documents_are_rejected_not_coerced():
    bad_mapping = {
        "mapping-collection": {
            "uuid": "not-a-uuid", "metadata": {}, "provenance": {}, "mappings": [],
        }
    }
    with pytest.raises(jsonschema_rs.ValidationError):
        validate_against_schema("mapping-collection", bad_mapping)
    with pytest.raises(Exception):
        emit.assemble(
            ledger(mappings=(mapping_row(relation="definitely-related"),)),
            clock=CLOCK, id_factory=IDS,
        )


def test_reassembling_the_same_ledger_is_byte_identical(tmp_path):
    source = ledger()
    first = emit.write_assembly(emit.assemble(source, clock=CLOCK, id_factory=IDS),
                                tmp_path / "a")
    second = emit.write_assembly(emit.assemble(source, clock=CLOCK, id_factory=IDS),
                                 tmp_path / "b")
    for left, right in zip(sorted(first, key=lambda p: p.name),
                           sorted(second, key=lambda p: p.name)):
        assert left.read_bytes() == right.read_bytes()
```

- [ ] **Step 2: Run the tests and confirm they are green**

Run: `nix develop -c pytest tests/integration/test_artifact_validation.py -v`
Expected: `4 passed`. These are validation/acceptance tests over the assembler delivered in Tasks 2, 8, 9, and 10; there is no production change in this task, so a failure indicates a regression or a missing dependency, not a missing module. (`facade.validate` is imported directly from `smeargle.oscal_build.facade`; the test does not reach through `emit.facade`, though that name does resolve.)

- [ ] **Step 3: Implementation**

No production code change; Task 9's `emit.assemble`/`write_assembly` and the Phase 2 `tests/support/schemas.py` provide the behaviour under test.

- [ ] **Step 4: Run the tests and see them pass**

Run: `nix develop -c pytest tests/integration/test_artifact_validation.py -v`
Expected: `4 passed`. Phase 4 new tests: **4** (running total **65**).

- [ ] **Step 5: Commit**

```bash
git add tests/support/artifacts.py tests/integration/test_artifact_validation.py
git commit -m "test(oscal): validate every artifact and prove byte determinism" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 16: Spec-driven suitability for run (Phase 4 acceptance)

**Files:**
- Create: `tests/e2e/test_phase4_run.py`

**Spec traceability:** §14 (an in-thread real HTTP fake per service exercised through the subprocess CLI; every artifact validated), §11 (full output layout), §11.6/§11.7 (integrity gate and determinism), §12.1/§12.2 (exit codes 0 and 6).

- [ ] **Step 1: Write the acceptance tests**

Create `tests/e2e/test_phase4_run.py`:

```python
import json
import os
import subprocess
from pathlib import Path

import pytest

from fakes.servers import FakeHttpService, jev_responder, llm_responder
from support.artifacts import validate_output

from smeargle.oscal_build import facade


def _binary() -> str:
    path = Path("result/bin/smeargle")
    if not path.exists():
        pytest.skip("run `nix build .#smeargle` first so result/bin/smeargle exists")
    return str(path)


def _fixtures(tmp_path):
    document = tmp_path / "spec.txt"
    document.write_text("The system MUST encrypt data at rest.", encoding="utf-8")
    catalog = tmp_path / "vendor.json"
    catalog.write_text(
        json.dumps({"catalog": {"name": "V", "securityControls": [
            {"controlId": "1.1", "title": "Policy", "family": "Access"}]}}),
        encoding="utf-8",
    )
    return document, catalog


def _invoke(tmp_path, document, catalog, llm, jev, run_id):
    return subprocess.run(
        [
            _binary(), "--state-dir", str(tmp_path / "state"),
            "--output", str(tmp_path / "out"), "--yes", "--run-id", run_id,
            "--llm-endpoint", llm.url, "--jev-endpoint", jev.url,
            "run", "-i", str(document), "-c", str(catalog),
        ],
        capture_output=True, text=True, env=os.environ.copy(), timeout=120,
    )


def test_installed_binary_emits_and_validates_full_output_tree(tmp_path):
    facade.configure_support_file(tmp_path / "support.db")
    document, catalog = _fixtures(tmp_path)
    with FakeHttpService(llm_responder) as llm, FakeHttpService(jev_responder) as jev:
        result = _invoke(tmp_path, document, catalog, llm, jev, "run-e2e")
    assert result.returncode == 0, result.stderr
    output = tmp_path / "out"
    assert sorted(path.name for path in output.iterdir() if path.is_file()) == [
        "mapping-collection.json", "profile.json", "rationale.json",
        "requirements-catalog.json",
    ]
    assert list((output / "catalogs").glob("*.json"))
    assert list((output / "evidence").glob("*.json"))
    assert sorted(validate_output(output)) == [
        "mapping-collection.json", "profile.json", "rationale.json",
        "requirements-catalog.json",
    ]


def test_installed_binary_zero_relation_run_omits_mapping_collection(tmp_path):
    facade.configure_support_file(tmp_path / "support.db")

    def empty_llm(path, body):
        prompt = body["messages"][0]["content"]
        if "extract normative requirements" in prompt:
            content = {"requirements": [
                {"text": "The system MUST encrypt data at rest.", "keyword": "MUST"}]}
        elif "classify security controls" in prompt:
            content = {"labels": []}  # IndexResponseModel
        elif "control domains" in prompt:
            content = {"domains": []}  # DomainSelectionModel
        else:
            content = {"control_ids": []}  # NominationResponseModel
        return {"choices": [{"message": {"content": json.dumps(content)}}]}

    def empty_jev(path, body):
        question = body["questions"][0]
        answer = "yes" if question["kind"] == "noul" else "MUST"
        return {"answers": [{"question": "q", "answer": answer, "answer_confidence": 0.9}]}

    document, catalog = _fixtures(tmp_path)
    with FakeHttpService(empty_llm) as llm, FakeHttpService(empty_jev) as jev:
        result = _invoke(tmp_path, document, catalog, llm, jev, "run-gap")
    assert result.returncode == 6, result.stderr
    assert not (tmp_path / "out" / "mapping-collection.json").exists()
    assert (tmp_path / "out" / "requirements-catalog.json").exists()
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `nix build .#smeargle`
Expected: `result/bin/smeargle` exists. Then:

Run: `nix develop -c pytest tests/e2e/test_phase4_run.py -v`
Expected: `2 passed`. The `from support.artifacts import validate_output` import matches the Phase 2 `pythonpath += tests` convention; `_invoke` passes every global option (`--state-dir`, `--output`, `--yes`, `--run-id`, `--llm-endpoint`, `--jev-endpoint`) before the `run` subcommand.

- [ ] **Step 3: Implementation**

No production change: Tasks 9–13 supply the assembler and CLI. If `test_installed_binary_zero_relation_run_omits_mapping_collection` does not exit 6, verify the CLI's `_finish` raises `GapsError` whenever `result.gaps > 0` (Task 12) and that `run.py` counts unmapped requirements (Task 11). Do not weaken the test.

- [ ] **Step 4: Run the acceptance suite, lint, types, and build**

Run:

```bash
nix develop -c pytest -q
nix develop -c ruff check src tests
nix develop -c mypy src
nix build .#smeargle
./result/bin/smeargle --version
```

Expected: the full Phase 1 + 2 + 3 + 4 suite passes; ruff `All checks passed!`; mypy `Success: no issues found`; `nix build` succeeds using only the pinned `nixpkgs` + `flake-utils` inputs; the binary prints `smeargle <version>`. Phase 4 new tests: **2** (running total **67**).

- [ ] **Step 5: Commit**

```bash
git add tests/e2e/test_phase4_run.py
git commit -m "test(e2e): accept phase 4 output tree via the built binary" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Phase 4 completion checklist

- [ ] All 16 tasks committed with atomic, lowercase Conventional Commits and the `Assisted-by: DeepSeek Flash via OpenCode` trailer.
- [ ] `nix develop -c pytest -q` green; Phase 4 adds the tests counted in the ledger.
- [ ] `nix develop -c ruff check src tests` and `nix develop -c mypy src` clean.
- [ ] `nix build .#smeargle` succeeds with only the pinned `nixpkgs` + `flake-utils` inputs.
- [ ] `./result/bin/smeargle run/extract/map/resume/validate/status` all execute end-to-end.
- [ ] The full §11 output layout is produced under `--output`, with `mapping-collection.json` omitted exactly on a globally zero-relation run.
- [ ] The §11.6 gate is a hard failure and §11.7 byte determinism is proven on a fixed ledger; the CLI exercises the gate failure as exit code 7 (`test_integrity_failure_exits_seven`).
- [ ] Exit codes 0–8 are centralised in `errors.py`; the CLI tests exercise at least 0 (`run`), 2 (usage/config), 4 (invalid artifact), 6 (completed with gaps), and 7 (integrity gate).






