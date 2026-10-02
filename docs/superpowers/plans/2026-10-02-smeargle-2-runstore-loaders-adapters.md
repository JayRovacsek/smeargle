# smeargle Phase 2 (RunStore, Loaders, Catalog Adapters) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `smeargle` runnable and testable for state + ingestion — load arbitrary input documents, load and normalise both standard OSCAL and vendor `securityControls` catalogs, persist everything to the SQLite run store, and emit valid normalised OSCAL catalogs — with no LLM/JEV calls.

**Architecture:** Phase 1's typed domain core is reused unchanged. Phase 2 adds an `oscal_build.facade` (the only module importing `oscal`), a `store/` package (connection pragmas, `PRAGMA user_version` migrations, and a typed `RunStore` repository for every spec §7 table), a `loaders/` registry (`text`/`json_text`/`pdf`/`docx`), a `catalog_adapters/` registry (standard OSCAL via the facade, plus a vendor `securityControls` adapter), and a `pipeline/` that runs Stage 0 `load` and the catalog-ingest portion of Stage 2. Everything is built test-first with `pytest`; every Python/Nix invocation is wrapped in `nix develop -c ...` so all dependencies come from the pinned flake, never PyPI.

**Tech Stack:** Python 3.11+ (nixpkgs `python3`), `typer`, `pydantic`/`pydantic-settings`, `httpx` (declared, unused this phase), `pyyaml`, `oscal==3.2.2` (overlay-packaged with `ruf-common==2.2.0`), `pypdf`, `python-docx`, `jsonschema-rs` (offline JSON Schema validation via Rust's Unicode regex engine), standard-library `sqlite3`, `pytest`, `ruff`, `mypy`, and a hand-written Nix flake that adds **no new inputs** and uses `flake-utils.lib.eachSystem` over `x86_64-linux` and `aarch64-linux`.

---

## Phase Boundary (read first)

This plan implements **Phase 2 (state + ingestion) only**. It must **not** call any LLM or JEV endpoint, must not implement Stage 1 `extract`, Stage 3 `retrieve`, Stage 4 `verify`, Stage 5 `classify`, the LLM domain-index step of Stage 2, or the `assemble` stage (profile/mapping-collection/rationale emission). No Pydantic enters `domain/` or `oscal_build/`.

Phase 2 assumes Phase 1 (Foundation) is complete: `src/smeargle/` contains `cli.py`, `config.py`, `errors.py`, `observability.py`, and `domain/` (frozen dataclasses/enums, `Clock`/`IdFactory` protocols, `fingerprint`/`config_hash`, and identity derivations). Tests live under `tests/`. Phase 2 modifies only the files listed below; it leaves the Phase 1 domain untouched.

Deviations from the original spec, made deliberately for this phase:

- Nix flake outputs use **only** the already-pinned `nixpkgs` and `flake-utils` inputs, iterated with `flake-utils.lib.eachSystem` (no new inputs, no hand-rolled `forAllSystems`).
- The dev shell uses `pkgs.mkShell` with `pkgs.python3.withPackages` (ruff/mypy/pytest from nixpkgs) rather than spec §13's suggested `uv`/`mkVirtualEnv`; this keeps every dependency supplied by the pinned nixpkgs and avoids a second resolver.
- The normalised-catalog builder lives in `catalog_adapters/normalise.py` (plain dicts, no `oscal` import). Spec §4's `oscal_build/emit.py` and the assembled artifacts arrive in Phase 3.
- The loaders (`loaders/*.py`) are deliberately registry functions returning `(media_type, text)` rather than constructing `Document` values; `pipeline/load.py` owns `Document` construction (hashing raw bytes, ordinal assignment, persistence), keeping `content_sha256` tied to the raw input bytes per spec §9.1.
- The `domain_index` table is created and its content-keyed `RunStore.add_domain_index`/`get_domain_index` repository methods are included; only the LLM computation that populates the index is deferred to Phase 3.
- `config_hash` is computed over the LLM/JEV/mapping/execution settings that exist in Phase 2; **prompt hashes are omitted pending Phase 3**, when the `prompts/` package and its `PROMPT_HASH` values are introduced (spec §7.1).
- The `oscal` support database is configured to live under `--state-dir` (via `facade.configure_support_file`) so runs never litter the repository root.

## Reference Documents

- Spec: `docs/superpowers/specs/2026-10-01-smeargle-design.md` (the "Approved spec").
- Phase 1 plan: `docs/superpowers/plans/2026-10-02-smeargle-1-foundation.md`.
- Skill(s): `superpowers:writing-plans` (authoring), `superpowers:subagent-driven-development` or `superpowers:executing-plans` (execution).

### Phase 1 interface assumptions (verified against the Phase 1 plan)

Plan 2 calls only these Phase 1 symbols; each signature below matches `2026-10-02-smeargle-1-foundation.md`, so no shim or adaptation is required:

| Phase 1 symbol | Verified Phase 1 signature | Plan 2 call sites |
|---|---|---|
| `Settings.load` | `classmethod load(config_file: Optional[Path] = None, overrides: Optional[Mapping[str, Any]] = None) -> Settings` | `pipeline/run.py`, `cli.py` |
| `redact` | `redact(value: Any) -> Any` | `store/run_store.py` (`record_evidence`), `pipeline/run.py` |
| `config_hash` | `config_hash(config: Mapping[str, Any]) -> str` | `pipeline/run.py` |
| `fingerprint` | `fingerprint(input_digests: Iterable[str], catalog_digests: Iterable[str]) -> str` | `pipeline/run.py` |
| `sha256_hex` | `sha256_hex(data: bytes) -> str` | `store/run_store.py`, `pipeline/run.py` |
| `doc_id_for` | `doc_id_for(content: bytes) -> str` | `pipeline/load.py` |
| `catalog_id_for` | `catalog_id_for(content: bytes) -> str` | `pipeline/index.py` |
| `IdFactory` / `UuidIdFactory` | `run_uuid(self) -> str`; `uuid_for(self, kind: str, stable_key: str) -> str` | `pipeline/run.py`, tests |

The `StubIdFactory` used by Task 14 subclasses the Phase 1 `UuidIdFactory` and overrides only `run_uuid(self) -> str`; it inherits `uuid_for`. No other Phase 1 behaviour is assumed by Plan 2.

## Global Conventions For Every Task

- **Every Python invocation MUST be an explicit Nix shell command.** Never run bare `pytest`, `python`, `ruff`, `mypy`, or `smeargle`; always wrap them, for example `nix develop -c pytest -q`, `nix develop -c ruff check src tests`, `nix develop -c mypy src`, `nix develop -c python -m smeargle ...`. The only direct commands are `nix build`/`nix build .#smeargle` and the real built binary (`./result/bin/smeargle`). Run every command from the repository root.
- **Temporary files live inside the project**, under `.tmp/` (git-ignored), and are cleaned up afterwards. Never use `/tmp`, `$TMPDIR`, or any OS-managed transient path for scratch work.
- **DRY / YAGNI:** implement exactly what the task specifies. Do not add fields, helpers, or abstractions "for later".
- **TDD:** write the failing test, run it, watch it fail for the stated reason, write the minimal implementation, run it green, commit.
- **Commits:** Conventional Commits, all lowercase, imperative mood, no trailing period, ≤ 140 characters. Every commit carries the mandatory `Assisted-by: DeepSeek Flash via OpenCode` trailer. Never `git push`.
- Do not add comments to code unless a docstring is shown in the plan.

## File Structure (responsibilities locked before tasks)

```
flake.nix                                       # modify: apply overlay; add oscal/pypdf/python-docx deps
overlays/default.nix                            # create: extend python3Packages with oscal + ruf-common
package/oscal/default.nix                       # create: buildPythonPackage oscal==3.2.2
package/ruf-common/default.nix                  # create: buildPythonPackage ruf-common==2.2.0
pyproject.toml                                  # modify: add oscal/pypdf/python-docx; pythonpath += tests
.gitignore                                      # modify: ignore /support/
src/smeargle/oscal_build/__init__.py            # create: namespace marker
src/smeargle/oscal_build/facade.py              # create: ONLY module importing `oscal`
src/smeargle/store/__init__.py                  # create: namespace marker
src/smeargle/store/db.py                        # create: connect() + pragmas + transaction()
src/smeargle/store/schema.py                    # create: DDL, MIGRATIONS, migrate() with user_version guard
src/smeargle/store/run_store.py                 # create: typed repository over every spec §7 table
src/smeargle/loaders/__init__.py                # create: namespace marker
src/smeargle/loaders/text.py                    # create: BOM/encoding normalisation
src/smeargle/loaders/json_text.py               # create: deterministic JSON flattening
src/smeargle/loaders/pdf.py                     # create: pypdf loader + scanned-PDF rejection
src/smeargle/loaders/docx.py                    # create: python-docx loader
src/smeargle/loaders/registry.py                # create: suffix→loader registry + .doc rejection
src/smeargle/catalog_adapters/__init__.py       # create: namespace marker
src/smeargle/catalog_adapters/types.py          # create: ParsedControl / ParsedCatalog values
src/smeargle/catalog_adapters/ids.py            # create: TokenDatatype-safe control-id sanitisation
src/smeargle/catalog_adapters/oscal.py          # create: standard OSCAL adapter (pure, dict-based)
src/smeargle/catalog_adapters/vendor_security_controls.py  # create: vendor adapter (pure, dict-based)
src/smeargle/catalog_adapters/normalise.py      # create: build a normalised OSCAL catalog dict
src/smeargle/catalog_adapters/registry.py       # create: auto/oscal format detection + dispatch
src/smeargle/pipeline/__init__.py               # create: namespace marker
src/smeargle/pipeline/load.py                   # create: Stage 0 load (detect, dedup, persist)
src/smeargle/pipeline/index.py                  # create: catalog ingest portion of Stage 2
src/smeargle/pipeline/run.py                    # create: orchestrate load+ingest, fingerprint/config_hash
src/smeargle/errors.py                          # modify: add StoreError
src/smeargle/cli.py                             # modify: wire run/validate/status and new options
tests/conftest.py                               # create: session support-DB fixture
tests/support/__init__.py                       # create: package marker for test helpers
tests/support/schemas.py                        # create: offline OSCAL JSON Schema validator (jsonschema-rs)
tests/schemas/oscal-1.2.3/oscal_catalog_schema.json    # create: vendored, hash-pinned
tests/schemas/oscal-1.2.3/oscal_profile_schema.json    # create: vendored, hash-pinned
tests/schemas/oscal-1.2.3/oscal_mapping_schema.json    # create: vendored, hash-pinned
tests/unit/test_schema_hashes.py                # create: pin vendored schemas by sha256
tests/unit/oscal_build/test_facade.py           # create
tests/unit/store/test_schema.py                 # create
tests/unit/store/test_run_store.py              # create
tests/unit/loaders/test_text.py                 # create
tests/unit/loaders/test_json_text.py            # create
tests/unit/loaders/test_registry.py             # create
tests/unit/catalog_adapters/test_ids.py         # create
tests/unit/catalog_adapters/test_adapters.py    # create
tests/unit/catalog_adapters/__init__.py         # create: package marker
tests/unit/test_dependency_direction.py         # create: guard that only facade imports oscal
tests/unit/oscal_build/__init__.py              # create: package marker
tests/unit/store/__init__.py                    # create: package marker
tests/unit/loaders/__init__.py                  # create: package marker
tests/integration/__init__.py                   # create: package marker
tests/e2e/__init__.py                           # create: package marker
tests/integration/test_load_stage.py            # create
tests/integration/test_normalised_catalog.py    # create: emitted catalog vs vendored schema
tests/integration/test_ingest_pipeline.py       # create: end-to-end load+ingest into store
tests/integration/test_run_orchestration.py     # create: fingerprint/config_hash integration
tests/e2e/test_phase2_run.py                    # create: spec-driven suitability for run
tests/unit/test_cli.py                          # modify: Phase 2 CLI behaviour
```

**Dependency direction (spec §4):** `cli → config / pipeline / loaders / catalog_adapters / store → domain`; `oscal_build → domain (only)`; `catalog_adapters → domain / oscal_build`; `store → domain`; `domain → (nothing project-internal)`. `oscal_build/facade.py` is the only module that imports `oscal`; a guard test in Task 11 enforces that.

---

## Task 1: Nix packaging for `oscal`, `ruf-common`, and the overlay

**Files:**
- Create: `overlays/default.nix`
- Create: `package/oscal/default.nix`
- Create: `package/ruf-common/default.nix`
- Modify (replace): `flake.nix`
- Modify: `pyproject.toml`
- Modify: `.gitignore`

**Spec traceability:** §4/§13/Q14 (per-upstream packages under `package/<name>/`, overlay extending `python3Packages`, `jsonschema_rs` alias, `pythonImportsCheck`, `nix build .#smeargle` offline), §9.1 (pypdf/python-docx dependencies), §16 (`oscal` API churn isolated by pinning).

- [ ] **Step 1: Create `package/oscal/default.nix`**

```nix
{
  lib,
  buildPythonPackage,
  fetchPypi,
  setuptools,
  jsonschema-rs,
  jsonpath-python,
  xmlschema,
  pyyaml,
  markdown,
  ruf-common,
}:

buildPythonPackage rec {
  pname = "oscal";
  version = "3.2.2";
  pyproject = true;

  src = fetchPypi {
    inherit pname version;
    hash = "sha256-w5F33JBVBOluXpvgvoEQhyoZvvIbia/w25Zs25Mnsk8=";
  };

  build-system = [ setuptools ];

  dependencies = [
    jsonschema-rs
    jsonpath-python
    xmlschema
    pyyaml
    markdown
    ruf-common
  ];

  doCheck = false;
  pythonImportsCheck = [ "oscal" ];

  postInstall = ''
    python - <<'PY'
    from importlib import resources
    archive = resources.files("oscal.data").joinpath("oscal_support.zip")
    assert archive.is_file(), "bundled oscal support database is missing"
    assert archive.stat().st_size > 1_000_000, "bundled oscal support database looks truncated"
    PY
  '';

  meta = {
    description = "Python library to validate, convert, query and mutate OSCAL content";
    homepage = "https://github.com/brian-ruf/oscal-class";
    license = lib.licenses.mit;
    mainProgram = "oscal";
  };
}
```

`postInstall` exercises the ~15 MB bundled support archive via `importlib.resources` without extracting it, so a missing/truncated package-data file fails the build even though `pythonImportsCheck = [ "oscal" ]` alone would not open it.

- [ ] **Step 2: Create `package/ruf-common/default.nix`**

```nix
{
  lib,
  buildPythonPackage,
  fetchPypi,
  setuptools,
  elementpath,
  pytz,
  tzlocal,
  geopy,
  timezonefinder,
  aiohttp,
  requests,
  pycountry,
  html2text,
  packaging,
  pyyaml,
}:

buildPythonPackage rec {
  pname = "ruf-common";
  version = "2.2.0";
  pyproject = true;

  src = fetchPypi {
    pname = "ruf_common";
    inherit version;
    hash = "sha256-NwpwCrC1jwPGqH/r77SdrL7lTbKSjwApMSU8RN+DZkA=";
  };

  build-system = [ setuptools ];

  dependencies = [
    elementpath
    pytz
    tzlocal
    geopy
    timezonefinder
    aiohttp
    requests
    pycountry
    html2text
    packaging
    pyyaml
  ];

  doCheck = false;
  pythonImportsCheck = [ "ruf_common" ];

  meta = {
    description = "Functions common to several Python projects by Brian Ruf";
    homepage = "https://github.com/brian-ruf/ruf-common-python";
    license = lib.licenses.mit;
  };
}
```

`ruf_common/__init__.py` imports every submodule, so `pythonImportsCheck = [ "ruf_common" ]` transitively imports `elementpath`, `pytz`, `tzlocal`, `geopy`, `timezonefinder`, `aiohttp`, `requests` and `packaging`, catching any missing dependency. The PyPI sdist filename uses an underscore (`ruf_common-2.2.0.tar.gz`), so `fetchPypi.pname` is `ruf_common` while the derivation `pname` stays `ruf-common`.

- [ ] **Step 3: Create `overlays/default.nix`**

```nix
final: prev:
let
  python3 = prev.python3.override {
    packageOverrides = pf: pp: {
      oscal = pf.callPackage ../package/oscal { };
      ruf-common = pf.callPackage ../package/ruf-common { };
      jsonschema_rs = pp.jsonschema-rs;
    };
  };
in
{
  inherit python3;
  python3Packages = python3.pkgs;
}
```

`python3.override { packageOverrides = ... }` is the supported way to extend the interpreter's own package set, so that both `pkgs.python3Packages.oscal` and `pkgs.python3.withPackages (ps: [ ps.oscal ])` see the new packages. The alias `jsonschema_rs = pp.jsonschema-rs` maps the PyPI dist/import spelling to the existing nixpkgs `jsonschema-rs`.

- [ ] **Step 4: Replace `flake.nix`**

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
    let
      overlay = import ./overlays/default.nix;
    in
    (flake-utils.lib.eachSystem
      [
        "x86_64-linux"
        "aarch64-linux"
      ]
      (
        system:
        let
          pkgs = import nixpkgs {
            inherit system;
            overlays = [ overlay ];
          };
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
              oscal
              pypdf
              python-docx
            ];
            nativeCheckInputs = [
              py.pytestCheckHook
              py.jsonschema-rs
            ];
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
                ps.oscal
                ps.pypdf
                ps.python-docx
                ps.jsonschema-rs
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
      )
    )
    // {
      overlays.default = overlay;
    };
}
```

The `overlay` binding is defined once at the top level and applied per system, so `pkgs.python3Packages.oscal` and `pkgs.python3.withPackages` both see the new packages; `overlays.default` is then exposed as a proper top-level flake output via the final `// { ... }` (with `eachSystem`, an `overlays` attribute declared *inside* the per-system function would be nested under `overlays.<system>`, not top-level).

