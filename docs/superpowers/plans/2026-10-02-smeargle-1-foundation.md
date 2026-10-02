# smeargle Phase 1 (Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a runnable, buildable `smeargle` skeleton — a typed domain core, layered configuration, a Typer CLI with centralised exit codes, observability/redaction, and a Nix flake that builds the CLI and runs the test suite — with no external HTTP calls yet.

**Architecture:** A `src/`-layout Python package with a pure, dependency-free `domain/` layer (frozen stdlib dataclasses, deterministic IDs, injectable clock), a Pydantic-Settings `config.py`, a `cli.py` that resolves config and maps typed errors to spec exit codes, and a hand-written Nix flake that adds **no new inputs** and uses the repository's two already-pinned inputs (`nixpkgs` and `flake-utils`) with `flake-utils.lib.eachSystem`. Everything is developed test-first with `pytest`; the Nix derivation supplies every dependency from `python3Packages` so builds never reach PyPI.

**Tech Stack:** Python 3.11+ (built with nixpkgs `python3`), `typer`, `pydantic` v2, `pydantic-settings` v2, `httpx` (declared, imported in Phase 2), `pyyaml`, `pytest`, `ruff`, `mypy`, Nix flake using the already-pinned `nixpkgs` and `flake-utils` inputs with `flake-utils.lib.eachSystem` over `x86_64-linux` and `aarch64-linux`.

---

## Phase Boundary (read first)

This plan implements **Phase 1 (Foundation) only**. It must **not** add `oscal`, `pypdf`, or `python-docx`, must not open a SQLite store, and must not make HTTP calls. Subcommands parse/resolve configuration and then exit with code 2 and a clear "not implemented in Phase 1" message; the pipeline modules (`loaders/`, `catalog_adapters/`, `clients/`, `store/`, `pipeline/`, `oscal_build/`, `prompts/`) are deliberately out of scope and are added in later phases.

Deviations from the original brief, made deliberately for this phase:

- The Nix flake introduces **no new inputs**: it declares only the repository's two already-pinned inputs, `nixpkgs` (`github:nixos/nixpkgs/nixos-unstable`) and `flake-utils` (`github:numtide/flake-utils`), and iterates systems with `flake-utils.lib.eachSystem`.
- The system list is limited to `x86_64-linux` and `aarch64-linux` (the brief's two Linux targets).

## Reference Documents

- Spec: `docs/superpowers/specs/2026-10-01-smeargle-design.md` (the "Approved spec").
- Skill(s): `superpowers:writing-plans` (authoring), `superpowers:subagent-driven-development` or `superpowers:executing-plans` (execution).

## Global Conventions For Every Task

- **Every Python invocation MUST be an explicit Nix shell command.** Never run bare `pytest`, `python`, `ruff`, `mypy`, or `smeargle`; always wrap them, for example `nix develop -c pytest -q`, `nix develop -c ruff check src tests`, `nix develop -c mypy src`, `nix develop -c python -m smeargle --version`. The dev shell deliberately does **not** install the package under test — doing so would run the in-flux `pytestCheckHook` suite just to enter the shell and would break every red TDD step. Instead the dev shell's `shellHook` puts `src/` on `PYTHONPATH`, so dev-shell CLI checks use `nix develop -c python -m smeargle ...`. The only direct commands are `nix build`/`nix build .#smeargle` and the real built binary (`./result/bin/smeargle`). Run every command from the repository root: the dev shell's `shellHook` derives `PYTHONPATH` from `$PWD`, and `pytest` locates `pyproject.toml` from the root.
- **DRY / YAGNI:** implement exactly what the task specifies. Do not add fields, helpers, or abstractions "for later".
- **TDD:** write the failing test, run it, watch it fail for the stated reason, write the minimal implementation, run it green, commit.
- **Commits:** Conventional Commits, all lowercase, imperative mood, no trailing period. Every commit carries the mandatory `Assisted-by` trailer. Never `git push`.
- Replace the `Assisted-by` value with the model you are actually running as; the example uses `DeepSeek Flash via OpenCode`.
- Do not add comments to code unless a docstring is shown in the plan.

## File Structure (responsibilities locked before tasks)

```
flake.nix                          # package/devShell/checks/apps for x86_64-linux + aarch64-linux
pyproject.toml                     # PEP 621 metadata, src layout, console script, pytest/ruff/mypy config
src/smeargle/__init__.py           # package docstring + __version__ (single source for --version)
src/smeargle/__main__.py           # `python -m smeargle` entry point
src/smeargle/errors.py             # typed SmeargleError hierarchy + EXIT_* constants + exit_code_for()
src/smeargle/observability.py      # configure_logging(text|json) + central redact()
src/smeargle/domain/__init__.py    # namespace marker for the pure domain package
src/smeargle/domain/clock.py       # Clock Protocol, SystemClock, FrozenClock
src/smeargle/domain/ids.py         # IdFactory Protocol, UuidIdFactory, fingerprint, config_hash, id derivations
src/smeargle/domain/documents.py   # Document value
src/smeargle/domain/requirements.py# Keyword enum + Requirement value
src/smeargle/domain/controls.py    # Control + DomainIndex values
src/smeargle/domain/mapping.py     # Relationship enum (+ POSITIVE_RELATIONSHIPS), CandidatePair, MappingRecord
src/smeargle/domain/run.py         # RunFingerprint + RunConfig values
src/smeargle/config.py             # Settings (CLI > SMEARGLE_* env > TOML/YAML > defaults) + groups
src/smeargle/cli.py                # Typer app, shared globals, subcommands, main() exit-code mapping
tests/unit/test_package.py         # package/version smoke test
tests/unit/test_errors.py          # error -> exit-code mapping
tests/unit/test_observability.py   # redaction
tests/unit/test_config.py          # config precedence
tests/unit/test_cli.py             # --help/--version/not-implemented/usage-error
tests/unit/domain/test_clock.py    # clock determinism
tests/unit/domain/test_ids.py      # determinism + identity derivations
tests/unit/domain/test_values.py   # dataclass/enum contracts
tests/unit/test_dependencies.py    # domain imports no project code, no pydantic, and no I/O
```

**Dependency direction (spec §4), enforced by `tests/unit/test_dependencies.py`:** `cli → config / observability / errors`; `domain → nothing project-internal` and `domain → no pydantic`.

---

## Task 1: Nix build/dev shell and Python package skeleton

**Files:**
- Modify (replace): `flake.nix`
- Create: `pyproject.toml`
- Create: `src/smeargle/__init__.py`
- Create: `tests/unit/test_package.py`

**Spec traceability:** §4 (layout), §13/Q13 (packaging, `buildPythonApplication`, dev shell, `nix build .#smeargle`).

- [ ] **Step 1: Replace `flake.nix`**

```nix
{
  description = "smeargle: map RFC 2119 requirements to OSCAL control catalogs";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      flake-utils,
      nixpkgs,
      ...
    }:
    flake-utils.lib.eachSystem
      [
        "x86_64-linux"
        "aarch64-linux"
      ]
      (
        system:
        let
          pkgs = import self.inputs.nixpkgs { inherit system; };
          py = pkgs.python3Packages;
          smeargle = py.buildPythonApplication {
            pname = "smeargle";
            version = "0.1.0";
            pyproject = true;
            src = pkgs.lib.cleanSourceWith {
              src = ./.;
              filter = path: type:
                let
                  root = toString ./.;
                  rel = pkgs.lib.removePrefix (root + "/") (toString path);
                in
                rel == "pyproject.toml"
                || rel == "src"
                || rel == "tests"
                || pkgs.lib.hasPrefix "src/" rel
                || pkgs.lib.hasPrefix "tests/" rel;
            };
            build-system = [ py.setuptools ];
            dependencies = with py; [
              typer
              pydantic
              pydantic-settings
              httpx
              pyyaml
            ];
            nativeCheckInputs = [ py.pytestCheckHook ];
            pythonImportsCheck = [ "smeargle" ];
            meta = {
              description = "Map RFC 2119 requirements to OSCAL control catalogs";
              mainProgram = "smeargle";
            };
          };
        in
        {
          packages = {
            inherit smeargle;
            default = smeargle;
          };

          devShells.default = pkgs.mkShell {
            packages = [
              (pkgs.python3.withPackages (ps: [
                ps.typer
                ps.pydantic
                ps.pydantic-settings
                ps.httpx
                ps.pyyaml
                ps.pytest
              ]))
              py.ruff
              py.mypy
            ];
            shellHook = ''
              export PYTHONPATH="$PWD/src''${PYTHONPATH:+:$PYTHONPATH}"
            '';
          };

          checks.default = self.packages.${system}.smeargle;

          apps.default = {
            type = "app";
            program = "${self.packages.${system}.smeargle}/bin/smeargle";
          };
        }
      );
}
```

The `devShell` intentionally omits `self.packages.${system}.smeargle`: that package runs `pytestCheckHook`, so including it would build and test the in-flux suite merely to enter the shell, breaking every "run the failing test" step. Instead the `shellHook` prepends `src/` to `PYTHONPATH` for `python -m smeargle`, and `pyproject.toml` sets `pythonpath = ["src"]` so `nix develop -c pytest` imports `smeargle` from source. `pytestCheckHook` stays on the package, so `nix build`/`checks.default` still run the suite once green. The `''${PYTHONPATH:+:$PYTHONPATH}` escape is required because `${...}` is Nix string interpolation.

The flake `src` uses `cleanSourceWith` to bundle only `src/`, `tests/`, and `pyproject.toml`, so unrelated untracked files (`pci-dss-4.json`, session logs, `.tmp/`) never enter the build. `tests/` stays in the filtered source, so `pytestCheckHook` still discovers the suite.

The `shellHook` derives `PYTHONPATH` from `$PWD`, so run `nix develop -c ...` **from the repository root** (the plan's commands assume this). Running from another directory would leave `src/` off `PYTHONPATH`; `pytest` likewise expects the repo root so it can find `pyproject.toml`.

- [ ] **Step 2: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "smeargle"
version = "0.1.0"
description = "Map RFC 2119 requirements to OSCAL control catalogs."
requires-python = ">=3.11"
dependencies = [
  "typer>=0.12",
  "pydantic>=2.6",
  "pydantic-settings>=2.2",
  "httpx>=0.27",
  "pyyaml>=6.0",
]

[project.scripts]
smeargle = "smeargle.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I"]

[tool.mypy]
python_version = "3.11"
ignore_missing_imports = true
```

- [ ] **Step 3: Write the failing test**

Create `tests/unit/test_package.py`:

```python
import smeargle


def test_version_is_exposed():
    assert smeargle.__version__ == "0.1.0"
```

- [ ] **Step 4: Run the test and see it fail**

Run: `nix develop -c pytest tests/unit/test_package.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'smeargle'` (`src/smeargle/__init__.py` does not exist yet).

- [ ] **Step 5: Write the minimal implementation**

Create `src/smeargle/__init__.py`:

```python
"""smeargle: map RFC 2119 requirements to OSCAL control catalogs."""

__all__ = ["__version__"]

__version__ = "0.1.0"
```

- [ ] **Step 6: Run the test and see it pass**

Run: `nix develop -c pytest tests/unit/test_package.py -v`
Expected: `1 passed`.

- [ ] **Step 7: Verify the Nix build**

Run: `nix build .#smeargle`
Expected: exit 0; the derivation runs `pytestCheckHook` (1 passed) and `pythonImportsCheck`; `./result/bin/smeargle` exists (it will fail at runtime until `cli.py` lands in Task 8, which is fine).

- [ ] **Step 8: Commit**

```bash
git add flake.nix pyproject.toml src/smeargle/__init__.py tests/unit/test_package.py
git commit -m "chore(build): scaffold python package with nix flake" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 2: Typed errors and exit-code mapping

**Files:**
- Create: `src/smeargle/errors.py`
- Test: `tests/unit/test_errors.py`

**Spec traceability:** §12.2 (the exit-code table), §15 (errors centralised in `errors.py` and mapped to exit codes in the CLI).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_errors.py`:

```python
import pytest

from smeargle import errors


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (errors.UsageError("x"), 2),
        (errors.InputError("x"), 3),
        (errors.CatalogError("x"), 4),
        (errors.ServiceError("x"), 5),
        (errors.GapsError("x"), 6),
        (errors.IntegrityError("x"), 7),
        (errors.AbortedError("x"), 8),
        (errors.SmeargleError("x"), 1),
    ],
)
def test_exit_code_for_smeargle_error(exc, code):
    assert errors.exit_code_for(exc) == code


def test_exit_code_for_unknown_is_unexpected():
    assert errors.exit_code_for(ValueError("x")) == errors.EXIT_UNEXPECTED


def test_exit_code_constants_match_spec():
    assert errors.EXIT_SUCCESS == 0
    assert errors.EXIT_ABORTED == 8
```

- [ ] **Step 2: Run the test and see it fail**

Run: `nix develop -c pytest tests/unit/test_errors.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'smeargle.errors'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/smeargle/errors.py`:

```python
"""Typed errors and exit-code mapping (spec 12.2, 15)."""

from __future__ import annotations

EXIT_SUCCESS = 0
EXIT_UNEXPECTED = 1
EXIT_USAGE = 2
EXIT_INPUT = 3
EXIT_CATALOG = 4
EXIT_SERVICE = 5
EXIT_GAPS = 6
EXIT_INTEGRITY = 7
EXIT_ABORTED = 8


class SmeargleError(Exception):
    exit_code: int = EXIT_UNEXPECTED


class UsageError(SmeargleError):
    exit_code = EXIT_USAGE


class InputError(SmeargleError):
    exit_code = EXIT_INPUT


class CatalogError(SmeargleError):
    exit_code = EXIT_CATALOG


class ServiceError(SmeargleError):
    exit_code = EXIT_SERVICE


class GapsError(SmeargleError):
    exit_code = EXIT_GAPS


class IntegrityError(SmeargleError):
    exit_code = EXIT_INTEGRITY


class AbortedError(SmeargleError):
    exit_code = EXIT_ABORTED


def exit_code_for(exc: BaseException) -> int:
    if isinstance(exc, SmeargleError):
        return exc.exit_code
    return EXIT_UNEXPECTED
```

- [ ] **Step 4: Run the test and see it pass**

Run: `nix develop -c pytest tests/unit/test_errors.py -v`
Expected: `10 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/smeargle/errors.py tests/unit/test_errors.py
git commit -m "feat(errors): add typed errors and exit-code mapping" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 3: Structured logging and central secret redaction

**Files:**
- Create: `src/smeargle/observability.py`
- Test: `tests/unit/test_observability.py`

**Spec traceability:** §15 (structured logging, central redaction), §7 `evidence.request_json [compressed + redacted]`, §11.4 (redacted config snapshot).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_observability.py`:

```python
from smeargle.observability import REDACTED, is_secret_key, redact


def test_redacts_secret_keys_recursively():
    data = {"api_key": "s", "nested": {"Authorization": "Bearer x", "path": "a"}}
    out = redact(data)
    assert out["api_key"] == REDACTED
    assert out["nested"]["Authorization"] == REDACTED
    assert out["nested"]["path"] == "a"


def test_redacts_lists():
    assert redact([{"token": "t"}]) == [{"token": REDACTED}]


def test_is_secret_key():
    assert is_secret_key("llm_api_key")
    assert is_secret_key("Authorization")
    assert not is_secret_key("model")
```

- [ ] **Step 2: Run the test and see it fail**

Run: `nix develop -c pytest tests/unit/test_observability.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'smeargle.observability'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/smeargle/observability.py`:

```python
"""Structured logging and central secret redaction (spec 15)."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, Mapping

REDACTED = "[REDACTED]"
_SECRET_MARKERS = (
    "api_key",
    "apikey",
    "authorization",
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
)


def is_secret_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return any(marker in lowered for marker in _SECRET_MARKERS)


def redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: (REDACTED if is_secret_key(str(key)) else redact(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "smeargle", None)
        if isinstance(extra, Mapping):
            payload["data"] = redact(dict(extra))
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, sort_keys=True, default=str)


def configure_logging(log_format: str = "text", verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(stream=sys.stderr)
    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
```

- [ ] **Step 4: Run the test and see it pass**

Run: `nix develop -c pytest tests/unit/test_observability.py -v`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/smeargle/observability.py tests/unit/test_observability.py
git commit -m "feat(observability): add structured logging and secret redaction" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 4: Domain clock

**Files:**
- Create: `src/smeargle/domain/__init__.py`
- Create: `src/smeargle/domain/clock.py`
- Test: `tests/unit/domain/test_clock.py`

**Spec traceability:** §5 (`Clock.now_utc() -> datetime`, timezone-aware UTC, frozen to the run's `created_at`), §11.7 (timestamps from the frozen run `Clock`).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/domain/test_clock.py`:

```python
from datetime import datetime, timezone

import pytest

from smeargle.domain.clock import FrozenClock, SystemClock


def test_frozen_clock_returns_fixed_time():
    moment = datetime(2026, 1, 1, tzinfo=timezone.utc)
    clock = FrozenClock(moment)
    assert clock.now_utc() == moment
    assert clock.now_utc() is clock.now_utc()


def test_frozen_clock_requires_timezone():
    with pytest.raises(ValueError):
        FrozenClock(datetime(2026, 1, 1))


def test_system_clock_is_timezone_aware():
    assert SystemClock().now_utc().tzinfo is not None
```

- [ ] **Step 2: Run the test and see it fail**

Run: `nix develop -c pytest tests/unit/domain/test_clock.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'smeargle.domain'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/smeargle/domain/__init__.py`:

```python
"""Domain package: frozen stdlib dataclasses, no I/O, no Pydantic (spec 4, 5)."""
```

Create `src/smeargle/domain/clock.py`:

```python
"""Injected clocks for deterministic timestamps (spec 5)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    def now_utc(self) -> datetime: ...


class SystemClock:
    def now_utc(self) -> datetime:
        return datetime.now(timezone.utc)


class FrozenClock:
    def __init__(self, moment: datetime) -> None:
        if moment.tzinfo is None:
            raise ValueError("FrozenClock requires a timezone-aware datetime")
        self._moment = moment.astimezone(timezone.utc)

    def now_utc(self) -> datetime:
        return self._moment
```

- [ ] **Step 4: Run the test and see it pass**

Run: `nix develop -c pytest tests/unit/domain/test_clock.py -v`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/smeargle/domain/__init__.py src/smeargle/domain/clock.py tests/unit/domain/test_clock.py
git commit -m "feat(domain): add injectable clock protocol" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 5: Deterministic IDs, fingerprints, and config hashing

**Files:**
- Create: `src/smeargle/domain/ids.py`
- Test: `tests/unit/domain/test_ids.py`

**Spec traceability:** §5 (`IdFactory.uuid_for(kind, stable_key)` UUIDv5, `run_uuid()`, `doc_id`, `req_id`, `pair_id`, `catalog_id`, `index_id` derivations, `map_uuid`), §7.1 (`fingerprint` content-only, order-independent, version-salted; `config_hash` covers config inputs). Domain is pure: the file-level `sha256_file` step of §7.1 is performed by callers, so `fingerprint` accepts already-computed content digests.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/domain/test_ids.py`:

```python
import uuid

from smeargle.domain.ids import (
    UuidIdFactory,
    catalog_id_for,
    config_hash,
    doc_id_for,
    fingerprint,
    index_id_for,
    pair_id_for,
    req_id_for,
)


def test_doc_and_catalog_ids_are_content_hashes():
    assert doc_id_for(b"abc") == doc_id_for(b"abc")
    assert doc_id_for(b"abc") != doc_id_for(b"abd")
    assert len(doc_id_for(b"abc")) == 64
    assert catalog_id_for(b"abc") == doc_id_for(b"abc")


def test_fingerprint_is_order_independent():
    assert fingerprint(["a", "b"], ["c"]) == fingerprint(["b", "a"], ["c"])


def test_fingerprint_is_content_sensitive():
    assert fingerprint(["a"], []) != fingerprint(["b"], [])
    assert fingerprint(["a"], []) != fingerprint(["a"], ["a"])


def test_req_id_is_prefixed_and_deterministic():
    r1 = req_id_for("deadbeef", "The system MUST x")
    r2 = req_id_for("deadbeef", "The system MUST x")
    r3 = req_id_for("deadbeef", "The system MUST y")
    assert r1 == r2
    assert r1 != r3
    assert r1.startswith("req-")


def test_pair_and_index_ids_are_deterministic():
    assert pair_id_for("req-a", "cat", "ctrl") == pair_id_for("req-a", "cat", "ctrl")
    assert pair_id_for("req-a", "cat", "ctrl") != pair_id_for("req-a", "cat", "ctrl2")
    assert index_id_for("sum", "model", "prompt") == index_id_for("sum", "model", "prompt")
    assert index_id_for("sum", "model", "prompt") != index_id_for("sum", "model2", "prompt")


def test_config_hash_is_order_independent_and_sensitive():
    assert config_hash({"a": 1, "b": 2}) == config_hash({"b": 2, "a": 1})
    assert config_hash({"a": 1}) != config_hash({"a": 2})


def test_uuid_factory_is_stable():
    factory = UuidIdFactory()
    u1 = factory.uuid_for("map", "run:req:cat:ctrl")
    u2 = factory.uuid_for("map", "run:req:cat:ctrl")
    assert u1 == u2
    assert uuid.UUID(u1)
    assert factory.uuid_for("map", "x") != factory.uuid_for("other", "x")
    assert uuid.UUID(factory.run_uuid())
```

- [ ] **Step 2: Run the test and see it fail**

Run: `nix develop -c pytest tests/unit/domain/test_ids.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'smeargle.domain.ids'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/smeargle/domain/ids.py`:

```python
"""Deterministic identifiers, fingerprints, and config hashing (spec 5, 7.1)."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Iterable, Mapping, Protocol

SMEARGLE_NAMESPACE = uuid.UUID("c1a9f7e2-4d3b-4a6e-9f21-8b7c6d5e4f30")
RUN_FINGERPRINT_SALT = b"smeargle-run/1\0"


class IdFactory(Protocol):
    def run_uuid(self) -> str: ...

    def uuid_for(self, kind: str, stable_key: str) -> str: ...


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def doc_id_for(content: bytes) -> str:
    return sha256_hex(content)


def catalog_id_for(content: bytes) -> str:
    return sha256_hex(content)


def _sha256_text(*parts: str) -> str:
    hasher = hashlib.sha256()
    for part in parts:
        hasher.update(part.encode("utf-8"))
    return hasher.hexdigest()


def req_id_for(doc_content_sha256: str, normalized_text: str) -> str:
    return "req-" + _sha256_text(doc_content_sha256, normalized_text)


def pair_id_for(req_id: str, catalog_id: str, control_id: str) -> str:
    return _sha256_text(req_id, catalog_id, control_id)


def index_id_for(content_sha256: str, model_id: str, prompt_hash: str) -> str:
    return _sha256_text(content_sha256, model_id, prompt_hash)


def fingerprint(input_digests: Iterable[str], catalog_digests: Iterable[str]) -> str:
    hasher = hashlib.sha256()
    hasher.update(RUN_FINGERPRINT_SALT)
    for digest in sorted(input_digests):
        hasher.update(digest.encode("utf-8") + b"\0")
    hasher.update(b"|")
    for digest in sorted(catalog_digests):
        hasher.update(digest.encode("utf-8") + b"\0")
    return hasher.hexdigest()


def config_hash(config: Mapping[str, Any]) -> str:
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"), default=str)
    return sha256_hex(canonical.encode("utf-8"))


class UuidIdFactory:
    def run_uuid(self) -> str:
        return str(uuid.uuid4())

    def uuid_for(self, kind: str, stable_key: str) -> str:
        return str(uuid.uuid5(SMEARGLE_NAMESPACE, f"{kind}:{stable_key}"))
```

- [ ] **Step 4: Run the test and see it pass**

Run: `nix develop -c pytest tests/unit/domain/test_ids.py -v`
Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/smeargle/domain/ids.py tests/unit/domain/test_ids.py
git commit -m "feat(domain): add deterministic id factory and fingerprints" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 6: Frozen domain dataclasses and enums

**Files:**
- Create: `src/smeargle/domain/documents.py`
- Create: `src/smeargle/domain/requirements.py`
- Create: `src/smeargle/domain/controls.py`
- Create: `src/smeargle/domain/mapping.py`
- Create: `src/smeargle/domain/run.py`
- Test: `tests/unit/domain/test_values.py`

**Spec traceability:** §5 (`Document`, `Requirement`, `Control`, `DomainIndex`, `CandidatePair`, `MappingRecord`, `RunFingerprint`, `RunConfig`; `Keyword` excludes `MAY`/`OPTIONAL`; `Relationship` has the six OSCAL values). Frozen stdlib dataclasses, no I/O, no Pydantic.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/domain/test_values.py`:

```python
from smeargle.domain.controls import Control, DomainIndex
from smeargle.domain.documents import Document
from smeargle.domain.mapping import (
    POSITIVE_RELATIONSHIPS,
    CandidatePair,
    MappingRecord,
    Relationship,
)
from smeargle.domain.requirements import Keyword, Requirement
from smeargle.domain.run import RunConfig, RunFingerprint


def test_keyword_excludes_may_and_optional():
    values = {k.value for k in Keyword}
    assert "MAY" not in values
    assert "OPTIONAL" not in values
    assert Keyword.MUST.value == "MUST"


def test_relationship_has_exactly_six_values():
    assert {r.value for r in Relationship} == {
        "equivalent-to",
        "equal-to",
        "subset-of",
        "superset-of",
        "intersects-with",
        "no-relationship",
    }
    assert len(POSITIVE_RELATIONSHIPS) == 5
    assert Relationship.NO_RELATIONSHIP not in POSITIVE_RELATIONSHIPS


def test_document_is_frozen_and_hashable():
    doc = Document("run", "doc", 0, "p", "u", None, "text/plain", "sha", 1, "x")
    assert doc == Document("run", "doc", 0, "p", "u", None, "text/plain", "sha", 1, "x")
    hash(doc)


def test_requirement_holds_keyword_and_status():
    req = Requirement(
        run_id="run",
        req_id="req-1",
        doc_id="doc",
        ordinal=0,
        text="MUST x",
        normalized_text="MUST x",
        keyword=Keyword.MUST,
        extract_status="proposed",
        gate_status=None,
        gate_noul_prob=None,
        gate_choice=None,
        retrieve_status=None,
    )
    assert req.keyword is Keyword.MUST
    hash(req)


def test_control_and_domain_index_values():
    control = Control("run", "cat", "c1", "title", "text", "d", "f", ("a", "b"))
    assert control == Control("run", "cat", "c1", "title", "text", "d", "f", ("a", "b"))
    hash(control)
    index = DomainIndex("idx", "sum", "model", "prompt", {"d": ["c1"]})
    assert index == DomainIndex("idx", "sum", "model", "prompt", {"d": ["c1"]})


def test_candidate_pair_and_mapping_record_values():
    pair = CandidatePair("run", "pair", "req", "cat", "c1", "pending", 0.9)
    assert pair == CandidatePair("run", "pair", "req", "cat", "c1", "pending", 0.9)
    hash(pair)
    record = MappingRecord("run", "req", "cat", "c1", Relationship.SUBSET_OF, 0.9, "high")
    assert record == MappingRecord(
        "run", "req", "cat", "c1", Relationship.SUBSET_OF, 0.9, "high"
    )
    hash(record)


def test_run_values_are_frozen():
    fp = RunFingerprint(fingerprint="f", config_hash="c")
    rc = RunConfig(values={"a": 1})
    assert fp.fingerprint == "f"
    assert rc.values["a"] == 1
```

- [ ] **Step 2: Run the test and see it fail**

Run: `nix develop -c pytest tests/unit/domain/test_values.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'smeargle.domain.documents'`.

- [ ] **Step 3: Write the minimal implementations**

Create `src/smeargle/domain/documents.py`:

```python
"""Document domain value (spec 5)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True, slots=True)
class Document:
    run_id: str
    doc_id: str
    ordinal: int
    path: str
    uri: str
    external_id: Optional[str]
    media_type: str
    content_sha256: str
    size_bytes: int
    text: str
```

Create `src/smeargle/domain/requirements.py`:

```python
"""Requirement domain value and RFC 2119 keyword enum (spec 5)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Keyword(str, Enum):
    MUST = "MUST"
    MUST_NOT = "MUST NOT"
    SHALL = "SHALL"
    SHALL_NOT = "SHALL NOT"
    REQUIRED = "REQUIRED"
    SHOULD = "SHOULD"
    SHOULD_NOT = "SHOULD NOT"
    RECOMMENDED = "RECOMMENDED"
    NOT_RECOMMENDED = "NOT RECOMMENDED"


@dataclass(frozen=True, slots=True)
class Requirement:
    run_id: str
    req_id: str
    doc_id: str
    ordinal: int
    text: str
    normalized_text: str
    keyword: Optional[Keyword]
    extract_status: str
    gate_status: Optional[str]
    gate_noul_prob: Optional[float]
    gate_choice: Optional[str]
    retrieve_status: Optional[str]
```

Create `src/smeargle/domain/controls.py`:

```python
"""Control and domain-index domain values (spec 5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True, slots=True)
class Control:
    run_id: str
    catalog_id: str
    control_id: str
    title: str
    text: str
    domain: str
    family: str
    path: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DomainIndex:
    index_id: str
    content_sha256: str
    model_id: str
    prompt_hash: str
    domains: Mapping[str, list[str]] = field(default_factory=dict)
```

Create `src/smeargle/domain/mapping.py`:

```python
"""Mapping domain values and OSCAL relationship enum (spec 5)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Relationship(str, Enum):
    EQUIVALENT_TO = "equivalent-to"
    EQUAL_TO = "equal-to"
    SUBSET_OF = "subset-of"
    SUPERSET_OF = "superset-of"
    INTERSECTS_WITH = "intersects-with"
    NO_RELATIONSHIP = "no-relationship"


POSITIVE_RELATIONSHIPS: tuple[Relationship, ...] = (
    Relationship.EQUIVALENT_TO,
    Relationship.EQUAL_TO,
    Relationship.SUBSET_OF,
    Relationship.SUPERSET_OF,
    Relationship.INTERSECTS_WITH,
)


@dataclass(frozen=True, slots=True)
class CandidatePair:
    run_id: str
    pair_id: str
    req_id: str
    catalog_id: str
    control_id: str
    verify_status: str
    noul_prob: Optional[float] = None


@dataclass(frozen=True, slots=True)
class MappingRecord:
    run_id: str
    req_id: str
    catalog_id: str
    control_id: str
    relation: Relationship
    confidence_percentage: float
    confidence_category: str
```

Create `src/smeargle/domain/run.py`:

```python
"""Run-scoped domain values (spec 5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class RunFingerprint:
    fingerprint: str
    config_hash: str


@dataclass(frozen=True, slots=True)
class RunConfig:
    values: Mapping[str, Any] = field(default_factory=dict)
```

- [ ] **Step 4: Run the test and see it pass**

Run: `nix develop -c pytest tests/unit/domain/test_values.py -v`
Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/smeargle/domain/documents.py src/smeargle/domain/requirements.py src/smeargle/domain/controls.py src/smeargle/domain/mapping.py src/smeargle/domain/run.py tests/unit/domain/test_values.py
git commit -m "feat(domain): add frozen domain dataclasses and enums" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 7: Layered configuration

**Files:**
- Create: `src/smeargle/config.py`
- Test: `tests/unit/test_config.py`

**Spec traceability:** §6 (precedence **CLI > environment (`SMEARGLE_*`) > TOML/YAML file (`--config`) > defaults**; the four groups Paths/llm/jev/Mapping/Execution; secrets only via env/auth-file). §12 (`--state-dir`, `--log-format`, `--run-id`, `--force`, `--yes`, `--verbose`). §12.1 (`run_id`, `force`).

**Note on `--concurrency`:** spec §12 lists `--concurrency` under the mapping option group, while spec §6 groups concurrency under Execution. This plan follows **§6** and places `concurrency` in `ExecutionSettings`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_config.py`:

```python
from pathlib import Path

from smeargle.config import Settings


def test_defaults():
    s = Settings.load()
    assert s.mapping.extract_gate_threshold == 0.5
    assert s.state_dir == Path(".smeargle")
    assert s.llm.temperature == 0.0
    assert s.execution.log_format == "text"


def test_file_overrides_defaults(tmp_path):
    cfg = tmp_path / "smeargle.toml"
    cfg.write_text("[mapping]\nextract_gate_threshold = 0.6\n")
    s = Settings.load(config_file=cfg)
    assert s.mapping.extract_gate_threshold == 0.6


def test_env_overrides_file(tmp_path, monkeypatch):
    cfg = tmp_path / "smeargle.toml"
    cfg.write_text("[mapping]\nextract_gate_threshold = 0.6\n")
    monkeypatch.setenv("SMEARGLE_MAPPING__EXTRACT_GATE_THRESHOLD", "0.7")
    s = Settings.load(config_file=cfg)
    assert s.mapping.extract_gate_threshold == 0.7


def test_cli_overrides_env_and_file(tmp_path, monkeypatch):
    cfg = tmp_path / "smeargle.toml"
    cfg.write_text("[mapping]\nextract_gate_threshold = 0.6\n")
    monkeypatch.setenv("SMEARGLE_MAPPING__EXTRACT_GATE_THRESHOLD", "0.7")
    s = Settings.load(
        config_file=cfg,
        overrides={"mapping": {"extract_gate_threshold": 0.8}},
    )
    assert s.mapping.extract_gate_threshold == 0.8


def test_yaml_file_is_supported(tmp_path):
    cfg = tmp_path / "smeargle.yaml"
    cfg.write_text("mapping:\n  mapped_threshold: 0.65\n")
    s = Settings.load(config_file=cfg)
    assert s.mapping.mapped_threshold == 0.65


def test_secrets_are_referenced_not_stored():
    s = Settings.load()
    assert not hasattr(s.llm, "api_key")
    assert not hasattr(s.jev, "api_key")
```

- [ ] **Step 2: Run the test and see it fail**

Run: `nix develop -c pytest tests/unit/test_config.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'smeargle.config'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/smeargle/config.py`:

```python
"""Pydantic Settings with CLI > env > file > defaults precedence (spec 6)."""

from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path
from typing import Any, Literal, Mapping, Optional

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LlmSettings(BaseModel):
    endpoint: Optional[str] = None
    model: Optional[str] = None
    auth_file: Optional[Path] = None
    api_key_env: Optional[str] = None
    timeout: float = 60.0
    retries: int = 3
    temperature: float = 0.0
    structured_output: bool = True


class JevSettings(BaseModel):
    endpoint: Optional[str] = None
    model: Optional[str] = None
    auth_file: Optional[Path] = None
    api_key_env: Optional[str] = None
    timeout: float = 60.0
    retries: int = 3
    batch: bool = False
    batch_size: int = Field(default=64, ge=1, le=64)
    min_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    max_len: int = Field(default=4096, ge=1)
    head_max_len: int = Field(default=512, ge=1)


class MappingSettings(BaseModel):
    extract_gate_threshold: float = Field(default=0.50, ge=0.0, le=1.0)
    mapped_threshold: float = Field(default=0.50, ge=0.0, le=1.0)
    category_high: float = Field(default=0.80, ge=0.0, le=1.0)
    category_medium: float = Field(default=0.50, ge=0.0, le=1.0)
    nomination_cap: int = Field(default=0, ge=0)


class ExecutionSettings(BaseModel):
    log_format: Literal["text", "json"] = "text"
    chunk_size: int = Field(default=2000, ge=1)
    chunk_overlap: int = Field(default=200, ge=0)
    run_id: Optional[str] = None
    force: bool = False
    yes: bool = False
    verbose: bool = False
    catalog_format: Literal["auto", "oscal"] = "auto"
    gaps_fatal: bool = False
    concurrency: int = Field(default=4, ge=1)


_CONFIG_FILE: ContextVar[Optional[Path]] = ContextVar("smeargle_config_file", default=None)


def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, Mapping):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SMEARGLE_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    inputs: list[str] = Field(default_factory=list)
    catalogs: list[str] = Field(default_factory=list)
    output: Optional[Path] = None
    state_dir: Path = Path(".smeargle")
    llm: LlmSettings = Field(default_factory=LlmSettings)
    jev: JevSettings = Field(default_factory=JevSettings)
    mapping: MappingSettings = Field(default_factory=MappingSettings)
    execution: ExecutionSettings = Field(default_factory=ExecutionSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: Any,
        env_settings: Any,
        dotenv_settings: Any,
        file_secret_settings: Any,
    ) -> tuple[Any, ...]:
        from pydantic_settings import TomlConfigSettingsSource, YamlConfigSettingsSource

        sources: list[Any] = [init_settings, env_settings]
        path = _CONFIG_FILE.get()
        if path is not None:
            suffix = path.suffix.lower()
            if suffix in {".toml", ""}:
                sources.append(TomlConfigSettingsSource(settings_cls, toml_file=path))
            elif suffix in {".yaml", ".yml"}:
                sources.append(YamlConfigSettingsSource(settings_cls, yaml_file=path))
            else:
                raise ValueError(f"unsupported config file extension: {path.suffix}")
        sources.append(file_secret_settings)
        return tuple(sources)

    @classmethod
    def load(
        cls,
        config_file: Optional[Path] = None,
        overrides: Optional[Mapping[str, Any]] = None,
    ) -> "Settings":
        token = _CONFIG_FILE.set(Path(config_file) if config_file is not None else None)
        try:
            base = cls()
        finally:
            _CONFIG_FILE.reset(token)
        if not overrides:
            return base
        merged = _deep_merge(base.model_dump(), overrides)
        return cls.model_validate(merged)
```

- [ ] **Step 4: Run the test and see it pass**

Run: `nix develop -c pytest tests/unit/test_config.py -v`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/smeargle/config.py tests/unit/test_config.py
git commit -m "feat(config): add layered pydantic settings" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 8: Typer CLI with central exit-code mapping

**Files:**
- Create: `src/smeargle/cli.py`
- Create: `src/smeargle/__main__.py`
- Test: `tests/unit/test_cli.py`

**Spec traceability:** §12 (shared globals `--config`, `--state-dir`, `--output`, `--log-format`, `--run-id`, `--force`, `--verbose`, `--yes`; subcommands `run`/`extract`/`map`/`resume`/`validate`/`status`), §12.2 + §15 (errors mapped to exit codes centrally in the CLI). Phase boundary: every subcommand resolves configuration, then exits 2 with a clear "not implemented in Phase 1" message.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_cli.py`:

```python
from smeargle.cli import main


def test_version_exits_zero(capsys):
    code = main(["--version"])
    assert code == 0
    assert "smeargle" in capsys.readouterr().out


def test_help_lists_subcommands(capsys):
    code = main(["--help"])
    out = capsys.readouterr().out
    assert code == 0
    for command in ("run", "extract", "map", "resume", "validate", "status"):
        assert command in out


def test_subcommand_reports_not_implemented(capsys):
    code = main(["run"])
    err = capsys.readouterr().err
    assert code == 2
    assert "not implemented in Phase 1" in err


def test_unknown_option_is_usage_error():
    code = main(["--nope"])
    assert code == 2
```

- [ ] **Step 2: Run the test and see it fail**

Run: `nix develop -c pytest tests/unit/test_cli.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'smeargle.cli'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/smeargle/cli.py`:

```python
"""Typer CLI, shared globals, and central exit-code mapping (spec 12)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from smeargle import __version__
from smeargle.config import Settings
from smeargle.errors import (
    EXIT_ABORTED,
    EXIT_SUCCESS,
    EXIT_UNEXPECTED,
    SmeargleError,
    UsageError,
    exit_code_for,
)
from smeargle.observability import configure_logging

app = typer.Typer(
    name="smeargle",
    help="Map RFC 2119 requirements to OSCAL control catalogs.",
    no_args_is_help=True,
    add_completion=False,
)


def _resolve_settings(ctx: typer.Context) -> Settings:
    if not isinstance(ctx.obj, Settings):
        raise UsageError("internal error: settings were not resolved")
    return ctx.obj


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    config: Optional[Path] = typer.Option(None, "--config", help="TOML/YAML config file."),
    state_dir: Optional[Path] = typer.Option(None, "--state-dir", help="Run-state directory."),
    output: Optional[Path] = typer.Option(None, "--output", help="Output directory."),
    log_format: Optional[str] = typer.Option(None, "--log-format", help="text or json."),
    run_id: Optional[str] = typer.Option(None, "--run-id", help="Select a run explicitly."),
    force: bool = typer.Option(False, "--force", help="Start a new run."),
    verbose: bool = typer.Option(False, "--verbose", help="Verbose logging."),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation prompts."),
    version: bool = typer.Option(False, "--version", help="Show version and exit."),
) -> None:
    if version:
        typer.echo(f"smeargle {__version__}")
        raise typer.Exit(code=EXIT_SUCCESS)

    overrides: dict[str, object] = {}
    if output is not None:
        overrides["output"] = output
    if state_dir is not None:
        overrides["state_dir"] = state_dir
    execution: dict[str, object] = {}
    if log_format is not None:
        execution["log_format"] = log_format
    if run_id is not None:
        execution["run_id"] = run_id
    if force:
        execution["force"] = True
    if verbose:
        execution["verbose"] = True
    if yes:
        execution["yes"] = True
    if execution:
        overrides["execution"] = execution

    settings = Settings.load(config_file=config, overrides=overrides)
    configure_logging(settings.execution.log_format, verbose=settings.execution.verbose)
    ctx.obj = settings

    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(code=EXIT_SUCCESS)


def _not_implemented(name: str) -> None:
    raise UsageError(f"'{name}' is not implemented in Phase 1")


@app.command()
def run(ctx: typer.Context) -> None:
    """Run the full pipeline."""
    _resolve_settings(ctx)
    _not_implemented("run")


@app.command()
def extract(ctx: typer.Context) -> None:
    """Extract requirements only (Stages 0-1)."""
    _resolve_settings(ctx)
    _not_implemented("extract")


@app.command()
def map(ctx: typer.Context) -> None:
    """Map an existing run's requirements to catalogs."""
    _resolve_settings(ctx)
    _not_implemented("map")


@app.command()
def resume(ctx: typer.Context) -> None:
    """Continue an interrupted run."""
    _resolve_settings(ctx)
    _not_implemented("resume")


@app.command()
def validate(ctx: typer.Context) -> None:
    """Validate input catalogs and/or emitted artifacts."""
    _resolve_settings(ctx)
    _not_implemented("validate")


@app.command()
def status(ctx: typer.Context) -> None:
    """Show per-stage progress and counts."""
    _resolve_settings(ctx)
    _not_implemented("status")


def main(argv: Optional[list[str]] = None) -> int:
    try:
        result = app(args=argv, standalone_mode=False)
        return result if isinstance(result, int) else EXIT_SUCCESS
    except SmeargleError as exc:
        typer.secho(f"smeargle: {exc}", fg=typer.colors.RED, err=True)
        return exit_code_for(exc)
    except typer.Abort:
        typer.secho("smeargle: aborted", fg=typer.colors.RED, err=True)
        return EXIT_ABORTED
    except typer.Exit as exc:
        return int(exc.exit_code)
    except Exception as exc:
        show = getattr(exc, "show", None)
        exit_code = getattr(exc, "exit_code", None)
        if callable(show) and isinstance(exit_code, int):
            show()
            return exit_code
        typer.secho(f"smeargle: unexpected error: {exc}", fg=typer.colors.RED, err=True)
        return EXIT_UNEXPECTED
```

`cli.py` imports only `typer`, never `click` directly (`click` is a transitive dependency). `main()` catches `typer.Exit`/`typer.Abort` and, for click's usage errors (not re-exported by typer), detects the exception by duck typing (`show` + integer `exit_code`) and returns that code; this preserves the tested exit-0/exit-2 behaviour without a new dependency.

Create `src/smeargle/__main__.py`:

```python
"""Module entry point: python -m smeargle."""

from smeargle.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the test and see it pass**

Run: `nix develop -c pytest tests/unit/test_cli.py -v`
Expected: `4 passed`.

- [ ] **Step 5: Run the whole suite and the build**

Run: `nix develop -c pytest -q`
Expected: all tests pass.

Run: `nix develop -c python -m smeargle --version`
Expected: `smeargle 0.1.0` (run from the repository root; imported from `src/` via the dev shell's `PYTHONPATH`; the dev shell does not install the package under test).

Run: `nix build .#smeargle`
Expected: exit 0; pytest runs inside the derivation; `./result/bin/smeargle --version` prints `smeargle 0.1.0`.

- [ ] **Step 6: Commit**

```bash
git add src/smeargle/cli.py src/smeargle/__main__.py tests/unit/test_cli.py
git commit -m "feat(cli): add typer app with config resolution and exit mapping" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 9: Enforce the dependency-direction contract

**Files:**
- Test: `tests/unit/test_dependencies.py`

**Spec traceability:** §4 (`domain → (nothing project-internal)`, no Pydantic in `domain/`), §5 ("no I/O"): the domain layer must not import I/O modules (`httpx`, `socket`, `subprocess`, `urllib`, `requests`). The dependency direction is enforced by a test.

This is a **guard/regression test**: it passes immediately because the domain was written correctly. Step 3 deliberately breaks it to prove it bites, then restores it.

- [ ] **Step 1: Write the test**

Create `tests/unit/test_dependencies.py`:

```python
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "smeargle"
DOMAIN = SRC / "domain"
FORBIDDEN_IO = ("httpx", "socket", "subprocess", "urllib", "requests")
FORBIDDEN_THIRD_PARTY = ("pydantic",)


def _imported_modules(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            yield node.module or ""


def test_domain_imports_nothing_project_internal_pydantic_or_io():
    for path in DOMAIN.glob("*.py"):
        for module in _imported_modules(ast.parse(path.read_text())):
            root = module.split(".")[0]
            assert root not in FORBIDDEN_THIRD_PARTY, f"{path.name} imports {module}"
            assert root not in FORBIDDEN_IO, f"{path.name} imports {module}"
            if module.startswith("smeargle"):
                assert module == "smeargle.domain" or module.startswith("smeargle.domain."), (
                    f"{path.name} imports {module}"
                )
```

- [ ] **Step 2: Run the test and see it pass**

Run: `nix develop -c pytest tests/unit/test_dependencies.py -v`
Expected: `1 passed` (the domain layer is clean).

- [ ] **Step 3: Prove the guard bites (temporarily violate it)**

Temporarily add `import httpx` to the top of `src/smeargle/domain/ids.py` (this is an I/O import the domain contract forbids).

Run: `nix develop -c pytest tests/unit/test_dependencies.py -v`
Expected: `1 failed` with `AssertionError: ids.py imports httpx`.

Remove the temporary import; do not commit it. (Adding `import pydantic` instead also fails, with `AssertionError: ids.py imports pydantic`.)

- [ ] **Step 4: Confirm green again**

Run: `nix develop -c pytest tests/unit/test_dependencies.py -v`
Expected: `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_dependencies.py
git commit -m "test(domain): enforce dependency-direction contract" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 10: Spec-driven suitability for run (Phase 1 acceptance)

**Files:** none (verification only). No commit.

This task proves the phase is genuinely runnable, exactly as an operator would use it. Run each command **from the repository root** (the dev shell's `shellHook` derives `PYTHONPATH` from `$PWD`) and compare to the expected output.

- [ ] **Step 1: Invoke the CLI from source through the dev shell**

Run:

```bash
nix develop -c python -m smeargle --version
nix develop -c python -m smeargle --help
```

Expected:

- `smeargle 0.1.0` (imported from `src/` via the dev shell's `PYTHONPATH`).
- A Typer help screen whose `Commands` block lists `run`, `extract`, `map`, `resume`, `validate`, `status`, and whose `Options` block lists `--config`, `--state-dir`, `--output`, `--log-format`, `--run-id`, `--force`, `--verbose`, `--yes`, `--version`, `--help`.

- [ ] **Step 2: Exercise a subcommand and exit codes**

Run:

```bash
nix develop -c python -m smeargle run; echo "exit=$?"
nix develop -c python -m smeargle --nope; echo "exit=$?"
```

Expected:

- `smeargle: 'run' is not implemented in Phase 1` on stderr, then `exit=2`.
- A click usage error on stderr, then `exit=2`.

- [ ] **Step 3: Build the application and run the built binary**

Run:

```bash
nix build .#smeargle
./result/bin/smeargle --version
./result/bin/smeargle --help
```

Expected:

- `nix build` exits 0 (its `pytestCheckHook` phase reports all tests passing and `pythonImportsCheck` succeeds).
- `smeargle 0.1.0`.
- The same help screen as Step 1.

- [ ] **Step 4: Run the full suite and the check output**

Run:

```bash
nix develop -c pytest -q
nix develop -c ruff check src tests
nix develop -c mypy src
nix build .#checks.x86_64-linux.default
```

Expected:

- `pytest`: all tests pass (the suite contains the package, errors, observability, config precedence, clock, ids, domain values, CLI, and dependency-direction tests).
- `ruff`: `All checks passed!`.
- `mypy`: `Success: no issues found in ... source files`.
- `nix build .#checks.x86_64-linux.default`: exit 0.

- [ ] **Step 5: Record acceptance**

No files change. If every expected result above matches, Phase 1 is complete and ready for the Phase 2 (ingestion/clients/store) plan.

---

## Appendix A: Commit sequence

| # | Commit message (lowercase, Conventional Commits) |
|---|---|
| 1 | `chore(build): scaffold python package with nix flake` |
| 2 | `feat(errors): add typed errors and exit-code mapping` |
| 3 | `feat(observability): add structured logging and secret redaction` |
| 4 | `feat(domain): add injectable clock protocol` |
| 5 | `feat(domain): add deterministic id factory and fingerprints` |
| 6 | `feat(domain): add frozen domain dataclasses and enums` |
| 7 | `feat(config): add layered pydantic settings` |
| 8 | `feat(cli): add typer app with config resolution and exit mapping` |
| 9 | `test(domain): enforce dependency-direction contract` |

Task 10 produces no commit.

## Appendix B: Spec traceability matrix

| Test file | Spec requirement(s) |
|---|---|
| `tests/unit/test_package.py` | §4 layout, §13/Q13 packaging + `--version` source |
| `tests/unit/test_errors.py` | §12.2 exit-code table, §15 central mapping |
| `tests/unit/test_observability.py` | §15 redaction, §7/§11.4 redacted evidence/config |
| `tests/unit/domain/test_clock.py` | §5 `Clock`, §11.7 frozen timestamps |
| `tests/unit/domain/test_ids.py` | §5 identity derivations, §7.1 fingerprint/config_hash |
| `tests/unit/domain/test_values.py` | §5 dataclasses + `Keyword`/`Relationship` enums |
| `tests/unit/test_config.py` | §6 precedence + groups + secret handling; §12/§12.1 options |
| `tests/unit/test_cli.py` | §12 globals/subcommands, §12.2/§15 exit mapping |
| `tests/unit/test_dependencies.py` | §4 dependency direction (no Pydantic, no internal imports in `domain/`) |
| Task 10 (manual) | §13 `nix build .#smeargle`, §14 `pytest`/Nix checks |