The dev shell still deliberately omits `self.packages.${system}.smeargle` (it runs `pytestCheckHook`); `shellHook` prepends `src/` to `PYTHONPATH` for `python -m smeargle` and `pyproject.toml` sets `pythonpath = ["src", "tests"]`. `jsonschema-rs` is added to `nativeCheckInputs` (tests import `jsonschema_rs` directly) and to the dev shell.

- [ ] **Step 5: Modify `pyproject.toml`**

Add `oscal`, `pypdf`, `python-docx` to `[project].dependencies` and `tests` to the pytest `pythonpath`:

```toml
dependencies = [
  "typer>=0.12",
  "pydantic>=2.6",
  "pydantic-settings>=2.2",
  "httpx>=0.27",
  "pyyaml>=6.0",
  "oscal==3.2.2",
  "pypdf>=6.0",
  "python-docx>=1.1",
]
```

```toml
[tool.pytest.ini_options]
pythonpath = ["src", "tests"]
testpaths = ["tests"]
```

Also add an explicit `E501` ignore so long SQL and test-literal lines do not fight the linter:

```toml
[tool.ruff.lint]
select = ["E", "F", "I"]
ignore = ["E501"]
```

- [ ] **Step 6: Modify `.gitignore`**

Append, under the Nix block:

```
# oscal support database written to CWD by unconfigured callers
/support/
```

- [ ] **Step 7: Build and import-check the new dependencies**

Run:

```bash
nix build .#smeargle
nix develop -c python -c "import oscal, ruf_common, pypdf, docx, jsonschema_rs; print('deps ok')"
```

Expected:

- `nix build .#smeargle` exits 0. The `oscal` and `ruf-common` derivations build (their `postInstall`/`pythonImportsCheck` pass) and Phase 1's tests still pass.
- `deps ok`.

- [ ] **Step 8: Commit**

```bash
git add flake.nix overlays/default.nix package/oscal/default.nix package/ruf-common/default.nix pyproject.toml .gitignore
git commit -m "chore(nix): package oscal and ruf-common via python overlay" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 2: Isolated `oscal` facade

**Files:**
- Create: `src/smeargle/oscal_build/__init__.py`
- Create: `src/smeargle/oscal_build/facade.py`
- Test: `tests/unit/oscal_build/test_facade.py`

**Spec traceability:** §4 (`oscal_build/facade.py` is the ONLY module that imports `oscal`; surface `validate(model, document)` plus small load/serialise helpers), §16 (isolate `oscal` API churn), §11.6 (validate every artifact).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/oscal_build/__init__.py` (empty) and `tests/unit/oscal_build/test_facade.py`:

```python
import json

import pytest

from smeargle.errors import CatalogError
from smeargle.oscal_build import facade


def _write_catalog(tmp_path, controls):
    document = {
        "catalog": {
            "uuid": "11111111-1111-4111-8111-111111111111",
            "metadata": {
                "title": "Test Catalog",
                "last-modified": "2026-01-01T00:00:00Z",
                "version": "1.0.0",
                "oscal-version": "1.2.3",
            },
            "controls": controls,
        }
    }
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path, document


@pytest.fixture(autouse=True)
def _support(tmp_path_factory):
    support = tmp_path_factory.mktemp("support") / "oscal_support.db"
    facade.configure_support_file(support)


def test_load_document_returns_plain_dict(tmp_path):
    path, document = _write_catalog(tmp_path, [{"id": "ac-1", "title": "Policy"}])
    assert facade.load_document(path) == document


def test_validate_accepts_valid_catalog():
    document = {
        "catalog": {
            "uuid": "11111111-1111-4111-8111-111111111111",
            "metadata": {
                "title": "T",
                "last-modified": "2026-01-01T00:00:00Z",
                "version": "1.0.0",
                "oscal-version": "1.2.3",
            },
        }
    }
    facade.validate("catalog", document)


def test_validate_rejects_invalid_catalog():
    document = {
        "catalog": {
            "uuid": "not-a-uuid",
            "metadata": {"title": "T"},
        }
    }
    with pytest.raises(CatalogError):
        facade.validate("catalog", document)


def test_serialise_json_round_trips():
    document = {
        "catalog": {
            "uuid": "11111111-1111-4111-8111-111111111111",
            "metadata": {
                "title": "T",
                "last-modified": "2026-01-01T00:00:00Z",
                "version": "1.0.0",
                "oscal-version": "1.2.3",
            },
        }
    }
    text = facade.serialise_json("catalog", document)
    assert json.loads(text)["catalog"]["metadata"]["oscal-version"] == "1.2.3"


def test_validate_wraps_raw_oscal_errors():
    document = {"catalog": {"unserialisable": object()}}
    with pytest.raises(CatalogError):
        facade.validate("catalog", document)


def test_serialise_wraps_raw_oscal_errors():
    document = {"catalog": {"unserialisable": object()}}
    with pytest.raises(CatalogError):
        facade.serialise_json("catalog", document)


def test_load_document_wraps_read_errors(tmp_path):
    with pytest.raises(CatalogError):
        facade.load_document(tmp_path / "missing.json")
```

- [ ] **Step 2: Run the test and see it fail**

Run: `nix develop -c pytest tests/unit/oscal_build/test_facade.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'smeargle.oscal_build'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/smeargle/oscal_build/__init__.py`:

```python
"""OSCAL construction and validation (spec 4)."""
```

Create `src/smeargle/oscal_build/facade.py`:

```python
"""The only module that imports `oscal`; a thin, typed boundary (spec 4, 16)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from oscal import OSCAL, Catalog, Profile
from oscal import Mapping as OscalMapping

from smeargle.errors import CatalogError

_MODELS = {
    "catalog": Catalog,
    "profile": Profile,
    "mapping-collection": OscalMapping,
}


def configure_support_file(path: Path) -> None:
    from oscal.oscal_support import configure_support

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    configure_support(support_file=str(path))


def _summary(instance: Any) -> str:
    status = getattr(instance, "validation_status", {}) or {}
    failed = ", ".join(name for name, ok in status.items() if ok is False)
    errors = getattr(instance, "validation_errors", []) or []
    detail = failed or "unknown phase"
    if errors:
        first = errors[0]
        detail = f"{detail}: {first.get('error-type')} at {first.get('location')}"
    return detail


def _safe_loads(cls: Any, content: Any, *, href: str | None = None) -> Any:
    try:
        return cls.loads(content, href=href)
    except CatalogError:
        raise
    except Exception as exc:
        raise CatalogError(f"could not parse OSCAL content: {exc}") from exc


def validate(model: str, document: Mapping[str, Any]) -> None:
    cls = _MODELS.get(model)
    if cls is None:
        raise CatalogError(f"unsupported OSCAL model '{model}'")
    instance = _safe_loads(cls, dict(document))
    if not instance.validate():
        raise CatalogError(f"invalid OSCAL {model}: {_summary(instance)}")


def load_document(path: Path) -> dict[str, Any]:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CatalogError(f"could not read OSCAL document '{path}': {exc}") from exc
    instance = _safe_loads(OSCAL, text, href=str(path))
    if not instance.is_valid:
        raise CatalogError(f"'{path}' is not valid OSCAL: {_summary(instance)}")
    return json.loads(instance.json)


def serialise_json(model: str, document: Mapping[str, Any]) -> str:
    cls = _MODELS.get(model)
    if cls is None:
        raise CatalogError(f"unsupported OSCAL model '{model}'")
    instance = _safe_loads(cls, dict(document))
    if not instance.is_valid:
        raise CatalogError(f"cannot serialise invalid OSCAL {model}: {_summary(instance)}")
    return instance.dumps(format="json", pretty_print=True)
```

`_safe_loads` funnels every `OSCAL.loads` / model-class `loads` call through one boundary so malformed or non-serialisable input surfaces as a project `CatalogError`, never a raw `oscal`/`json` exception. `load_document` likewise converts filesystem/encoding failures.

`load_document` parses JSON/XML/YAML uniformly by handing the raw text to `OSCAL.loads`, then re-emits canonical JSON and parses it back to a plain dict (the spec requires artifacts be built as plain dicts outside the facade). `configure_support_file` redirects the shared OSCAL support database so callers never write `./support/`.

Scratch validation against the pinned `oscal` 3.2.2 confirmed that `OSCAL.loads(document).json` reproduces the input document exactly (the library injects no default/empty fields for a minimal catalog), so the exact-equality assertion in `test_load_document_returns_plain_dict` is safe on this version; if a future `oscal` release changes that, relax the assertion to a structural subset of `document["catalog"]`.

- [ ] **Step 4: Run the test and see it pass**

Run: `nix develop -c pytest tests/unit/oscal_build/test_facade.py -v`
Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/smeargle/oscal_build/__init__.py src/smeargle/oscal_build/facade.py tests/unit/oscal_build/__init__.py tests/unit/oscal_build/test_facade.py
git commit -m "feat(oscal): add isolated oscal facade" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 3: Vendored OSCAL 1.2.3 JSON Schemas and offline validator

**Files:**
- Create: `tests/schemas/oscal-1.2.3/oscal_catalog_schema.json`
- Create: `tests/schemas/oscal-1.2.3/oscal_profile_schema.json`
- Create: `tests/schemas/oscal-1.2.3/oscal_mapping_schema.json`
- Create: `tests/support/__init__.py`
- Create: `tests/support/schemas.py`
- Create: `tests/conftest.py`
- Test: `tests/unit/test_schema_hashes.py`

**Spec traceability:** §4 (`tests/schemas/oscal-1.2.3/`), §14 (every artifact validated against the vendored official JSON Schemas as a second opinion), §16 (metaschema vs JSON Schema).

- [ ] **Step 1: Vendor the pinned official schemas**

Create the directory and download the three self-contained v1.2.3 release schemas, then verify the pinned sha256 values:

```bash
mkdir -p tests/schemas/oscal-1.2.3
base="https://github.com/usnistgov/OSCAL/releases/download/v1.2.3"
curl -sSL "$base/oscal_catalog_schema.json" -o tests/schemas/oscal-1.2.3/oscal_catalog_schema.json
curl -sSL "$base/oscal_profile_schema.json" -o tests/schemas/oscal-1.2.3/oscal_profile_schema.json
curl -sSL "$base/oscal_mapping_schema.json" -o tests/schemas/oscal-1.2.3/oscal_mapping_schema.json
sha256sum tests/schemas/oscal-1.2.3/*.json
```

Expected (exact):

```
ab95836e9e8dfeb6fde80007f6cc76fa3192f595d427c751a3f3923c3f474fc2  tests/schemas/oscal-1.2.3/oscal_catalog_schema.json
ed28b68c8e56cc7d39f0c6076a5d7da3e8100fbe25abf5bb731120bd34f8817e  tests/schemas/oscal-1.2.3/oscal_mapping_schema.json
7c5ff5a92683b6a80ce6a3474dea04e0ea8680a4ecb60702ffa08ebfc677e6cb  tests/schemas/oscal-1.2.3/oscal_profile_schema.json
```

These official schemas are self-contained (no external `$ref`), so they can be used fully offline.

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_schema_hashes.py`:

```python
import hashlib

from support.schemas import SCHEMA_DIR

EXPECTED = {
    "oscal_catalog_schema.json": "ab95836e9e8dfeb6fde80007f6cc76fa3192f595d427c751a3f3923c3f474fc2",
    "oscal_profile_schema.json": "7c5ff5a92683b6a80ce6a3474dea04e0ea8680a4ecb60702ffa08ebfc677e6cb",
    "oscal_mapping_schema.json": "ed28b68c8e56cc7d39f0c6076a5d7da3e8100fbe25abf5bb731120bd34f8817e",
}


def test_vendored_schemas_are_hash_pinned():
    for name, digest in EXPECTED.items():
        data = (SCHEMA_DIR / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest, name
```

- [ ] **Step 3: Write the offline validation helper and conftest**

Create `tests/support/__init__.py`:

```python
"""Test-only support helpers."""
```

Create `tests/support/schemas.py`:

```python
"""Offline OSCAL JSON Schema validation via jsonschema-rs (spec 14)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import jsonschema_rs

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas" / "oscal-1.2.3"

SCHEMA_FILES = {
    "catalog": "oscal_catalog_schema.json",
    "profile": "oscal_profile_schema.json",
    "mapping-collection": "oscal_mapping_schema.json",
}


@lru_cache(maxsize=None)
def _validator(model: str) -> jsonschema_rs.Draft7Validator:
    schema = json.loads((SCHEMA_DIR / SCHEMA_FILES[model]).read_text(encoding="utf-8"))
    return jsonschema_rs.Draft7Validator(schema)


def validate_against_schema(model: str, document: Mapping[str, Any]) -> None:
    """Raise jsonschema_rs.ValidationError when document fails the vendored schema."""
    _validator(model).validate(dict(document))
```

`jsonschema-rs` is used rather than pure-Python `jsonschema` because the official OSCAL schemas use ECMA-262 Unicode property classes (`\p{L}`) that Python's `re` cannot compile.

Create `tests/conftest.py`:

```python
"""Shared fixtures for the smeargle test suite."""

from __future__ import annotations

import pytest

from smeargle.oscal_build import facade


@pytest.fixture(scope="session", autouse=True)
def _oscal_support(tmp_path_factory):
    support = tmp_path_factory.mktemp("oscal-support") / "oscal_support.db"
    facade.configure_support_file(support)
```

- [ ] **Step 4: Run the test and see it pass**

Run: `nix develop -c pytest tests/unit/test_schema_hashes.py -v`
Expected: `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add tests/schemas tests/support tests/conftest.py tests/unit/test_schema_hashes.py
git commit -m "test(oscal): vendor 1.2.3 json schemas with offline validator" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 4: SQLite connection, pragmas, and schema migrations

**Files:**
- Modify: `src/smeargle/errors.py`
- Create: `src/smeargle/store/__init__.py`
- Create: `src/smeargle/store/db.py`
- Create: `src/smeargle/store/schema.py`
- Test: `tests/unit/store/test_schema.py`

**Spec traceability:** §7 (one SQLite file per `--state-dir`; WAL/NORMAL/foreign_keys/busy_timeout pragmas; `PRAGMA user_version` migrations; refuse a database newer than the binary), §15 (typed errors).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/store/__init__.py` (empty) and `tests/unit/store/test_schema.py`:

```python
import pytest

from smeargle.errors import StoreError
from smeargle.store import db, schema


def test_connect_sets_pragmas(tmp_path):
    conn = db.connect(tmp_path)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    conn.close()


def test_migrate_sets_user_version_and_is_idempotent(tmp_path):
    conn = db.connect(tmp_path)
    schema.migrate(conn)
    assert schema.current_version(conn) == schema.SCHEMA_VERSION
    schema.migrate(conn)
    assert schema.current_version(conn) == schema.SCHEMA_VERSION
    names = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {
        "runs",
        "documents",
        "requirements",
        "catalogs",
        "controls",
        "domain_index",
        "candidate_pairs",
        "mappings",
        "attempts",
        "evidence",
        "stage_runs",
    } <= names
    conn.close()


def test_migrate_refuses_newer_database(tmp_path):
    conn = db.connect(tmp_path)
    conn.execute("PRAGMA user_version = 999")
    conn.commit()
    with pytest.raises(StoreError):
        schema.migrate(conn)
    conn.close()


def test_transaction_rolls_back_on_error(tmp_path):
    conn = db.connect(tmp_path)
    schema.migrate(conn)
    conn.execute(
        "INSERT INTO runs (run_id, fingerprint, config_hash, status, oscal_version, created_at, updated_at)"
        " VALUES ('r', 'f', 'c', 'started', '1.2.3', 't', 't')"
    )
    conn.commit()
    with pytest.raises(ValueError):
        with db.transaction(conn):
            conn.execute("UPDATE runs SET status='changed' WHERE run_id='r'")
            raise ValueError("boom")
    status = conn.execute("SELECT status FROM runs WHERE run_id='r'").fetchone()[0]
    assert status == "started"
    conn.close()
```

- [ ] **Step 2: Run the test and see it fail**

Run: `nix develop -c pytest tests/unit/store/test_schema.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'smeargle.store'`.

- [ ] **Step 3: Write the minimal implementation**

Modify `src/smeargle/errors.py`: add `StoreError` after `AbortedError`:

```python
class StoreError(SmeargleError):
    exit_code = EXIT_UNEXPECTED
```

Create `src/smeargle/store/__init__.py`:

```python
"""SQLite run store: connection, schema, and typed repository (spec 7)."""
```

Create `src/smeargle/store/db.py`:

```python
"""SQLite connection, pragmas, and transaction handling (spec 7)."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DB_FILENAME = "smeargle.db"
PRAGMAS = (
    "journal_mode=WAL",
    "synchronous=NORMAL",
    "foreign_keys=ON",
    "busy_timeout=5000",
)


def connect(state_dir: Path) -> sqlite3.Connection:
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(state_dir / DB_FILENAME)
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None
    for pragma in PRAGMAS:
        conn.execute(f"PRAGMA {pragma}")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
```

Create `src/smeargle/store/schema.py`:

```python
"""Schema DDL and `PRAGMA user_version` migrations (spec 7)."""

from __future__ import annotations

import sqlite3

from smeargle.errors import StoreError

SCHEMA_VERSION = 1

MIGRATION_1 = """
CREATE TABLE runs (
    run_id        TEXT PRIMARY KEY,
    fingerprint   TEXT NOT NULL,
    config_hash   TEXT NOT NULL,
    status        TEXT NOT NULL,
    oscal_version TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    finished_at   TEXT
);
CREATE INDEX idx_runs_fingerprint ON runs (fingerprint, created_at DESC);

CREATE TABLE documents (
    run_id         TEXT NOT NULL,
    doc_id         TEXT NOT NULL,
    ordinal        INTEGER NOT NULL,
    path           TEXT NOT NULL,
    uri            TEXT NOT NULL,
    external_id    TEXT,
    media_type     TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    size_bytes     INTEGER NOT NULL,
    status         TEXT NOT NULL,
    error          TEXT,
    loaded_at      TEXT NOT NULL,
    PRIMARY KEY (run_id, doc_id),
    UNIQUE (run_id, content_sha256),
    UNIQUE (run_id, ordinal),
    FOREIGN KEY (run_id) REFERENCES runs (run_id)
);

CREATE TABLE requirements (
    run_id          TEXT NOT NULL,
    req_id          TEXT NOT NULL,
    doc_id          TEXT NOT NULL,
    ordinal         INTEGER NOT NULL,
    text            TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    keyword         TEXT,
    extract_status  TEXT NOT NULL,
    gate_status     TEXT,
    gate_noul_prob  REAL,
    gate_choice     TEXT,
    retrieve_status TEXT,
    PRIMARY KEY (run_id, req_id),
    UNIQUE (run_id, doc_id, normalized_text),
    FOREIGN KEY (run_id) REFERENCES runs (run_id)
);

CREATE TABLE catalogs (
    run_id         TEXT NOT NULL,
    catalog_id     TEXT NOT NULL,
    ordinal        INTEGER NOT NULL,
    uri            TEXT NOT NULL,
    path           TEXT NOT NULL,
    external_id    TEXT,
    content_sha256 TEXT NOT NULL,
    oscal_version  TEXT,
    status         TEXT NOT NULL,
    PRIMARY KEY (run_id, catalog_id),
    FOREIGN KEY (run_id) REFERENCES runs (run_id)
);

CREATE TABLE controls (
    run_id     TEXT NOT NULL,
    catalog_id TEXT NOT NULL,
    control_id TEXT NOT NULL,
    title      TEXT NOT NULL,
    text       TEXT NOT NULL,
    domain     TEXT NOT NULL,
    family     TEXT NOT NULL,
    path       TEXT NOT NULL,
    PRIMARY KEY (run_id, catalog_id, control_id),
    FOREIGN KEY (run_id, catalog_id) REFERENCES catalogs (run_id, catalog_id)
);

CREATE TABLE domain_index (
    index_id       TEXT PRIMARY KEY,
    content_sha256 TEXT NOT NULL,
    model_id       TEXT NOT NULL,
    prompt_hash    TEXT NOT NULL,
    index_json     TEXT NOT NULL,
    UNIQUE (content_sha256, model_id, prompt_hash)
);

CREATE TABLE candidate_pairs (
    run_id                TEXT NOT NULL,
    pair_id               TEXT NOT NULL,
    req_id                TEXT NOT NULL,
    catalog_id            TEXT NOT NULL,
    control_id            TEXT NOT NULL,
    verify_status         TEXT NOT NULL,
    noul_prob             REAL,
    mapped_threshold      REAL,
    classify_status       TEXT,
    relation              TEXT,
    confidence_percentage REAL,
    confidence_category   TEXT,
    PRIMARY KEY (run_id, pair_id),
    UNIQUE (run_id, req_id, catalog_id, control_id),
    FOREIGN KEY (run_id) REFERENCES runs (run_id)
);

CREATE TABLE mappings (
    run_id                TEXT NOT NULL,
    map_uuid              TEXT NOT NULL,
    req_id                TEXT NOT NULL,
    catalog_id            TEXT NOT NULL,
    control_id            TEXT NOT NULL,
    relation              TEXT NOT NULL,
    confidence_percentage REAL,
    confidence_category   TEXT,
    rationale             TEXT,
    PRIMARY KEY (run_id, map_uuid),
    UNIQUE (run_id, req_id, catalog_id, control_id),
    FOREIGN KEY (run_id) REFERENCES runs (run_id)
);

CREATE TABLE attempts (
    attempt_id  TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL,
    stage       TEXT NOT NULL,
    item_ref    TEXT NOT NULL,
    call_type   TEXT NOT NULL,
    attempt_no  INTEGER NOT NULL,
    http_status INTEGER,
    error_class TEXT,
    error       TEXT,
    duration_ms INTEGER,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs (run_id)
);

CREATE TABLE evidence (
    evidence_id    TEXT PRIMARY KEY,
    run_id         TEXT NOT NULL,
    stage          TEXT NOT NULL,
    item_ref       TEXT NOT NULL,
    call_type      TEXT NOT NULL,
    request_json   BLOB,
    response_json  BLOB,
    request_sha256 TEXT NOT NULL,
    http_status    INTEGER,
    attempt_no     INTEGER,
    prompt_hash    TEXT,
    created_at     TEXT NOT NULL,
    UNIQUE (run_id, item_ref, call_type, request_sha256),
    FOREIGN KEY (run_id) REFERENCES runs (run_id)
);

CREATE TABLE stage_runs (
    run_id      TEXT NOT NULL,
    stage       TEXT NOT NULL,
    status      TEXT NOT NULL,
    cursor      TEXT,
    started_at  TEXT,
    finished_at TEXT,
    error       TEXT,
    PRIMARY KEY (run_id, stage),
    FOREIGN KEY (run_id) REFERENCES runs (run_id)
);
"""

MIGRATIONS: tuple[str, ...] = (MIGRATION_1,)


def current_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def migrate(conn: sqlite3.Connection) -> None:
    version = current_version(conn)
    if version > SCHEMA_VERSION:
        raise StoreError(
            f"database schema version {version} is newer than supported {SCHEMA_VERSION}"
        )
    for target, script in enumerate(MIGRATIONS[version:], start=version + 1):
        conn.executescript(script)
        conn.execute(f"PRAGMA user_version = {int(target)}")
```

- [ ] **Step 4: Run the test and see it pass**

Run: `nix develop -c pytest tests/unit/store/test_schema.py -v`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/smeargle/errors.py src/smeargle/store/__init__.py src/smeargle/store/db.py src/smeargle/store/schema.py tests/unit/store/__init__.py tests/unit/store/test_schema.py
git commit -m "feat(store): add sqlite connection and schema migrations" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 5: `RunStore` runs, stages, and documents

**Files:**
- Create: `src/smeargle/store/run_store.py`
- Test: `tests/unit/store/test_run_store.py`

**Spec traceability:** §7 (`runs`, `documents`, `stage_runs`; run-scoped composite PKs; `stage_runs.status='complete'` short-circuits; work is derived, never a mutable ledger), §5 (`Document`), §12.1 (`--run-id`, fingerprint/config_hash).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/store/test_run_store.py`:

```python
from datetime import datetime, timezone

import pytest

from smeargle.domain.clock import FrozenClock
from smeargle.domain.documents import Document
from smeargle.domain.ids import UuidIdFactory
from smeargle.store import run_store as rs


@pytest.fixture
def store(tmp_path):
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    with rs.RunStore.open(tmp_path, clock=clock, id_factory=UuidIdFactory()) as opened:
        yield opened


def test_create_and_read_run(store):
    store.create_run("run-1", "fp", "cfg")
    row = store.get_run("run-1")
    assert row["fingerprint"] == "fp"
    assert row["status"] == "started"
    assert store.find_runs_by_fingerprint("fp")[0]["run_id"] == "run-1"


def test_set_run_status_marks_finished_at(store):
    store.create_run("run-1", "fp", "cfg")
    store.set_run_status("run-1", "ingested", finished=True)
    row = store.get_run("run-1")
    assert row["status"] == "ingested"
    assert row["finished_at"] is not None


def test_stage_lifecycle(store):
    store.create_run("run-1", "fp", "cfg")
    store.start_stage("run-1", "load")
    assert store.get_stage("run-1", "load")["status"] == "running"
    store.complete_stage("run-1", "load")
    assert store.get_stage("run-1", "load")["status"] == "complete"
    store.start_stage("run-1", "load")
    assert store.get_stage("run-1", "load")["status"] == "running"


def test_add_and_list_documents(store):
    store.create_run("run-1", "fp", "cfg")
    doc = Document(
        run_id="run-1",
        doc_id="d1",
        ordinal=0,
        path="/x/a.txt",
        uri="file:///x/a.txt",
        external_id=None,
        media_type="text/plain",
        content_sha256="d1",
        size_bytes=10,
        text="hello",
    )
    store.add_document(doc)
    assert store.document_content_exists("run-1", "d1")
    assert not store.document_content_exists("run-1", "other")
    rows = store.list_documents("run-1")
    assert [row["doc_id"] for row in rows] == ["d1"]
    assert rows[0]["path"] == "/x/a.txt"


def test_document_content_is_unique_per_run(store):
    store.create_run("run-1", "fp", "cfg")
    doc = Document("run-1", "d1", 0, "a", "u", None, "text/plain", "d1", 1, "x")
    store.add_document(doc)
    duplicate = Document("run-1", "d1", 1, "b", "u2", None, "text/plain", "d1", 1, "x")
    with pytest.raises(Exception):
        store.add_document(duplicate)
```

- [ ] **Step 2: Run the test and see it fail**

Run: `nix develop -c pytest tests/unit/store/test_run_store.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'smeargle.store.run_store'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/smeargle/store/run_store.py`:

```python
"""Typed repository over the SQLite run store (spec 7)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from smeargle.domain.clock import Clock, SystemClock
from smeargle.domain.documents import Document
from smeargle.domain.ids import IdFactory, UuidIdFactory
from smeargle.store import db as db_module
from smeargle.store.schema import migrate


class RunStore:
    def __init__(self, conn, clock: Optional[Clock] = None, id_factory: Optional[IdFactory] = None):
        self._conn = conn
        self._clock = clock or SystemClock()
        self._ids = id_factory or UuidIdFactory()

    @classmethod
    def open(
        cls,
        state_dir: Path,
        *,
        clock: Optional[Clock] = None,
        id_factory: Optional[IdFactory] = None,
    ) -> "RunStore":
        conn = db_module.connect(state_dir)
        migrate(conn)
        return cls(conn, clock=clock, id_factory=id_factory)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "RunStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def transaction(self):
        return db_module.transaction(self._conn)

    def _now(self) -> str:
        return self._clock.now_utc().isoformat()

    # -- runs ---------------------------------------------------------------
    def create_run(
        self,
        run_id: str,
        fingerprint: str,
        config_hash: str,
        *,
        oscal_version: str = "1.2.3",
        status: str = "started",
    ) -> None:
        now = self._now()
        self._conn.execute(
            "INSERT INTO runs (run_id, fingerprint, config_hash, status, oscal_version,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, fingerprint, config_hash, status, oscal_version, now, now),
        )

    def get_run(self, run_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def list_runs(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM runs ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]

    def find_runs_by_fingerprint(self, fingerprint: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM runs WHERE fingerprint = ? ORDER BY created_at DESC",
            (fingerprint,),
        ).fetchall()
        return [dict(row) for row in rows]

    def set_run_status(self, run_id: str, status: str, *, finished: bool = False) -> None:
        now = self._now()
        if finished:
            self._conn.execute(
                "UPDATE runs SET status = ?, updated_at = ?, finished_at = ? WHERE run_id = ?",
                (status, now, now, run_id),
            )
        else:
            self._conn.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE run_id = ?",
                (status, now, run_id),
            )

    # -- stage_runs ---------------------------------------------------------
    def start_stage(self, run_id: str, stage: str) -> None:
        self._conn.execute(
            "INSERT INTO stage_runs (run_id, stage, status, started_at)"
            " VALUES (?, ?, 'running', ?)"
            " ON CONFLICT (run_id, stage) DO UPDATE SET status = 'running',"
            " started_at = excluded.started_at, finished_at = NULL, error = NULL",
            (run_id, stage, self._now()),
        )

    def complete_stage(self, run_id: str, stage: str) -> None:
        self._conn.execute(
            "UPDATE stage_runs SET status = 'complete', finished_at = ?"
            " WHERE run_id = ? AND stage = ?",
            (self._now(), run_id, stage),
        )

    def fail_stage(self, run_id: str, stage: str, error: str) -> None:
        self._conn.execute(
            "UPDATE stage_runs SET status = 'failed', finished_at = ?, error = ?"
            " WHERE run_id = ? AND stage = ?",
            (self._now(), error, run_id, stage),
        )

    def get_stage(self, run_id: str, stage: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM stage_runs WHERE run_id = ? AND stage = ?", (run_id, stage)
        ).fetchone()
        return dict(row) if row else None

    # -- documents ----------------------------------------------------------
    def add_document(
        self, document: Document, *, status: str = "loaded", error: Optional[str] = None
    ) -> None:
        self._conn.execute(
            "INSERT INTO documents (run_id, doc_id, ordinal, path, uri, external_id,"
            " media_type, content_sha256, size_bytes, status, error, loaded_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                document.run_id,
                document.doc_id,
                document.ordinal,
                document.path,
                document.uri,
                document.external_id,
                document.media_type,
                document.content_sha256,
                document.size_bytes,
                status,
                error,
                self._now(),
            ),
        )

    def document_content_exists(self, run_id: str, content_sha256: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM documents WHERE run_id = ? AND content_sha256 = ?",
            (run_id, content_sha256),
        ).fetchone()
        return row is not None

    def list_documents(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM documents WHERE run_id = ? ORDER BY ordinal", (run_id,)
        ).fetchall()
        return [dict(row) for row in rows]
```

- [ ] **Step 4: Run the test and see it pass**

Run: `nix develop -c pytest tests/unit/store/test_run_store.py -v`
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/smeargle/store/run_store.py tests/unit/store/test_run_store.py
git commit -m "feat(store): add run, stage, and document repository methods" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 6: `RunStore` catalogs, controls, requirements, and work derivation

**Files:**
- Modify: `src/smeargle/store/run_store.py`
- Test: `tests/unit/store/test_run_store.py`

**Spec traceability:** §7 (`catalogs`, `controls`, `requirements`; work derived via `IS NULL` predicates; `retrieve_status ∈ {nominated, none}` terminal marker), §5 (`Control`, `Requirement`), §10 Stage 2/3.

- [ ] **Step 1: Write the failing test**

Modify the top-of-file import block in `tests/unit/store/test_run_store.py` to:

```python
from datetime import datetime, timezone

import pytest

from smeargle.domain.clock import FrozenClock
from smeargle.domain.controls import Control
from smeargle.domain.documents import Document
from smeargle.domain.ids import UuidIdFactory
from smeargle.domain.requirements import Keyword, Requirement
from smeargle.store import run_store as rs
from smeargle.store.run_store import CatalogRow
```

Then append these tests to the end of the file (the appended block contains **no import statements**, so ruff E402 cannot fire):

```python
def _catalog(store, catalog_id="cat-1"):
    store.create_run("run-1", "fp", "cfg")
    store.add_catalog(
        CatalogRow(
            run_id="run-1",
            catalog_id=catalog_id,
            ordinal=0,
            uri="file:///c.json",
            path="/c.json",
            external_id=None,
            content_sha256=catalog_id,
            oscal_version="1.2.3",
            status="loaded",
        )
    )


def test_add_and_list_controls(store):
    _catalog(store)
    store.add_control(
        Control("run-1", "cat-1", "ac-1", "Policy", "text", "ac", "Access", ("ac",))
    )
    controls = store.list_controls("run-1", "cat-1")
    assert controls[0].control_id == "ac-1"
    assert controls[0].path == ("ac",)
    assert store.list_catalogs("run-1")[0]["catalog_id"] == "cat-1"


def _requirement(req_id, *, gate=None, retrieve=None):
    text = f"The system MUST satisfy {req_id}"
    return Requirement(
        run_id="run-1",
        req_id=req_id,
        doc_id="d1",
        ordinal=0,
        text=text,
        normalized_text=text,
        keyword=Keyword.MUST,
        extract_status="proposed",
        gate_status=gate,
        gate_noul_prob=None,
        gate_choice=None,
        retrieve_status=retrieve,
    )


def test_work_is_derived_with_is_null_predicates(store):
    store.create_run("run-1", "fp", "cfg")
    store.add_requirement(_requirement("req-a"))
    store.add_requirement(_requirement("req-b", gate="passed"))
    store.add_requirement(_requirement("req-c", gate="passed", retrieve="none"))
    store.add_requirement(_requirement("req-d", gate="rejected"))

    gate_work = {r.req_id for r in store.requirements_for_gate("run-1")}
    assert gate_work == {"req-a"}

    retrieval_work = {r.req_id for r in store.requirements_for_retrieval("run-1")}
    assert retrieval_work == {"req-b"}


def test_set_requirement_gate_and_retrieve(store):
    store.create_run("run-1", "fp", "cfg")
    store.add_requirement(_requirement("req-a"))
    store.set_requirement_gate(
        "run-1",
        "req-a",
        gate_status="passed",
        gate_noul_prob=0.9,
        gate_choice="MUST",
        keyword="MUST",
        extract_status="proposed",
    )
    assert {r.req_id for r in store.requirements_for_gate("run-1")} == set()
    assert {r.req_id for r in store.requirements_for_retrieval("run-1")} == {"req-a"}
    store.set_requirement_retrieve_status("run-1", "req-a", "none")
    assert {r.req_id for r in store.requirements_for_retrieval("run-1")} == set()


def test_retrieve_status_terminal_markers(store):
    store.create_run("run-1", "fp", "cfg")
    store.add_requirement(_requirement("req-a", gate="passed"))
    store.add_requirement(_requirement("req-b", gate="passed"))
    store.set_requirement_retrieve_status("run-1", "req-a", "nominated")
    store.set_requirement_retrieve_status("run-1", "req-b", "none")
    assert {r.req_id for r in store.requirements_for_retrieval("run-1")} == set()
    assert store.get_requirement("run-1", "req-a")["retrieve_status"] == "nominated"
    assert store.get_requirement("run-1", "req-b")["retrieve_status"] == "none"
```

- [ ] **Step 2: Run the test and see it fail**

Run: `nix develop -c pytest tests/unit/store/test_run_store.py -v`
Expected: FAIL — `ImportError: cannot import name 'CatalogRow' from 'smeargle.store.run_store'`.

- [ ] **Step 3: Write the minimal implementation**

Add the following to `src/smeargle/store/run_store.py`. The final import block must be exactly:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from smeargle.domain.clock import Clock, SystemClock
from smeargle.domain.controls import Control
from smeargle.domain.documents import Document
from smeargle.domain.ids import IdFactory, UuidIdFactory
from smeargle.domain.requirements import Keyword, Requirement
from smeargle.store import db as db_module
from smeargle.store.schema import migrate
```

Add the `CatalogRow` dataclass and the row converter after the imports and before `class RunStore`:

```python
@dataclass(frozen=True, slots=True)
class CatalogRow:
    run_id: str
    catalog_id: str
    ordinal: int
    uri: str
    path: str
    external_id: Optional[str]
    content_sha256: str
    oscal_version: Optional[str]
    status: str


def _requirement_from_row(row) -> Requirement:
    keyword = row["keyword"]
    return Requirement(
        run_id=row["run_id"],
        req_id=row["req_id"],
        doc_id=row["doc_id"],
        ordinal=row["ordinal"],
        text=row["text"],
        normalized_text=row["normalized_text"],
        keyword=Keyword(keyword) if keyword is not None else None,
        extract_status=row["extract_status"],
        gate_status=row["gate_status"],
        gate_noul_prob=row["gate_noul_prob"],
        gate_choice=row["gate_choice"],
        retrieve_status=row["retrieve_status"],
    )
```

Add these methods inside `class RunStore` (after the document methods):

```python
    # -- catalogs and controls ---------------------------------------------
    def add_catalog(self, catalog: CatalogRow) -> None:
        self._conn.execute(
            "INSERT INTO catalogs (run_id, catalog_id, ordinal, uri, path, external_id,"
            " content_sha256, oscal_version, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                catalog.run_id,
                catalog.catalog_id,
                catalog.ordinal,
                catalog.uri,
                catalog.path,
                catalog.external_id,
                catalog.content_sha256,
                catalog.oscal_version,
                catalog.status,
            ),
        )

    def list_catalogs(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM catalogs WHERE run_id = ? ORDER BY ordinal", (run_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    def add_control(self, control: Control) -> None:
        self._conn.execute(
            "INSERT INTO controls (run_id, catalog_id, control_id, title, text, domain,"
            " family, path) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                control.run_id,
                control.catalog_id,
                control.control_id,
                control.title,
                control.text,
                control.domain,
                control.family,
                json.dumps(list(control.path)),
            ),
        )

    def add_controls(self, controls: Iterable[Control]) -> None:
        for control in controls:
            self.add_control(control)

    def list_controls(self, run_id: str, catalog_id: Optional[str] = None) -> list[Control]:
        if catalog_id is None:
            rows = self._conn.execute(
                "SELECT * FROM controls WHERE run_id = ? ORDER BY catalog_id, control_id",
                (run_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM controls WHERE run_id = ? AND catalog_id = ?"
                " ORDER BY control_id",
                (run_id, catalog_id),
            ).fetchall()
        return [
            Control(
                run_id=row["run_id"],
                catalog_id=row["catalog_id"],
                control_id=row["control_id"],
                title=row["title"],
                text=row["text"],
                domain=row["domain"],
                family=row["family"],
                path=tuple(json.loads(row["path"])),
            )
            for row in rows
        ]

    # -- requirements -------------------------------------------------------
    def add_requirement(self, requirement: Requirement) -> None:
        self._conn.execute(
            "INSERT INTO requirements (run_id, req_id, doc_id, ordinal, text,"
            " normalized_text, keyword, extract_status, gate_status, gate_noul_prob,"
            " gate_choice, retrieve_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                requirement.run_id,
                requirement.req_id,
                requirement.doc_id,
                requirement.ordinal,
                requirement.text,
                requirement.normalized_text,
                requirement.keyword.value if requirement.keyword else None,
                requirement.extract_status,
                requirement.gate_status,
                requirement.gate_noul_prob,
                requirement.gate_choice,
                requirement.retrieve_status,
            ),
        )

    def set_requirement_gate(
        self,
        run_id: str,
        req_id: str,
        *,
        gate_status: str,
        gate_noul_prob: Optional[float],
        gate_choice: Optional[str],
        keyword: Optional[str],
        extract_status: str,
    ) -> None:
        self._conn.execute(
            "UPDATE requirements SET extract_status = ?, gate_status = ?,"
            " gate_noul_prob = ?, gate_choice = ?, keyword = ?"
            " WHERE run_id = ? AND req_id = ?",
            (extract_status, gate_status, gate_noul_prob, gate_choice, keyword, run_id, req_id),
        )

    def set_requirement_retrieve_status(
        self, run_id: str, req_id: str, retrieve_status: str
    ) -> None:
        self._conn.execute(
            "UPDATE requirements SET retrieve_status = ? WHERE run_id = ? AND req_id = ?",
            (retrieve_status, run_id, req_id),
        )

    def get_requirement(self, run_id: str, req_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM requirements WHERE run_id = ? AND req_id = ?", (run_id, req_id)
        ).fetchone()
        return dict(row) if row else None

    def requirements_for_gate(self, run_id: str) -> list[Requirement]:
        rows = self._conn.execute(
            "SELECT * FROM requirements WHERE run_id = ? AND gate_status IS NULL"
            " ORDER BY req_id",
            (run_id,),
        ).fetchall()
        return [_requirement_from_row(row) for row in rows]

    def requirements_for_retrieval(self, run_id: str) -> list[Requirement]:
        rows = self._conn.execute(
            "SELECT * FROM requirements WHERE run_id = ? AND gate_status = 'passed'"
            " AND retrieve_status IS NULL ORDER BY req_id",
            (run_id,),
        ).fetchall()
        return [_requirement_from_row(row) for row in rows]
```

- [ ] **Step 4: Run the test and see it pass**

Run: `nix develop -c pytest tests/unit/store/test_run_store.py -v`
Expected: `9 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/smeargle/store/run_store.py tests/unit/store/test_run_store.py
git commit -m "feat(store): add catalog, control, and requirement repository methods" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 7: `RunStore` candidates, mappings, evidence, and attempts

**Files:**
- Modify: `src/smeargle/store/run_store.py`
- Test: `tests/unit/store/test_run_store.py`

**Spec traceability:** §7 (candidates persisted pre-gate; `verify_status='pending'` then terminal `passed`/`rejected`; `classify_status` terminal; evidence at-least-once with compressed + redacted payloads; `attempts`), §10 Stages 3–5, §11.5.

- [ ] **Step 1: Write the failing test**

Modify the top-of-file import block in `tests/unit/store/test_run_store.py` to:

```python
import json
import zlib
from datetime import datetime, timezone

import pytest

from smeargle.domain.clock import FrozenClock
from smeargle.domain.controls import Control, DomainIndex
from smeargle.domain.documents import Document
from smeargle.domain.ids import UuidIdFactory
from smeargle.domain.mapping import CandidatePair, MappingRecord, Relationship
from smeargle.domain.requirements import Keyword, Requirement
from smeargle.store import run_store as rs
from smeargle.store.run_store import CatalogRow
```

Then append these tests to the end of the file (no imports in the appended block):

```python
def test_candidates_persisted_pre_gate_and_work_queries(store):
    store.create_run("run-1", "fp", "cfg")
    store.add_candidate_pair(
        CandidatePair("run-1", "pair-a", "req-a", "cat-1", "ac-1", "pending", None)
    )
    store.add_candidate_pair(
        CandidatePair("run-1", "pair-b", "req-a", "cat-1", "ac-2", "passed", 0.9)
    )
    pending = {p.pair_id for p in store.candidate_pairs_for_verify("run-1")}
    assert pending == {"pair-a"}
    classify = {p.pair_id for p in store.candidate_pairs_for_classify("run-1")}
    assert classify == {"pair-b"}
    store.set_pair_verify("run-1", "pair-a", verify_status="rejected", noul_prob=0.1)
    assert {p.pair_id for p in store.candidate_pairs_for_verify("run-1")} == set()


def test_set_pair_classify_terminal(store):
    store.create_run("run-1", "fp", "cfg")
    store.add_candidate_pair(
        CandidatePair("run-1", "pair-b", "req-a", "cat-1", "ac-2", "passed", 0.9)
    )
    store.set_pair_classify(
        "run-1",
        "pair-b",
        classify_status="done",
        relation="subset-of",
        confidence_percentage=0.8,
        confidence_category="high",
    )
    pair = store.get_candidate_pair("run-1", "pair-b")
    assert pair["classify_status"] == "done"
    assert pair["relation"] == "subset-of"


def test_classify_status_terminal_unmapped_and_skipped(store):
    store.create_run("run-1", "fp", "cfg")
    store.add_candidate_pair(
        CandidatePair("run-1", "pair-u", "req-a", "cat-1", "ac-1", "passed", 0.9)
    )
    store.add_candidate_pair(
        CandidatePair("run-1", "pair-s", "req-a", "cat-1", "ac-2", "passed", 0.9)
    )
    store.set_pair_classify("run-1", "pair-u", classify_status="unmapped")
    store.set_pair_classify("run-1", "pair-s", classify_status="skipped")
    assert store.get_candidate_pair("run-1", "pair-u")["classify_status"] == "unmapped"
    assert store.get_candidate_pair("run-1", "pair-s")["classify_status"] == "skipped"
    assert {p.pair_id for p in store.candidate_pairs_for_classify("run-1")} == set()


def test_add_mapping(store):
    store.create_run("run-1", "fp", "cfg")
    store.add_mapping(
        MappingRecord("run-1", "req-a", "cat-1", "ac-2", Relationship.SUBSET_OF, 0.8, "high"),
        rationale="because",
    )
    rows = store.list_mappings("run-1")
    assert rows[0]["relation"] == "subset-of"
    assert rows[0]["rationale"] == "because"


def test_evidence_is_compressed_redacted_and_at_least_once(store):
    store.create_run("run-1", "fp", "cfg")
    store.record_evidence(
        run_id="run-1",
        stage="extract",
        item_ref="doc:d1",
        call_type="llm",
        request={"api_key": "secret", "prompt": "hi"},
    )
    rows = store.list_evidence("run-1")
    assert len(rows) == 1
    request = json.loads(zlib.decompress(rows[0]["request_json"]))
    assert request == {"api_key": "[REDACTED]", "prompt": "hi"}

    store.record_evidence(
        run_id="run-1",
        stage="extract",
        item_ref="doc:d1",
        call_type="llm",
        request={"api_key": "secret", "prompt": "hi"},
        response={"answer": "ok", "authorization": "Bearer x"},
        http_status=200,
        attempt_no=1,
    )
    rows = store.list_evidence("run-1")
    assert len(rows) == 1
    response = json.loads(zlib.decompress(rows[0]["response_json"]))
    assert response == {"answer": "ok", "authorization": "[REDACTED]"}
    assert rows[0]["http_status"] == 200


def test_record_attempt(store):
    store.create_run("run-1", "fp", "cfg")
    store.record_attempt(
        run_id="run-1",
        stage="verify",
        item_ref="pair-a",
        call_type="jev",
        attempt_no=1,
        http_status=503,
        error_class="ServiceUnavailable",
        error="retry",
        duration_ms=12,
    )
    assert store.counts("run-1")["attempts"] == 1


def test_domain_index_round_trip(store):
    store.create_run("run-1", "fp", "cfg")
    index = DomainIndex("idx-1", "content", "model", "prompt", {"access": ["ac-1"]})
    store.add_domain_index(index)
    loaded = store.get_domain_index("content", "model", "prompt")
    assert loaded["index_id"] == "idx-1"
    assert json.loads(loaded["index_json"]) == {"access": ["ac-1"]}
    assert store.get_domain_index("other", "model", "prompt") is None
```

- [ ] **Step 2: Run the test and see it fail**

Run: `nix develop -c pytest tests/unit/store/test_run_store.py -v`
Expected: FAIL — `AttributeError: 'RunStore' object has no attribute 'add_candidate_pair'`.

- [ ] **Step 3: Write the minimal implementation**

Add to the imports of `src/smeargle/store/run_store.py` so the final import block is exactly:

```python
from __future__ import annotations

import json
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from smeargle.domain.clock import Clock, SystemClock
from smeargle.domain.controls import Control, DomainIndex
from smeargle.domain.documents import Document
from smeargle.domain.ids import IdFactory, UuidIdFactory, sha256_hex
from smeargle.domain.mapping import CandidatePair, MappingRecord
from smeargle.domain.requirements import Keyword, Requirement
from smeargle.observability import redact
from smeargle.store import db as db_module
from smeargle.store.schema import migrate
```

Add these methods inside `class RunStore`:

```python
    # -- candidate pairs and mappings --------------------------------------
    def add_candidate_pair(
        self, pair: CandidatePair, *, mapped_threshold: Optional[float] = None
    ) -> None:
        self._conn.execute(
            "INSERT INTO candidate_pairs (run_id, pair_id, req_id, catalog_id, control_id,"
            " verify_status, noul_prob, mapped_threshold) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                pair.run_id,
                pair.pair_id,
                pair.req_id,
                pair.catalog_id,
                pair.control_id,
                pair.verify_status,
                pair.noul_prob,
                mapped_threshold,
            ),
        )

    def set_pair_verify(
        self, run_id: str, pair_id: str, *, verify_status: str, noul_prob: Optional[float]
    ) -> None:
        self._conn.execute(
            "UPDATE candidate_pairs SET verify_status = ?, noul_prob = ?"
            " WHERE run_id = ? AND pair_id = ?",
            (verify_status, noul_prob, run_id, pair_id),
        )

    def set_pair_classify(
        self,
        run_id: str,
        pair_id: str,
        *,
        classify_status: str,
        relation: Optional[str] = None,
        confidence_percentage: Optional[float] = None,
        confidence_category: Optional[str] = None,
    ) -> None:
        self._conn.execute(
            "UPDATE candidate_pairs SET classify_status = ?, relation = ?,"
            " confidence_percentage = ?, confidence_category = ?"
            " WHERE run_id = ? AND pair_id = ?",
            (
                classify_status,
                relation,
                confidence_percentage,
                confidence_category,
                run_id,
                pair_id,
            ),
        )

    def get_candidate_pair(self, run_id: str, pair_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM candidate_pairs WHERE run_id = ? AND pair_id = ?", (run_id, pair_id)
        ).fetchone()
        return dict(row) if row else None

    def candidate_pairs_for_verify(self, run_id: str) -> list[CandidatePair]:
        rows = self._conn.execute(
            "SELECT * FROM candidate_pairs WHERE run_id = ? AND verify_status = 'pending'"
            " ORDER BY pair_id",
            (run_id,),
        ).fetchall()
        return [self._pair_from_row(row) for row in rows]

    def candidate_pairs_for_classify(self, run_id: str) -> list[CandidatePair]:
        rows = self._conn.execute(
            "SELECT * FROM candidate_pairs WHERE run_id = ? AND verify_status = 'passed'"
            " AND classify_status IS NULL ORDER BY pair_id",
            (run_id,),
        ).fetchall()
        return [self._pair_from_row(row) for row in rows]

    @staticmethod
    def _pair_from_row(row) -> CandidatePair:
        return CandidatePair(
            run_id=row["run_id"],
            pair_id=row["pair_id"],
            req_id=row["req_id"],
            catalog_id=row["catalog_id"],
            control_id=row["control_id"],
            verify_status=row["verify_status"],
            noul_prob=row["noul_prob"],
        )

    def add_mapping(self, record: MappingRecord, *, rationale: Optional[str] = None) -> None:
        map_uuid = self._ids.uuid_for(
            "map", f"{record.run_id}:{record.req_id}:{record.catalog_id}:{record.control_id}"
        )
        self._conn.execute(
            "INSERT INTO mappings (run_id, map_uuid, req_id, catalog_id, control_id, relation,"
            " confidence_percentage, confidence_category, rationale)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.run_id,
                map_uuid,
                record.req_id,
                record.catalog_id,
                record.control_id,
                record.relation.value,
                record.confidence_percentage,
                record.confidence_category,
                rationale,
            ),
        )

    def list_mappings(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM mappings WHERE run_id = ? ORDER BY map_uuid", (run_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    # -- domain index (content-keyed, cross-run) ---------------------------
    def add_domain_index(self, index: DomainIndex) -> None:
        self._conn.execute(
            "INSERT INTO domain_index (index_id, content_sha256, model_id, prompt_hash,"
            " index_json) VALUES (?, ?, ?, ?, ?)",
            (
                index.index_id,
                index.content_sha256,
                index.model_id,
                index.prompt_hash,
                json.dumps(dict(index.domains)),
            ),
        )

    def get_domain_index(
        self, content_sha256: str, model_id: str, prompt_hash: str
    ) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM domain_index WHERE content_sha256 = ? AND model_id = ?"
            " AND prompt_hash = ?",
            (content_sha256, model_id, prompt_hash),
        ).fetchone()
        return dict(row) if row else None

    # -- attempts and evidence ---------------------------------------------
    def record_attempt(
        self,
        *,
        run_id: str,
        stage: str,
        item_ref: str,
        call_type: str,
        attempt_no: int,
        http_status: Optional[int] = None,
        error_class: Optional[str] = None,
        error: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> str:
        attempt_id = self._ids.uuid_for(
            "attempt", f"{run_id}:{stage}:{item_ref}:{call_type}:{attempt_no}"
        )
        self._conn.execute(
            "INSERT INTO attempts (attempt_id, run_id, stage, item_ref, call_type, attempt_no,"
            " http_status, error_class, error, duration_ms, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                attempt_id,
                run_id,
                stage,
                item_ref,
                call_type,
                attempt_no,
                http_status,
                error_class,
                error,
                duration_ms,
                self._now(),
            ),
        )
        return attempt_id

    def record_evidence(
        self,
        *,
        run_id: str,
        stage: str,
        item_ref: str,
        call_type: str,
        request: Any,
        response: Any = None,
        request_sha256: Optional[str] = None,
        http_status: Optional[int] = None,
        attempt_no: Optional[int] = None,
        prompt_hash: Optional[str] = None,
    ) -> str:
        request_bytes = json.dumps(
            redact(request), sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
        digest = request_sha256 or sha256_hex(request_bytes)
        evidence_id = self._ids.uuid_for(
            "evidence", f"{run_id}:{item_ref}:{call_type}:{digest}"
        )
        response_blob = None
        if response is not None:
            response_blob = zlib.compress(
                json.dumps(
                    redact(response), sort_keys=True, separators=(",", ":"), default=str
                ).encode("utf-8")
            )
        self._conn.execute(
            "INSERT INTO evidence (evidence_id, run_id, stage, item_ref, call_type,"
            " request_json, response_json, request_sha256, http_status, attempt_no,"
            " prompt_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (run_id, item_ref, call_type, request_sha256) DO UPDATE SET"
            " response_json = excluded.response_json, http_status = excluded.http_status,"
            " attempt_no = excluded.attempt_no, prompt_hash = excluded.prompt_hash",
            (
                evidence_id,
                run_id,
                stage,
                item_ref,
                call_type,
                zlib.compress(request_bytes),
                response_blob,
                digest,
                http_status,
                attempt_no,
                prompt_hash,
                self._now(),
            ),
        )
        return evidence_id

    def list_evidence(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM evidence WHERE run_id = ? ORDER BY created_at, evidence_id",
            (run_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def counts(self, run_id: str) -> dict[str, int]:
        tables = (
            "documents",
            "catalogs",
            "controls",
            "requirements",
            "candidate_pairs",
            "mappings",
            "evidence",
            "attempts",
        )
        result: dict[str, int] = {}
        for table in tables:
            row = self._conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE run_id = ?", (run_id,)
            ).fetchone()
            result[table] = int(row[0])
        return result
```

- [ ] **Step 4: Run the test and see it pass**

Run: `nix develop -c pytest tests/unit/store/test_run_store.py -v`
Expected: `16 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/smeargle/store/run_store.py tests/unit/store/test_run_store.py
git commit -m "feat(store): add candidate, evidence, and attempt repository methods" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 8: Text and JSON document loaders

**Files:**
- Create: `src/smeargle/loaders/__init__.py`
- Create: `src/smeargle/loaders/text.py`
- Create: `src/smeargle/loaders/json_text.py`
- Test: `tests/unit/loaders/test_text.py`
- Test: `tests/unit/loaders/test_json_text.py`

**Spec traceability:** §9.1 (plain text/Markdown loader; JSON flattening rule exactly as specified; encoding/BOM normalisation), §5 (`content_sha256` is the raw-bytes hash, so flattening never affects identity).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/loaders/__init__.py` (empty), `tests/unit/loaders/test_text.py`:

```python
import codecs

import pytest

from smeargle.errors import InputError
from smeargle.loaders import text


def test_strips_utf8_bom_and_normalises_newlines():
    raw = codecs.BOM_UTF8 + b"line one\r\nline two\rline three"
    assert text.decode_bytes(raw) == "line one\nline two\nline three"


def test_decodes_utf16_with_bom():
    raw = "hello \u2713".encode("utf-16")
    assert text.decode_bytes(raw) == "hello \u2713"


def test_rejects_undecodable_bytes():
    with pytest.raises(InputError):
        text.decode_bytes(b"\xff\xff\xff")


def test_load_text_returns_media_type(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("hello", encoding="utf-8")
    media_type, content = text.load_text(path)
    assert media_type == "text/plain"
    assert content == "hello"
```

Create `tests/unit/loaders/test_json_text.py`:

```python
import json

import pytest

from smeargle.errors import InputError
from smeargle.loaders import json_text


def _flatten(value):
    return json_text.flatten_value(value)


def test_root_scalar_uses_dollar():
    assert _flatten(42) == "$ = 42"
    assert _flatten("x") == '$ = "x"'
    assert _flatten(None) == "$ = null"


def test_object_keys_are_sorted_and_dotted():
    value = {"b": 2, "a": {"d": True, "c": None}}
    assert _flatten(value) == "a.c = null\na.d = true\nb = 2"


def test_arrays_use_index_paths():
    value = {"items": [1, "two", {"x": 3}]}
    assert _flatten(value) == 'items[0] = 1\nitems[1] = "two"\nitems[2].x = 3'


def test_empty_containers_render_as_leaves():
    assert _flatten({"a": {}, "b": []}) == "a = {}\nb = []"


def test_json_to_text_is_deterministic():
    text = '{"b": 1, "a": 2}'
    assert json_text.json_to_text(text) == "a = 2\nb = 1"
    assert json_text.json_to_text(text) == json_text.json_to_text(text)


def test_invalid_json_is_rejected():
    with pytest.raises(InputError):
        json_text.json_to_text("{not json")


def test_load_json_returns_media_type(tmp_path):
    path = tmp_path / "a.json"
    path.write_text(json.dumps({"a": 1}), encoding="utf-8")
    media_type, content = json_text.load_json(path)
    assert media_type == "application/json"
    assert content == "a = 1"
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `nix develop -c pytest tests/unit/loaders/test_text.py tests/unit/loaders/test_json_text.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'smeargle.loaders'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/smeargle/loaders/__init__.py`:

```python
"""Document loaders and their registry (spec 9.1)."""
```

Create `src/smeargle/loaders/text.py`:

```python
"""Plain-text/Markdown loading with encoding and BOM normalisation (spec 9.1)."""

from __future__ import annotations

import codecs
from pathlib import Path

from smeargle.errors import InputError

_BOMS = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def decode_bytes(raw: bytes) -> str:
    for bom, encoding in _BOMS:
        if raw.startswith(bom):
            decoded = raw.decode(encoding)
            break
    else:
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InputError(f"could not decode text as UTF-8: {exc}") from exc
    return decoded.replace("\r\n", "\n").replace("\r", "\n")


def load_text(path: Path) -> tuple[str, str]:
    return "text/plain", decode_bytes(Path(path).read_bytes())
```

Create `src/smeargle/loaders/json_text.py`:

```python
"""Deterministic JSON-to-text flattening (spec 9.1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from smeargle.errors import InputError


def flatten_value(value: Any) -> str:
    lines: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            if not node:
                lines.append(f"{path or '$'} = {{}}")
            else:
                for key in sorted(node):
                    walk(node[key], f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            if not node:
                lines.append(f"{path or '$'} = []")
            else:
                for index, item in enumerate(node):
                    walk(item, f"{path}[{index}]")
        else:
            lines.append(f"{path or '$'} = {json.dumps(node, ensure_ascii=False)}")

    walk(value, "")
    return "\n".join(lines)


def json_to_text(raw: str) -> str:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InputError(f"invalid JSON document: {exc}") from exc
    return flatten_value(value)


def load_json(path: Path) -> tuple[str, str]:
    path = Path(path)
    return "application/json", json_to_text(path.read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `nix develop -c pytest tests/unit/loaders/test_text.py tests/unit/loaders/test_json_text.py -v`
Expected: `11 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/smeargle/loaders/__init__.py src/smeargle/loaders/text.py src/smeargle/loaders/json_text.py tests/unit/loaders/__init__.py tests/unit/loaders/test_text.py tests/unit/loaders/test_json_text.py
git commit -m "feat(loaders): add text and json flattening loaders" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 9: PDF, DOCX, and loader registry

**Files:**
- Create: `src/smeargle/loaders/pdf.py`
- Create: `src/smeargle/loaders/docx.py`
- Create: `src/smeargle/loaders/registry.py`
- Test: `tests/unit/loaders/test_registry.py`

**Spec traceability:** §9.1 (PDF via `pypdf`, DOCX via `python-docx`; scanned/image-only PDFs and legacy binary `.doc` rejected with actionable errors), §10 Stage 0 (media-type detection).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/loaders/test_registry.py`:

```python
import json

import pytest
from docx import Document as DocxDocument
from pypdf import PdfWriter

from smeargle.errors import InputError
from smeargle.loaders import registry


def test_load_text_and_json(tmp_path):
    txt = tmp_path / "a.md"
    txt.write_text("# Title", encoding="utf-8")
    assert registry.load_document(txt) == ("text/plain", "# Title")
    js = tmp_path / "a.json"
    js.write_text(json.dumps({"a": 1}), encoding="utf-8")
    assert registry.load_document(js) == ("application/json", "a = 1")


def test_load_docx(tmp_path):
    path = tmp_path / "a.docx"
    document = DocxDocument()
    document.add_paragraph("First paragraph")
    document.save(path)
    media_type, content = registry.load_document(path)
    assert media_type.endswith("wordprocessingml.document")
    assert content == "First paragraph"


def test_scanned_pdf_is_rejected(tmp_path):
    path = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with path.open("wb") as handle:
        writer.write(handle)
    with pytest.raises(InputError, match="scanned/image-only"):
        registry.load_document(path)


def test_legacy_doc_is_rejected(tmp_path):
    path = tmp_path / "old.doc"
    path.write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 32)
    with pytest.raises(InputError, match=r"\.doc"):
        registry.load_document(path)


def test_unknown_suffix_is_rejected(tmp_path):
    path = tmp_path / "a.xyz"
    path.write_text("x", encoding="utf-8")
    with pytest.raises(InputError, match="unsupported"):
        registry.load_document(path)


def test_detect_media_type_by_magic_bytes(tmp_path):
    path = tmp_path / "noext"
    path.write_bytes(b"%PDF-1.7\n")
    assert registry.detect_media_type(path) == "application/pdf"
```

- [ ] **Step 2: Run the test and see it fail**

Run: `nix develop -c pytest tests/unit/loaders/test_registry.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'smeargle.loaders.registry'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/smeargle/loaders/pdf.py`:

```python
"""PDF loading with pypdf; scanned/image-only PDFs are rejected (spec 9.1)."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from smeargle.errors import InputError


def load_pdf(path: Path) -> tuple[str, str]:
    path = Path(path)
    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    content = "\n".join(pages).strip()
    if not content:
        raise InputError(
            f"'{path}' is a scanned/image-only PDF with no extractable text;"
            " OCR is not supported - supply a text, Markdown, DOCX, or text-based PDF"
        )
    return "application/pdf", content
```

Create `src/smeargle/loaders/docx.py`:

```python
"""DOCX loading via python-docx (spec 9.1)."""

from __future__ import annotations

from pathlib import Path

from docx import Document as DocxDocument

from smeargle.errors import InputError

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def load_docx(path: Path) -> tuple[str, str]:
    path = Path(path)
    document = DocxDocument(str(path))
    paragraphs = [paragraph.text for paragraph in document.paragraphs]
    content = "\n".join(paragraphs).strip()
    if not content:
        raise InputError(
            f"'{path}' contains no extractable paragraph text;"
            " scanned/image-only documents are not supported"
        )
    return DOCX_MEDIA_TYPE, content
```

Create `src/smeargle/loaders/registry.py`:

```python
"""Media-type detection and loader registry (spec 9.1)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from smeargle.errors import InputError
from smeargle.loaders import docx, json_text, pdf, text

Loader = Callable[[Path], tuple[str, str]]

SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".json", ".txt", ".md", ".markdown")
OLE_MAGIC = b"\xd0\xcf\x11\xe0"

_SUFFIX_LOADERS: dict[str, Loader] = {
    ".pdf": pdf.load_pdf,
    ".docx": docx.load_docx,
    ".json": json_text.load_json,
    ".txt": text.load_text,
    ".md": text.load_text,
    ".markdown": text.load_text,
}


def detect_media_type(path: Path) -> str:
    path = Path(path)
    raw = path.read_bytes()
    if raw.startswith(b"%PDF-"):
        return "application/pdf"
    if raw.startswith(OLE_MAGIC):
        return "application/msword"
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return docx.DOCX_MEDIA_TYPE
    if suffix == ".json":
        return "application/json"
    if suffix in {".txt", ".md", ".markdown"}:
        return "text/plain"
    return "application/octet-stream"


def loader_for(path: Path) -> Loader:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".doc":
        raise InputError(
            f"'{path}' is a legacy binary .doc file, which is not supported;"
            " convert it to .docx or PDF"
        )
    if path.read_bytes().startswith(OLE_MAGIC):
        raise InputError(
            f"'{path}' looks like a legacy binary .doc/OLE file, which is not supported;"
            " convert it to .docx or PDF"
        )
    loader = _SUFFIX_LOADERS.get(suffix)
    if loader is None:
        supported = ", ".join(SUPPORTED_EXTENSIONS)
        raise InputError(f"unsupported input type '{suffix or path.name}'; supported: {supported}")
    return loader


def load_document(path: Path) -> tuple[str, str]:
    path = Path(path)
    return loader_for(path)(path)
```

- [ ] **Step 4: Run the test and see it pass**

Run: `nix develop -c pytest tests/unit/loaders/test_registry.py -v`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/smeargle/loaders/pdf.py src/smeargle/loaders/docx.py src/smeargle/loaders/registry.py tests/unit/loaders/test_registry.py
git commit -m "feat(loaders): add pdf, docx, and registry with rejections" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 10: Control-id sanitisation, adapter types, and catalog registry

**Files:**
- Create: `src/smeargle/catalog_adapters/__init__.py`
- Create: `src/smeargle/catalog_adapters/types.py`
- Create: `src/smeargle/catalog_adapters/ids.py`
- Create: `src/smeargle/catalog_adapters/registry.py`
- Test: `tests/unit/catalog_adapters/__init__.py`
- Test: `tests/unit/catalog_adapters/test_ids.py`

**Spec traceability:** §9.2 (control-id sanitisation: replace characters outside `[\p{L}\p{N}._-]` with `-`, then prefix `c-` when the id does not start with a letter or `_`), §10 Stage 2 step 1, §5 (`Control`).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/catalog_adapters/__init__.py` (empty) and `tests/unit/catalog_adapters/test_ids.py`:

```python
import pytest

from smeargle.catalog_adapters import ids


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ac-2", "ac-2"),
        ("AC-2(1)", "AC-2-1-"),
        ("1.1.1", "c-1.1.1"),
        ("_private", "_private"),
        ("a/b c", "a-b-c"),
        ("9a", "c-9a"),
        ("-leading", "c--leading"),
    ],
)
def test_sanitize_control_id(raw, expected):
    assert ids.sanitize_control_id(raw) == expected


def test_sanitize_is_token_safe_and_deterministic():
    assert ids.is_token_safe(ids.sanitize_control_id("1 bad/id")) is True
    assert ids.is_token_safe(ids.sanitize_control_id("ac-2")) is True
    assert ids.is_token_safe("1bad") is False


def test_empty_id_becomes_prefixed():
    assert ids.sanitize_control_id("") == "c-"
```

- [ ] **Step 2: Run the test and see it fail**

Run: `nix develop -c pytest tests/unit/catalog_adapters/test_ids.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'smeargle.catalog_adapters'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/smeargle/catalog_adapters/__init__.py`:

```python
"""Catalog adapters that normalise inputs into the Control model (spec 9.2)."""
```

Create `src/smeargle/catalog_adapters/ids.py`:

```python
"""TokenDatatype-safe control-id sanitisation (spec 9.2)."""

from __future__ import annotations

import re

_DISALLOWED = re.compile(r"[^\w.\-]")


def sanitize_control_id(raw: str) -> str:
    replaced = _DISALLOWED.sub("-", raw)
    if not replaced or not (replaced[0].isalpha() or replaced[0] == "_"):
        return f"c-{replaced}"
    return replaced


def is_token_safe(value: str) -> bool:
    if not value or not (value[0].isalpha() or value[0] == "_"):
        return False
    return _DISALLOWED.search(value) is None
```

`\w` in Python matches Unicode letters, digits, and `_` (the OSCAL `\p{L}|\p{N}|_` set), and the pattern additionally permits `.` and `-`; this reproduces `^(\p{L}|_)(\p{L}|\p{N}|[.\-_])*$` exactly after the `c-` prefix rule.

Create `src/smeargle/catalog_adapters/types.py`:

```python
"""Neutral intermediate values shared by catalog adapters (spec 9.2)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ParsedControl:
    control_id: str
    original_id: str
    title: str
    text: str
    domain: str
    family: str
    path: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ParsedCatalog:
    title: str
    version: str
    oscal_version: str
    source_kind: str
    controls: tuple[ParsedControl, ...]
```

Create `src/smeargle/catalog_adapters/registry.py`:

```python
"""Catalog-format detection and adapter dispatch (spec 9.2)."""

from __future__ import annotations

import json
from pathlib import Path

from smeargle.catalog_adapters.types import ParsedCatalog
from smeargle.errors import CatalogError

VENDOR_KIND = "vendor-security-controls"
OSCAL_KIND = "oscal"


def _load_json(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CatalogError(f"'{path}' is not valid JSON: {exc}") from exc


def detect_kind(path: Path, document: dict) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in {".xml", ".yaml", ".yml"}:
        return OSCAL_KIND
    catalog = document.get("catalog") if isinstance(document, dict) else None
    if isinstance(catalog, dict) and "securityControls" in catalog:
        return VENDOR_KIND
    return OSCAL_KIND


def parse_catalog(path: Path, catalog_format: str = "auto") -> tuple[str, ParsedCatalog]:
    from smeargle.catalog_adapters import oscal as oscal_adapter
    from smeargle.catalog_adapters import vendor_security_controls as vendor_adapter
    from smeargle.oscal_build import facade

    path = Path(path)
    suffix = path.suffix.lower()
    if catalog_format == "oscal":
        return OSCAL_KIND, oscal_adapter.parse_standard(facade.load_document(path))
    if catalog_format != "auto":
        raise CatalogError(f"unsupported catalog format '{catalog_format}'")

    if suffix in {".xml", ".yaml", ".yml"}:
        return OSCAL_KIND, oscal_adapter.parse_standard(facade.load_document(path))

    document = _load_json(path)
    kind = detect_kind(path, document)
    if kind == VENDOR_KIND:
        return kind, vendor_adapter.parse_vendor(document)
    return OSCAL_KIND, oscal_adapter.parse_standard(facade.load_document(path))
```

- [ ] **Step 4: Run the test and see it pass**

Run: `nix develop -c pytest tests/unit/catalog_adapters/test_ids.py -v`
Expected: `9 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/smeargle/catalog_adapters/__init__.py src/smeargle/catalog_adapters/types.py src/smeargle/catalog_adapters/ids.py src/smeargle/catalog_adapters/registry.py tests/unit/catalog_adapters/__init__.py tests/unit/catalog_adapters/test_ids.py
git commit -m "feat(catalog-adapters): add id sanitisation and format registry" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 11: Standard OSCAL and vendor adapters with normalisation

**Files:**
- Create: `src/smeargle/catalog_adapters/oscal.py`
- Create: `src/smeargle/catalog_adapters/vendor_security_controls.py`
- Create: `src/smeargle/catalog_adapters/normalise.py`
- Test: `tests/unit/catalog_adapters/test_adapters.py`
- Test: `tests/unit/test_dependency_direction.py`

**Spec traceability:** §9.2 (standard OSCAL catalog + vendor `securityControls`; original id as `prop name=original-id`; source-document reference), §10 Stage 2 (parse into `Control[]`; fail fast on duplicate ids), §11.2 (normalised catalogs as the profile import target), §4 (only the facade imports `oscal`).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/catalog_adapters/test_adapters.py`:

```python
from smeargle.catalog_adapters import normalise, oscal, vendor_security_controls
from smeargle.catalog_adapters.ids import sanitize_control_id

STANDARD = {
    "catalog": {
        "uuid": "11111111-1111-4111-8111-111111111111",
        "metadata": {
            "title": "Standard Catalog",
            "last-modified": "2026-01-01T00:00:00Z",
            "version": "2.0.0",
            "oscal-version": "1.2.3",
        },
        "groups": [
            {
                "id": "ac",
                "title": "Access Control",
                "controls": [
                    {
                        "id": "ac-2",
                        "title": "Account Management",
                        "parts": [
                            {
                                "id": "ac-2_smt",
                                "name": "statement",
                                "prose": "Manage accounts.",
                            },
                            {
                                "id": "ac-2_smt.a",
                                "name": "item",
                                "prose": "Define account types.",
                            },
                        ],
                    }
                ],
            }
        ],
    }
}

VENDOR = {
    "catalog": {
        "name": "Vendor Controls",
        "securityControls": [
            {
                "controlId": "1.1",
                "title": "Policy",
                "family": "Access Control",
                "description": "Establish a policy.",
            }
        ],
    }
}


def test_standard_adapter_extracts_controls():
    parsed = oscal.parse_standard(STANDARD)
    assert parsed.title == "Standard Catalog"
    assert parsed.version == "2.0.0"
    assert parsed.source_kind == "oscal"
    control = parsed.controls[0]
    assert control.control_id == "ac-2"
    assert control.original_id == "ac-2"
    assert control.domain == "ac"
    assert control.family == "Access Control"
    assert control.path == ("ac",)
    assert "Manage accounts." in control.text
    assert "Define account types." in control.text


def test_vendor_adapter_sanitises_and_preserves_original():
    parsed = vendor_security_controls.parse_vendor(VENDOR)
    assert parsed.title == "Vendor Controls"
    assert parsed.source_kind == "vendor-security-controls"
    control = parsed.controls[0]
    assert control.control_id == "c-1.1"
    assert control.original_id == "1.1"
    assert control.family == "Access Control"
    assert control.text == "Establish a policy."


def test_normalise_builds_valid_shape():
    parsed = vendor_security_controls.parse_vendor(VENDOR)
    document = normalise.build_normalised_catalog(
        catalog_id="cat-1",
        parsed=parsed,
        source_uri="file:///vendor.json",
        last_modified="2026-01-01T00:00:00Z",
        uuid_for=lambda kind, key: "22222222-2222-4222-8222-222222222222",
    )
    catalog = document["catalog"]
    assert catalog["metadata"]["oscal-version"] == "1.2.3"
    assert catalog["metadata"]["title"] == "Vendor Controls"
    group = catalog["groups"][0]
    assert group["title"] == "Access Control"
    control = group["controls"][0]
    assert control["id"] == sanitize_control_id("1.1")
    props = {prop["name"]: prop["value"] for prop in control["props"]}
    assert props["original-id"] == "1.1"
    assert props["source-document"] == "file:///vendor.json"


def test_normalise_omits_empty_parts():
    parsed = vendor_security_controls.parse_vendor(
        {
            "catalog": {
                "name": "V",
                "securityControls": [{"controlId": "1.1", "title": "Empty", "family": "A"}],
            }
        }
    )
    document = normalise.build_normalised_catalog(
        catalog_id="cat-1",
        parsed=parsed,
        source_uri="file:///vendor.json",
        last_modified="2026-01-01T00:00:00Z",
        uuid_for=lambda kind, key: "22222222-2222-4222-8222-222222222222",
    )
    control = document["catalog"]["groups"][0]["controls"][0]
    assert "parts" not in control
```

Create `tests/unit/test_dependency_direction.py`:

```python
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "smeargle"


def _imports(path: Path):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            yield node.module or ""


def test_only_facade_imports_oscal():
    offenders = []
    for path in SRC.rglob("*.py"):
        if path.name == "facade.py":
            continue
        for module in _imports(path):
            if module == "oscal" or module.startswith("oscal."):
                offenders.append(f"{path.name} imports {module}")
    assert offenders == []
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `nix develop -c pytest tests/unit/catalog_adapters/test_adapters.py tests/unit/test_dependency_direction.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'smeargle.catalog_adapters.oscal'`.

- [ ] **Step 3: Write the minimal implementations**

Create `src/smeargle/catalog_adapters/oscal.py`:

```python
"""Standard OSCAL catalog adapter (spec 9.2)."""

from __future__ import annotations

from typing import Any

from smeargle.catalog_adapters.ids import sanitize_control_id
from smeargle.catalog_adapters.types import ParsedCatalog, ParsedControl


def _parts_text(parts: Any) -> str:
    if not isinstance(parts, list):
        return ""
    chunks: list[str] = []
    for part in parts:
        if isinstance(part, dict):
            prose = part.get("prose")
            if prose:
                chunks.append(str(prose))
            nested = _parts_text(part.get("parts", []))
            if nested:
                chunks.append(nested)
    return "\n".join(chunks)


def _parsed(control: dict, domain: str, family: str, path: tuple[str, ...]) -> ParsedControl:
    original = str(control.get("id", ""))
    return ParsedControl(
        control_id=sanitize_control_id(original),
        original_id=original,
        title=str(control.get("title", "")),
        text=_parts_text(control.get("parts", [])),
        domain=domain,
        family=family,
        path=path,
    )


def parse_standard(document: dict) -> ParsedCatalog:
    catalog = document.get("catalog")
    if not isinstance(catalog, dict):
        raise ValueError("document does not contain a catalog object")
    metadata = catalog.get("metadata", {})
    controls: list[ParsedControl] = []

    def walk_group(group: dict, path: tuple[str, ...]) -> None:
        group_id = str(group.get("id", ""))
        group_title = str(group.get("title", "")) or group_id
        current = path + (group_id,) if group_id else path
        domain = current[0] if current else ""
        for control in group.get("controls", []) or []:
            controls.append(_parsed(control, domain, group_title, current))
        for child in group.get("groups", []) or []:
            walk_group(child, current)

    for control in catalog.get("controls", []) or []:
        controls.append(_parsed(control, "", "", ()))
    for group in catalog.get("groups", []) or []:
        walk_group(group, ())

    return ParsedCatalog(
        title=str(metadata.get("title", "")) or "catalog",
        version=str(metadata.get("version", "")) or "1.0.0",
        oscal_version=str(metadata.get("oscal-version", "")) or "1.2.3",
        source_kind="oscal",
        controls=tuple(controls),
    )
```

Create `src/smeargle/catalog_adapters/vendor_security_controls.py`:

```python
"""Vendor `securityControls` catalog adapter (spec 9.2)."""

from __future__ import annotations

from smeargle.catalog_adapters.ids import sanitize_control_id
from smeargle.catalog_adapters.types import ParsedCatalog, ParsedControl


def parse_vendor(document: dict) -> ParsedCatalog:
    catalog = document.get("catalog")
    if not isinstance(catalog, dict):
        raise ValueError("document does not contain a catalog object")
    controls: list[ParsedControl] = []
    for item in catalog.get("securityControls", []) or []:
        original = str(item.get("controlId") or item.get("id") or "")
        family = str(item.get("family", ""))
        controls.append(
            ParsedControl(
                control_id=sanitize_control_id(original),
                original_id=original,
                title=str(item.get("title", "")),
                text=str(item.get("description", "")),
                domain=family,
                family=family,
                path=(family,) if family else (),
            )
        )
    return ParsedCatalog(
        title=str(catalog.get("name") or catalog.get("title") or ""),
        version=str(catalog.get("version", "")) or "1.0.0",
        oscal_version="1.2.3",
        source_kind="vendor-security-controls",
        controls=tuple(controls),
    )
```

Create `src/smeargle/catalog_adapters/normalise.py`:

```python
"""Build a normalised OSCAL catalog as a plain dict (spec 9.2, 11.2)."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Callable

from smeargle.catalog_adapters.ids import sanitize_control_id
from smeargle.catalog_adapters.types import ParsedCatalog, ParsedControl


def _control_dict(control: ParsedControl, source_uri: str) -> dict[str, Any]:
    props: list[dict[str, str]] = [
        {"name": "original-id", "value": control.original_id},
        {"name": "source-document", "value": source_uri},
    ]
    control_dict: dict[str, Any] = {
        "id": control.control_id,
        "title": control.title or control.control_id,
        "props": props,
    }
    if control.text:
        control_dict["parts"] = [
            {
                "id": f"{control.control_id}-statement",
                "name": "statement",
                "prose": control.text,
            }
        ]
    return control_dict


def build_normalised_catalog(
    *,
    catalog_id: str,
    parsed: ParsedCatalog,
    source_uri: str,
    last_modified: str,
    uuid_for: Callable[[str, str], str],
) -> dict[str, Any]:
    groups: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    for control in parsed.controls:
        label = control.family or control.domain or "controls"
        group_id = sanitize_control_id(label)
        if group_id not in groups:
            groups[group_id] = {"id": group_id, "title": label, "controls": []}
        groups[group_id]["controls"].append(_control_dict(control, source_uri))

    catalog: dict[str, Any] = {
        "uuid": uuid_for("catalog", catalog_id),
        "metadata": {
            "title": parsed.title or "catalog",
            "last-modified": last_modified,
            "version": parsed.version or "1.0.0",
            "oscal-version": "1.2.3",
        },
    }
    if groups:
        catalog["groups"] = list(groups.values())
    return {"catalog": catalog}
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `nix develop -c pytest tests/unit/catalog_adapters/test_adapters.py tests/unit/test_dependency_direction.py -v`
Expected: `5 passed` (4 adapter tests + 1 guard).

- [ ] **Step 5: Commit**

```bash
git add src/smeargle/catalog_adapters/oscal.py src/smeargle/catalog_adapters/vendor_security_controls.py src/smeargle/catalog_adapters/normalise.py tests/unit/catalog_adapters/test_adapters.py tests/unit/test_dependency_direction.py
git commit -m "feat(catalog-adapters): add oscal and vendor adapters with normalisation" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 12: Pipeline Stage 0 `load`

**Files:**
- Create: `src/smeargle/pipeline/__init__.py`
- Create: `src/smeargle/pipeline/load.py`
- Test: `tests/integration/test_load_stage.py`

**Spec traceability:** §10 Stage 0 (detect media type → loader → `Document`; dedup identical content; reject unsupported/scanned inputs; canonical emission ordering by `content_sha256`), §5 (`doc_id = sha256(raw bytes)`), §7 (`UNIQUE(run_id, content_sha256)`).

- [ ] **Step 1: Write the failing test**

Create `tests/integration/__init__.py` (empty) and `tests/integration/test_load_stage.py`:

```python
from datetime import datetime, timezone

import pytest

from smeargle.domain.clock import FrozenClock
from smeargle.domain.ids import UuidIdFactory
from smeargle.errors import InputError
from smeargle.pipeline import load
from smeargle.store.run_store import RunStore


@pytest.fixture
def store(tmp_path):
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    with RunStore.open(tmp_path, clock=clock, id_factory=UuidIdFactory()) as opened:
        opened.create_run("run-1", "fp", "cfg")
        yield opened


def test_load_persists_documents_in_canonical_order(store, tmp_path):
    first = tmp_path / "a.txt"
    first.write_text("alpha", encoding="utf-8")
    second = tmp_path / "b.md"
    second.write_text("beta", encoding="utf-8")

    documents = load.run_load(store, "run-1", [first, second])

    assert [doc.ordinal for doc in documents] == [0, 1]
    assert documents[0].content_sha256 == sorted(
        d.content_sha256 for d in documents
    )[0]
    assert len(store.list_documents("run-1")) == 2


def test_load_deduplicates_identical_content(store, tmp_path):
    first = tmp_path / "a.txt"
    first.write_text("same", encoding="utf-8")
    duplicate = tmp_path / "b.txt"
    duplicate.write_text("same", encoding="utf-8")

    documents = load.run_load(store, "run-1", [first, duplicate])

    assert len(documents) == 1
    assert len(store.list_documents("run-1")) == 1


def test_load_rejects_unsupported_input(store, tmp_path):
    bad = tmp_path / "a.xyz"
    bad.write_text("x", encoding="utf-8")
    with pytest.raises(InputError):
        load.run_load(store, "run-1", [bad])


def test_load_marks_stage_complete(store, tmp_path):
    doc = tmp_path / "a.txt"
    doc.write_text("alpha", encoding="utf-8")
    load.run_load(store, "run-1", [doc])
    assert store.get_stage("run-1", "load")["status"] == "complete"
```

- [ ] **Step 2: Run the test and see it fail**

Run: `nix develop -c pytest tests/integration/test_load_stage.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'smeargle.pipeline'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/smeargle/pipeline/__init__.py`:

```python
"""Stage pipeline over the SQLite run store (spec 10)."""
```

Create `src/smeargle/pipeline/load.py`:

```python
"""Stage 0: detect, load, deduplicate, and persist input documents (spec 10)."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from smeargle.domain.documents import Document
from smeargle.domain.ids import doc_id_for
from smeargle.loaders import registry
from smeargle.store.run_store import RunStore


def run_load(store: RunStore, run_id: str, input_paths: Iterable[Path]) -> list[Document]:
    store.start_stage(run_id, "load")
    loaded: list[Document] = []
    seen: set[str] = set()
    for path in (Path(p) for p in input_paths):
        raw = path.read_bytes()
        content_sha256 = doc_id_for(raw)
        if content_sha256 in seen:
            continue
        seen.add(content_sha256)
        media_type, text = registry.load_document(path)
        loaded.append(
            Document(
                run_id=run_id,
                doc_id=content_sha256,
                ordinal=0,
                path=str(path),
                uri=path.absolute().as_uri(),
                external_id=None,
                media_type=media_type,
                content_sha256=content_sha256,
                size_bytes=len(raw),
                text=text,
            )
        )

    loaded.sort(key=lambda document: document.content_sha256)
    ordered = [
        Document(
            run_id=document.run_id,
            doc_id=document.doc_id,
            ordinal=ordinal,
            path=document.path,
            uri=document.uri,
            external_id=document.external_id,
            media_type=document.media_type,
            content_sha256=document.content_sha256,
            size_bytes=document.size_bytes,
            text=document.text,
        )
        for ordinal, document in enumerate(loaded)
    ]
    for document in ordered:
        store.add_document(document)
    store.complete_stage(run_id, "load")
    return ordered
```

- [ ] **Step 4: Run the test and see it pass**

Run: `nix develop -c pytest tests/integration/test_load_stage.py -v`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/smeargle/pipeline/__init__.py src/smeargle/pipeline/load.py tests/integration/__init__.py tests/integration/test_load_stage.py
git commit -m "feat(pipeline): add stage 0 document loading" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 13: Catalog ingest (Stage 2 partial) and normalised catalog emission

**Files:**
- Create: `src/smeargle/pipeline/index.py`
- Test: `tests/integration/test_ingest_pipeline.py`
- Test: `tests/integration/test_normalised_catalog.py`

**Spec traceability:** §10 Stage 2 step 1 (parse via adapter into `Control[]`, fail fast on duplicate ids; LLM domain-index steps deferred to Phase 3), §9.2 (duplicate sanitised ids across all input catalogs fail fast, naming the colliding catalogs and ids), §11 (`catalogs/<source-stem>.json`, stem-collision fail-fast), §14 (emitted catalog validates against the vendored schema and the metaschema).

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_normalised_catalog.py`:

```python
from support.schemas import validate_against_schema

from smeargle.catalog_adapters import normalise, vendor_security_controls
from smeargle.domain.ids import UuidIdFactory

VENDOR = {
    "catalog": {
        "name": "Vendor Controls",
        "securityControls": [
            {
                "controlId": "1.1",
                "title": "Policy",
                "family": "Access Control",
                "description": "Establish a policy.",
            },
            {
                "controlId": "2.1",
                "title": "Review",
                "family": "Audit",
                "description": "Review logs.",
            },
            {
                "controlId": "2.2",
                "title": "Review II",
                "family": "Audit",
            },
        ],
    }
}


def test_normalised_catalog_validates_against_vendored_schema():
    parsed = vendor_security_controls.parse_vendor(VENDOR)
    document = normalise.build_normalised_catalog(
        catalog_id="cat-1",
        parsed=parsed,
        source_uri="file:///vendor.json",
        last_modified="2026-01-01T00:00:00Z",
        uuid_for=UuidIdFactory().uuid_for,
    )
    validate_against_schema("catalog", document)
    assert {group["title"] for group in document["catalog"]["groups"]} == {
        "Access Control",
        "Audit",
    }
```

Create `tests/integration/test_ingest_pipeline.py`:

```python
import json
from datetime import datetime, timezone

import pytest
from support.schemas import validate_against_schema

from smeargle.domain.clock import FrozenClock
from smeargle.domain.ids import UuidIdFactory
from smeargle.errors import CatalogError
from smeargle.pipeline import index
from smeargle.store.run_store import RunStore


@pytest.fixture
def store(tmp_path):
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    with RunStore.open(tmp_path, clock=clock, id_factory=UuidIdFactory()) as opened:
        opened.create_run("run-1", "fp", "cfg")
        yield opened


def _vendor(path, controls):
    path.write_text(
        json.dumps({"catalog": {"name": "V", "securityControls": controls}}),
        encoding="utf-8",
    )
    return path


def test_ingest_persists_catalogs_and_controls_and_emits(store, tmp_path):
    catalog = _vendor(
        tmp_path / "vendor.json",
        [{"controlId": "1.1", "title": "Policy", "family": "Access", "description": "d"}],
    )
    output = tmp_path / "out"
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    result = index.ingest_catalogs(
        store,
        "run-1",
        [catalog],
        output,
        catalog_format="auto",
        clock=clock,
        id_factory=UuidIdFactory(),
    )
    assert len(result) == 1
    assert store.counts("run-1")["catalogs"] == 1
    assert store.counts("run-1")["controls"] == 1
    emitted = json.loads((output / "catalogs" / "vendor.json").read_text(encoding="utf-8"))
    validate_against_schema("catalog", emitted)


def test_ingest_fails_fast_on_duplicate_control_ids(store, tmp_path):
    one = _vendor(tmp_path / "one.json", [{"controlId": "1.1", "title": "A"}])
    two = _vendor(tmp_path / "two.json", [{"controlId": "1.1", "title": "B"}])
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    with pytest.raises(CatalogError) as excinfo:
        index.ingest_catalogs(
            store,
            "run-1",
            [one, two],
            tmp_path / "out",
            catalog_format="auto",
            clock=clock,
            id_factory=UuidIdFactory(),
        )
    message = str(excinfo.value)
    assert "duplicate control id '1.1'" in message
    assert "sanitised 'c-1.1'" in message
    assert "one.json" in message
    assert "two.json" in message


def test_forced_oscal_rejects_vendor_shape(store, tmp_path):
    vendor = _vendor(tmp_path / "vendor.json", [{"controlId": "1.1", "title": "A"}])
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    with pytest.raises(CatalogError):
        index.ingest_catalogs(
            store,
            "run-1",
            [vendor],
            tmp_path / "out",
            catalog_format="oscal",
            clock=clock,
            id_factory=UuidIdFactory(),
        )


def test_ingest_fails_fast_on_stem_collision(store, tmp_path):
    one = _vendor(tmp_path / "same.json", [{"controlId": "1.1", "title": "A"}])
    two = tmp_path / "same.yaml"
    two.write_text("catalog:\n  metadata:\n    title: T\n", encoding="utf-8")
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    with pytest.raises(CatalogError, match="stem"):
        index.ingest_catalogs(
            store,
            "run-1",
            [one, two],
            tmp_path / "out",
            catalog_format="auto",
            clock=clock,
            id_factory=UuidIdFactory(),
        )
```

- [ ] **Step 2: Run the tests and see them fail**

Run: `nix develop -c pytest tests/integration/test_ingest_pipeline.py tests/integration/test_normalised_catalog.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'smeargle.pipeline.index'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/smeargle/pipeline/index.py`:

```python
"""Stage 2 (catalog ingest portion): parse catalogs and emit normalised OSCAL (spec 10)."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from smeargle.catalog_adapters import normalise
from smeargle.catalog_adapters.registry import parse_catalog
from smeargle.domain.clock import Clock
from smeargle.domain.controls import Control
from smeargle.domain.ids import IdFactory, catalog_id_for
from smeargle.errors import CatalogError
from smeargle.oscal_build import facade
from smeargle.store.run_store import CatalogRow, RunStore


def _oscal_timestamp(clock: Clock) -> str:
    return clock.now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")


def _check_stems(paths: list[Path]) -> None:
    seen: dict[str, Path] = {}
    for path in paths:
        stem = path.stem
        if stem in seen and seen[stem] != path:
            raise CatalogError(
                f"inputs '{seen[stem]}' and '{path}' share the stem '{stem}';"
                " rename one so normalised catalogs do not collide"
            )
        seen[stem] = path


def ingest_catalogs(
    store: RunStore,
    run_id: str,
    catalog_paths: Iterable[Path],
    output_dir: Path,
    *,
    catalog_format: str,
    clock: Clock,
    id_factory: IdFactory,
) -> list[str]:
    store.start_stage(run_id, "index")
    paths = [Path(p) for p in catalog_paths]
    _check_stems(paths)

    parsed_catalogs = []
    for path in paths:
        raw = path.read_bytes()
        catalog_id = catalog_id_for(raw)
        _kind, parsed = parse_catalog(path, catalog_format)
        parsed_catalogs.append((path, catalog_id, parsed))

    duplicate_paths: dict[str, Path] = {}
    for path, _catalog_id, parsed in parsed_catalogs:
        for control in parsed.controls:
            if control.control_id in duplicate_paths:
                raise CatalogError(
                    f"duplicate control id '{control.original_id}'"
                    f" (sanitised '{control.control_id}') in catalogs"
                    f" '{duplicate_paths[control.control_id]}' and '{path}'"
                )
            duplicate_paths[control.control_id] = path

    with store.transaction():
        for ordinal, (path, catalog_id, parsed) in enumerate(parsed_catalogs):
            store.add_catalog(
                CatalogRow(
                    run_id=run_id,
                    catalog_id=catalog_id,
                    ordinal=ordinal,
                    uri=path.absolute().as_uri(),
                    path=str(path),
                    external_id=None,
                    content_sha256=catalog_id,
                    oscal_version=parsed.oscal_version,
                    status="loaded",
                )
            )
            store.add_controls(
                [
                    Control(
                        run_id=run_id,
                        catalog_id=catalog_id,
                        control_id=control.control_id,
                        title=control.title,
                        text=control.text,
                        domain=control.domain,
                        family=control.family,
                        path=control.path,
                    )
                    for control in parsed.controls
                ]
            )
            document = normalise.build_normalised_catalog(
                catalog_id=catalog_id,
                parsed=parsed,
                source_uri=path.absolute().as_uri(),
                last_modified=_oscal_timestamp(clock),
                uuid_for=id_factory.uuid_for,
            )
            facade.validate("catalog", document)
            catalogs_dir = Path(output_dir) / "catalogs"
            catalogs_dir.mkdir(parents=True, exist_ok=True)
            (catalogs_dir / f"{path.stem}.json").write_text(
                facade.serialise_json("catalog", document), encoding="utf-8"
            )
        store.complete_stage(run_id, "index")

    return [catalog_id for _path, catalog_id, _parsed in parsed_catalogs]
```

- [ ] **Step 4: Run the tests and see them pass**

Run: `nix develop -c pytest tests/integration/test_ingest_pipeline.py tests/integration/test_normalised_catalog.py -v`
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/smeargle/pipeline/index.py tests/integration/test_ingest_pipeline.py tests/integration/test_normalised_catalog.py
git commit -m "feat(pipeline): add catalog ingest and normalised emission" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 14: Ingestion run orchestration, fingerprint, and config hash

**Files:**
- Create: `src/smeargle/pipeline/run.py`
- Test: `tests/integration/test_run_orchestration.py`

**Spec traceability:** §7.1 (order-independent, version-salted `fingerprint`; `config_hash` covering model/threshold/temperature settings), §12 (`--run-id`, `--force`; the fingerprint-hit resume prompt is Phase 3), §5 (`run_id` distinct from `fingerprint`).

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_run_orchestration.py`:

```python
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from smeargle.config import Settings
from smeargle.domain.clock import FrozenClock
from smeargle.domain.ids import UuidIdFactory
from smeargle.pipeline import run
from smeargle.store.run_store import RunStore


class StubIdFactory(UuidIdFactory):
    def __init__(self, run_uuid):
        self._run_uuid = run_uuid

    def run_uuid(self):
        return self._run_uuid


@dataclass
class Fixtures:
    document_path: object
    catalog_path: object


def _fixtures(tmp_path):
    document = tmp_path / "spec.txt"
    document.write_text("The system MUST encrypt data at rest.", encoding="utf-8")
    catalog = tmp_path / "vendor.json"
    catalog.write_text(
        json.dumps(
            {
                "catalog": {
                    "name": "V",
                    "securityControls": [
                        {"controlId": "1.1", "title": "Policy", "family": "Access"}
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    return Fixtures(document, catalog)


def test_run_ingestion_records_run_and_counts(tmp_path):
    fixtures = _fixtures(tmp_path)
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    result = run.run_ingestion(
        state_dir=tmp_path / "state",
        output=tmp_path / "out",
        input_paths=[fixtures.document_path],
        catalog_paths=[fixtures.catalog_path],
        settings=Settings.load(),
        clock=clock,
        id_factory=StubIdFactory("run-fixed"),
    )
    assert result.run_id == "run-fixed"
    assert result.document_count == 1
    assert result.control_count == 1
    with RunStore.open(tmp_path / "state") as store:
        row = store.get_run("run-fixed")
    assert row["fingerprint"] == result.fingerprint
    assert row["config_hash"] == result.config_hash
    assert row["status"] == "ingested"


def test_fingerprint_is_content_sensitive_and_config_hash_is_setting_sensitive(tmp_path):
    fixtures = _fixtures(tmp_path)
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    base = run.run_ingestion(
        state_dir=tmp_path / "state",
        output=tmp_path / "out",
        input_paths=[fixtures.document_path],
        catalog_paths=[fixtures.catalog_path],
        settings=Settings.load(),
        clock=clock,
        id_factory=StubIdFactory("run-a"),
    )
    other_config = run.run_ingestion(
        state_dir=tmp_path / "state",
        output=tmp_path / "out",
        input_paths=[fixtures.document_path],
        catalog_paths=[fixtures.catalog_path],
        settings=Settings.load(overrides={"mapping": {"mapped_threshold": 0.9}}),
        clock=clock,
        id_factory=StubIdFactory("run-b"),
    )
    assert other_config.fingerprint == base.fingerprint
    assert other_config.config_hash != base.config_hash

    fixtures.document_path.write_text("The system MUST log access.", encoding="utf-8")
    changed = run.run_ingestion(
        state_dir=tmp_path / "state2",
        output=tmp_path / "out2",
        input_paths=[fixtures.document_path],
        catalog_paths=[fixtures.catalog_path],
        settings=Settings.load(),
        clock=clock,
        id_factory=StubIdFactory("run-c"),
    )
    assert changed.fingerprint != base.fingerprint
```

- [ ] **Step 2: Run the test and see it fail**

Run: `nix develop -c pytest tests/integration/test_run_orchestration.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'smeargle.pipeline.run'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/smeargle/pipeline/run.py`:

```python
"""Orchestrate Stage 0 load and the Stage 2 catalog ingest; stop before any LLM work (spec 10)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from smeargle.config import Settings
from smeargle.domain.clock import Clock
from smeargle.domain.ids import IdFactory, config_hash, fingerprint, sha256_hex
from smeargle.observability import redact
from smeargle.pipeline import index, load
from smeargle.store.run_store import RunStore

_SECRET_SCOPED_KEYS = {"run_id", "force", "yes", "verbose"}


@dataclass(frozen=True, slots=True)
class IngestionResult:
    run_id: str
    fingerprint: str
    config_hash: str
    document_count: int
    catalog_count: int
    control_count: int


def config_snapshot(settings: Settings) -> dict[str, Any]:
    return {
        "llm": settings.llm.model_dump(mode="json"),
        "jev": settings.jev.model_dump(mode="json"),
        "mapping": settings.mapping.model_dump(mode="json"),
        "execution": {
            key: value
            for key, value in settings.execution.model_dump(mode="json").items()
            if key not in _SECRET_SCOPED_KEYS
        },
    }


def compute_fingerprint(input_paths: Iterable[Path], catalog_paths: Iterable[Path]) -> str:
    input_digests = [sha256_hex(Path(p).read_bytes()) for p in input_paths]
    catalog_digests = [sha256_hex(Path(p).read_bytes()) for p in catalog_paths]
    return fingerprint(input_digests, catalog_digests)


def run_ingestion(
    *,
    state_dir: Path,
    output: Path,
    input_paths: Iterable[Path],
    catalog_paths: Iterable[Path],
    settings: Settings,
    clock: Clock,
    id_factory: IdFactory,
    run_id: Optional[str] = None,
) -> IngestionResult:
    input_paths = [Path(p) for p in input_paths]
    catalog_paths = [Path(p) for p in catalog_paths]
    computed_fingerprint = compute_fingerprint(input_paths, catalog_paths)
    computed_config_hash = config_hash(redact(config_snapshot(settings)))
    selected_run_id = run_id or id_factory.run_uuid()

    with RunStore.open(state_dir, clock=clock, id_factory=id_factory) as store:
        store.create_run(selected_run_id, computed_fingerprint, computed_config_hash)
        documents = load.run_load(store, selected_run_id, input_paths)
        catalog_ids = index.ingest_catalogs(
            store,
            selected_run_id,
            catalog_paths,
            output,
            catalog_format=settings.execution.catalog_format,
            clock=clock,
            id_factory=id_factory,
        )
        store.set_run_status(selected_run_id, "ingested", finished=True)
        counts = store.counts(selected_run_id)

    return IngestionResult(
        run_id=selected_run_id,
        fingerprint=computed_fingerprint,
        config_hash=computed_config_hash,
        document_count=len(documents),
        catalog_count=len(catalog_ids),
        control_count=counts["controls"],
    )
```

- [ ] **Step 4: Run the test and see it pass**

Run: `nix develop -c pytest tests/integration/test_run_orchestration.py -v`
Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/smeargle/pipeline/run.py tests/integration/test_run_orchestration.py
git commit -m "feat(pipeline): add ingestion run orchestration and config hashing" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 15: Wire `run`, `validate`, and `status` into the CLI

**Files:**
- Modify: `src/smeargle/cli.py`
- Modify: `tests/unit/test_cli.py`

**Spec traceability:** §12 (shared globals plus `--catalog-format {auto,oscal}`; `run` exits cleanly after ingestion; `validate` validates input catalogs and/or emitted artifacts; `status` shows per-stage progress/counts), §12.2 exit codes, §15 central mapping.

- [ ] **Step 1: Update the failing test**

Replace `tests/unit/test_cli.py` with:

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


def test_extract_reports_not_implemented(capsys):
    code = main(["extract"])
    err = capsys.readouterr().err
    assert code == 2
    assert "not implemented in Phase 2" in err


def test_unknown_option_is_usage_error():
    code = main(["--nope"])
    assert code == 2


def test_run_requires_an_input(tmp_path, capsys):
    code = main(
        ["--state-dir", str(tmp_path / "state"), "--output", str(tmp_path / "out"), "run"]
    )
    assert code == 2
    assert "requires at least one --input" in capsys.readouterr().err


def test_status_without_state_reports_nothing(tmp_path, capsys):
    code = main(["--state-dir", str(tmp_path / "missing"), "status"])
    assert code == 0
    assert "no runs recorded" in capsys.readouterr().out


def test_validate_rejects_invalid_catalog(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"catalog": {"metadata": {"title": "T"}}}', encoding="utf-8")
    code = main(
        ["--state-dir", str(tmp_path / "state"), "validate", "-c", str(bad)]
    )
    assert code == 4
```

- [ ] **Step 2: Run the test and see it fail**

Run: `nix develop -c pytest tests/unit/test_cli.py -v`
Expected: against the **landed Phase 1** `cli.py` (Task 8 of the Phase 1 plan), exactly two of the new tests fail:
- `test_extract_reports_not_implemented` fails because Phase 1's `_not_implemented` raises `UsageError("'<name>' is not implemented in Phase 1")`, so stderr says "Phase 1" rather than the new "Phase 2" text.
- `test_validate_rejects_invalid_catalog` fails because Phase 1's `validate` calls `_not_implemented("validate")` and returns exit code 2, not 4.

Both go green once this task's replacement `cli.py` lands. If Phase 1 is not yet landed, run this step after Phase 1's Task 8.

- [ ] **Step 3: Replace `src/smeargle/cli.py`**

```python
"""Typer CLI, shared globals, and central exit-code mapping (spec 12)."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import typer

from smeargle import __version__
from smeargle.catalog_adapters.registry import parse_catalog
from smeargle.config import Settings
from smeargle.domain.clock import SystemClock
from smeargle.domain.ids import UuidIdFactory
from smeargle.errors import (
    EXIT_ABORTED,
    EXIT_SUCCESS,
    EXIT_UNEXPECTED,
    SmeargleError,
    UsageError,
    exit_code_for,
)
from smeargle.observability import configure_logging
from smeargle.oscal_build import facade
from smeargle.pipeline import run as run_pipeline
from smeargle.store.db import DB_FILENAME
from smeargle.store.run_store import RunStore

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


def _configure_oscal(settings: Settings) -> None:
    facade.configure_support_file(settings.state_dir / "oscal_support.db")


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
    catalog_format: Optional[str] = typer.Option(
        None, "--catalog-format", help="auto or oscal."
    ),
) -> None:
    if version:
        typer.echo(f"smeargle {__version__}")
        raise typer.Exit(code=EXIT_SUCCESS)

    if catalog_format is not None and catalog_format not in {"auto", "oscal"}:
        raise UsageError("--catalog-format must be 'auto' or 'oscal'")

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
    if catalog_format is not None:
        execution["catalog_format"] = catalog_format
    if execution:
        overrides["execution"] = execution

    settings = Settings.load(config_file=config, overrides=overrides)
    configure_logging(settings.execution.log_format, verbose=settings.execution.verbose)
    ctx.obj = settings

    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(code=EXIT_SUCCESS)


def _not_implemented(name: str) -> None:
    raise UsageError(f"'{name}' is not implemented in Phase 2")


@app.command()
def run(
    ctx: typer.Context,
    input: Optional[List[Path]] = typer.Option(None, "-i", "--input", help="Input document."),
    catalog: Optional[List[Path]] = typer.Option(None, "-c", "--catalog", help="Catalog."),
) -> None:
    """Load inputs, ingest catalogs, and stop before the LLM stages."""
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

    _configure_oscal(settings)
    result = run_pipeline.run_ingestion(
        state_dir=settings.state_dir,
        output=settings.output,
        input_paths=input_paths,
        catalog_paths=catalog_paths,
        settings=settings,
        clock=SystemClock(),
        id_factory=UuidIdFactory(),
        run_id=settings.execution.run_id,
    )
    typer.echo(
        f"run {result.run_id}: {result.document_count} document(s),"
        f" {result.catalog_count} catalog(s), {result.control_count} control(s)"
    )
    typer.echo(
        "phase 2: ingestion complete; extraction/index LLM stages are not implemented yet"
    )


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
    if not targets and settings.output is None:
        typer.echo("nothing to validate")
        return
    for path in targets:
        parse_catalog(path, settings.execution.catalog_format)
        typer.echo(f"{path}: valid")
    if settings.output is not None:
        catalogs_dir = settings.output / "catalogs"
        if catalogs_dir.is_dir():
            for path in sorted(catalogs_dir.glob("*.json")):
                facade.validate("catalog", facade.load_document(path))
                typer.echo(f"{path}: valid")


@app.command()
def status(ctx: typer.Context) -> None:
    """Show per-stage progress and counts."""
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


def main(argv: Optional[List[str]] = None) -> int:
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

- [ ] **Step 4: Run the test and see it pass**

Run: `nix develop -c pytest tests/unit/test_cli.py -v`
Expected: `7 passed`.

- [ ] **Step 5: Run the whole suite, lint, and types**

Run:

```bash
nix develop -c pytest -q
nix develop -c ruff check src tests
nix develop -c mypy src
```

Expected: all tests pass; `ruff` reports `All checks passed!`; `mypy` reports `Success: no issues found in ... source files`.

- [ ] **Step 6: Commit**

```bash
git add src/smeargle/cli.py tests/unit/test_cli.py
git commit -m "feat(cli): wire run, validate, and status for ingestion" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Task 16: Spec-driven suitability for run (Phase 2 acceptance)

**Files:**
- Create: `tests/e2e/__init__.py`
- Create: `tests/e2e/test_phase2_run.py`

**Spec traceability:** §10 (Stage 0 + Stage 2 catalog ingest), §7 (every persisted table), §11 (`catalogs/<source-stem>.json`), §12 (`run`/`validate`/`status`), §14 (end-to-end runnable and schema-valid).

This task proves the phase is genuinely runnable, end to end, exactly as an operator would use it: a real CLI invocation with `--state-dir`/`--output` that ingests a sample document and a vendor-shape catalog, persists the store rows, and emits a normalised catalog that validates against the vendored OSCAL 1.2.3 JSON Schema.

- [ ] **Step 1: Write the end-to-end test**

Create `tests/e2e/__init__.py` (empty) and `tests/e2e/test_phase2_run.py`:

```python
import json
import sqlite3

from support.schemas import validate_against_schema

from smeargle.cli import main


def test_phase2_run_ingests_and_emits_valid_catalog(tmp_path):
    document = tmp_path / "spec.txt"
    document.write_text("The system MUST encrypt data at rest.", encoding="utf-8")
    catalog = tmp_path / "vendor.json"
    catalog.write_text(
        json.dumps(
            {
                "catalog": {
                    "name": "Vendor Controls",
                    "securityControls": [
                        {
                            "controlId": "1.1",
                            "title": "Policy",
                            "family": "Access Control",
                            "description": "Establish a policy.",
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    state = tmp_path / "state"
    output = tmp_path / "out"

    code = main(
        [
            "--state-dir",
            str(state),
            "--output",
            str(output),
            "--yes",
            "run",
            "-i",
            str(document),
            "-c",
            str(catalog),
        ]
    )

    assert code == 0

    conn = sqlite3.connect(state / "smeargle.db")
    try:
        run_count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        document_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        catalog_count = conn.execute("SELECT COUNT(*) FROM catalogs").fetchone()[0]
        control_count = conn.execute("SELECT COUNT(*) FROM controls").fetchone()[0]
        assert (run_count, document_count, catalog_count, control_count) == (1, 1, 1, 1)
    finally:
        conn.close()

    emitted = json.loads((output / "catalogs" / "vendor.json").read_text(encoding="utf-8"))
    validate_against_schema("catalog", emitted)
    assert emitted["catalog"]["metadata"]["oscal-version"] == "1.2.3"
```

- [ ] **Step 2: Run the test**

Run: `nix develop -c pytest tests/e2e/test_phase2_run.py -v`
Expected: `1 passed` (all Task 1–15 components are in place).

- [ ] **Step 3: Build and exercise the real binary**

Run each command from the repository root:

```bash
rm -rf .tmp/p2
mkdir -p .tmp/p2/state .tmp/p2/out
printf 'The system MUST encrypt data at rest.\n' > .tmp/p2/spec.txt
cat > .tmp/p2/vendor.json <<'JSON'
{"catalog": {"name": "Vendor Controls", "securityControls": [
  {"controlId": "1.1", "title": "Policy", "family": "Access Control", "description": "Establish a policy."}
]}}
JSON
nix build .#smeargle
./result/bin/smeargle --state-dir .tmp/p2/state --output .tmp/p2/out run -i .tmp/p2/spec.txt -c .tmp/p2/vendor.json
./result/bin/smeargle --state-dir .tmp/p2/state status
./result/bin/smeargle --state-dir .tmp/p2/state validate -c .tmp/p2/vendor.json
ls .tmp/p2/out/catalogs
```

Expected:

- `nix build` exits 0 (the derivation runs the full `pytest` suite plus `pythonImportsCheck`).
- `run` prints a `run <uuid>: 1 document(s), 1 catalog(s), 1 control(s)` line followed by `phase 2: ingestion complete; extraction/index LLM stages are not implemented yet`, and exits 0.
- `status` prints the run id, `ingested`, and non-zero counts.
- `validate` prints `.tmp/p2/vendor.json: valid` and `.tmp/p2/out/catalogs/vendor.json: valid`.
- `ls` shows `vendor.json`.

- [ ] **Step 4: Clean up the acceptance scratch directory**

Run: `rm -rf .tmp/p2`

- [ ] **Step 5: Commit**

```bash
git add tests/e2e/__init__.py tests/e2e/test_phase2_run.py
git commit -m "test(e2e): prove phase 2 ingestion is runnable end to end" -m "Assisted-by: DeepSeek Flash via OpenCode"
```

---

## Appendix A: Commit sequence

| # | Commit message (lowercase, Conventional Commits) |
|---|---|
| 1 | `chore(nix): package oscal and ruf-common via python overlay` |
| 2 | `feat(oscal): add isolated oscal facade` |
| 3 | `test(oscal): vendor 1.2.3 json schemas with offline validator` |
| 4 | `feat(store): add sqlite connection and schema migrations` |
| 5 | `feat(store): add run, stage, and document repository methods` |
| 6 | `feat(store): add catalog, control, and requirement repository methods` |
| 7 | `feat(store): add candidate, evidence, and attempt repository methods` |
| 8 | `feat(loaders): add text and json flattening loaders` |
| 9 | `feat(loaders): add pdf, docx, and registry with rejections` |
| 10 | `feat(catalog-adapters): add id sanitisation and format registry` |
| 11 | `feat(catalog-adapters): add oscal and vendor adapters with normalisation` |
| 12 | `feat(pipeline): add stage 0 document loading` |
| 13 | `feat(pipeline): add catalog ingest and normalised emission` |
| 14 | `feat(pipeline): add ingestion run orchestration and config hashing` |
| 15 | `feat(cli): wire run, validate, and status for ingestion` |
| 16 | `test(e2e): prove phase 2 ingestion is runnable end to end` |

Every commit must carry the `Assisted-by: DeepSeek Flash via OpenCode` trailer as its final line(s).

## Appendix B: Spec traceability matrix

| Test file | Spec requirement(s) |
|---|---|
| `tests/unit/oscal_build/test_facade.py` | §4 facade isolation, §11.6 validation, §16 API churn |
| `tests/unit/test_schema_hashes.py` | §4/§14 vendored official OSCAL 1.2.3 JSON Schemas, hash-pinned |
| `tests/unit/store/test_schema.py` | §7 pragmas, `PRAGMA user_version` migrations, newer-DB refusal, transactions |
| `tests/unit/store/test_run_store.py` | §7 runs/documents/stage_runs/requirements/catalogs/controls/domain_index/candidate_pairs/mappings/evidence/attempts; derived work; pre-gate candidates; `retrieve_status` and `classify_status` terminal markers; at-least-once redacted compressed evidence |
| `tests/unit/loaders/test_text.py` | §9.1 encoding/BOM normalisation |
| `tests/unit/loaders/test_json_text.py` | §9.1 deterministic JSON flattening rule |
| `tests/unit/loaders/test_registry.py` | §9.1 PDF/DOCX registry, scanned-PDF and `.doc` rejection, media detection |
| `tests/unit/catalog_adapters/test_ids.py` | §9.2 `TokenDatatype`-safe control-id sanitisation |
| `tests/unit/catalog_adapters/test_adapters.py` | §9.2 standard + vendor adapters, `original-id`/source-document props, normalised catalog shape |
| `tests/unit/test_dependency_direction.py` | §4 only `facade.py` imports `oscal` |
| `tests/integration/test_load_stage.py` | §10 Stage 0 load, dedup, canonical ordering |
| `tests/integration/test_normalised_catalog.py` | §14 emitted catalog validates against vendored JSON Schema |
| `tests/integration/test_ingest_pipeline.py` | §10 Stage 2 ingest, §9.2 duplicate-id fail-fast, §11 stem-collision fail-fast |
| `tests/integration/test_run_orchestration.py` | §7.1 fingerprint order-independence/content-sensitivity, `config_hash` setting-sensitivity, §12 run record |
| `tests/e2e/test_phase2_run.py` | §10/§11/§12/§14 runnable end-to-end CLI, valid emitted catalog |
