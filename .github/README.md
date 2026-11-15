<div align="center">

# smeargle

**The painter that reads the world and paints it onto the canvas of compliance.**

> **AI-assisted work.** This package was written explicitly with AI assistance,
> by halogen-qwen3.8-flash-next via OpenCode, and every commit carries an
> `Assisted-by` trailer.

[![Python][python-badge]][python-link]
[![Nix Flakes][nix-badge]][nix-link]
[![Typer][typer-badge]][typer-link]
[![Pydantic v2][pydantic-badge]][pydantic-link]
[![httpx][httpx-badge]][httpx-link]
[![SQLite][sqlite-badge]][sqlite-link]
[![OSCAL][oscal-badge]][oscal-link]
[![pytest][pytest-badge]][pytest-link]
[![Ruff][ruff-badge]][ruff-link]
[![mypy][mypy-badge]][mypy-link]
[![License: GPL-3.0][license-badge]][license-link]

</div>

## The artist

> **Category:** Painter. **Behaviour:** wanders the world painting what it
> sees, marking its territory with art drawn from its own tail. It does not
> invent what it paints; it interprets it. **Habitat:** wherever unstructured
> documentation collects.

This `smeargle` is that artist for security and compliance. The raw world it
studies is your documentation: policies, standards and contracts, in PDFs,
DOCX files, JSON and Markdown of unknown and arbitrary structure. Within that
world it finds the normative vision, every `MUST`, `SHALL`, `SHOULD` and
`REQUIRED` statement, the RFC 2119 obligations that actually bind you. Then it
maps every requirement onto the controls of one or more
[OSCAL](https://pages.nist.gov/OSCAL/) control catalogs, choosing where each
stroke belongs, and paints the finished work: a coherent, validated set of
OSCAL 1.2.3 artifacts. Every brushstroke is recorded as evidence, every canvas
can be resumed mid-painting, and the gallery accepts nothing that fails
validation.

## What smeargle does

`smeargle` is a Python CLI that:

1. Ingests an arbitrary number of source documents (PDF, DOCX, JSON,
   text/Markdown) of unknown structure, plus one or more target control
   catalogs (standard OSCAL, or non-OSCAL "container" shapes which are
   normalised behind the scenes).
2. Extracts RFC 2119 normative requirements from the documents. Each candidate
   is proposed by an LLM, then gated by a JEV-style System 1 decision engine
   for authenticity and keyword classification.
3. Maps every accepted requirement to candidate controls (LLM retrieval),
   verifies each candidate pair (JEV `noul` probability gate) and classifies
   the confirmed pairs with an OSCAL relationship (`equivalent-to`, `equal-to`,
   `subset-of`, `superset-of`, `intersects-with`).
4. Emits a complete, schema-validated OSCAL 1.2.3 output set, plus a
   human/audit-facing rationale and full raw call evidence.

It never runs or hosts a model. It speaks HTTP to whatever endpoints you point
it at: a local llama.cpp server, OpenRouter, or any OpenAI-compatible LLM for
proposal/retrieval, and a [Laya](https://github.com/NandhaKishorM/laya)
SystemOne-style JEV endpoint for decisions.

## The canvas

| Input | Output (`--output DIR`) |
|---|---|
| `-i` documents: PDF, DOCX, JSON, text/Markdown | `requirements-catalog.json`: OSCAL catalog of extracted requirements, grouped per source document |
| `-c` catalogs: OSCAL or non-OSCAL container JSON | `profile.json`: OSCAL tailoring profile importing every catalog, with per-requirement mapping props |
| LLM endpoint (OpenAI-compatible) | `mapping-collection.json`: OSCAL control mappings with confidence percentages |
| JEV endpoint (chat decisions, or legacy Laya SystemOne) | `rationale.json`: the audit record of gates, confidences, unmapped/rejected reasons |
| | `catalogs/<source-stem>.json`: normalised OSCAL catalogs (one per input) |
| | `evidence/`: every raw redacted LLM/JEV request/response |

## How it paints

A single process executes a linear stage pipeline over a SQLite RunStore.
Each stage is idempotent and resume-safe: outstanding work is derived from the
store rather than tracked as a mutable to-do list. HTTP work fans out to a
thread pool; all writes are serialised through a single writer.

```
CLI (subcommand)
  → resolve config (defaults → file → env → CLI flags)
  → RunStore.open(state_dir)
  → content fingerprint + config_hash (resume decision)
  → run stages:

      0 load ──► inputs → Documents (ledger)
      1 extract ┐ (run concurrently — disjoint data)
      2 index   ┘
          extract:  Documents → Requirements   (LLM propose → JEV gate)
          index:    catalogs → Controls + DomainIndex (cached cross-run)
      3 retrieve ─► Requirement → candidate Controls (LLM domain pick + nomination)
      4 verify   ─► (Requirement, Control) → JEV noul → passed/rejected
      5 classify ─► passed pair → JEV choice → OSCAL relationship + confidence
      6 assemble ─► pure function of the ledger → OSCAL artifacts

  → integrity gate (validate everything, fail the run on violation)
  → write outputs/ + export evidence
```

### The two brushes: two models, two jobs

The pipeline uses two kinds of model for two kinds of work. One reads and
proposes; the other decides. The two jobs want different architectures,
outputs and guarantees, which is why they run on different models.

#### The generative LLM: reading and recall (System 2)

**Intent.** Turn arbitrary, unstructured source material into proposals. The
inputs are PDFs, DOCX files, JSON blobs and Markdown of unknown structure; the
job is to read them and surface everything that looks like a requirement, then
propose where those requirements might belong in a catalog.

**What it does, specifically:**

- Extracts candidate RFC 2119 requirements from each document chunk.
- Builds a domain/family index over every control in each catalog.
- Picks the plausible domain(s) for a requirement, then nominates candidate
  controls within them.

**Why a generative LLM is the right tool for this half.** The input is
arbitrary and unstructured. Deterministic parsing (regex for `MUST`/`SHOULD`,
fixed schema walks) is brittle: it cannot generalise across document layouts,
it misses paraphrased obligations, and it cannot judge whether a sentence is a
genuine, actionable requirement or just descriptive prose. Only a language
model's open-ended reading generalises across the whole zoo of inputs. The LLM
is used as a high-recall proposer: it casts a wide net and is expected to
over-generate. It runs with `temperature=0`, structured output, a bounded
validate-and-repair loop, and prompt-injection fencing around untrusted
document content. Its output is candidates, never verdicts.

#### The decision model: judgement and precision (System 1 / classifier)

**Intent.** Take the LLM's wide net of proposals and decide. Every externally
visible claim the tool makes is a small, bounded question with a defined answer
set: *"Is this a genuine requirement?"*, *"Does this requirement relate to this
control?"*, *"Which RFC 2119 keyword is it?"*, *"Which OSCAL relationship
holds?"*. These are classification problems, so a classification model answers
them, not the generative model.

**What it does.** The JEV endpoint answers typed questions over HTTP:

- `noul`: a binary yes/no probability. Used as the authenticity gate at
  extraction (against `--extract-gate-threshold`) and the relatedness gate at
  verification (against `--mapped-threshold`). For a `noul` answer the returned
  probability is the answer confidence.
- `choice`: a multiclass decision over a fixed option set, returning a label
  plus an answer confidence. Used to confirm the RFC 2119 keyword (over the
  nine normative levels) and to pick the OSCAL relationship (over the five
  positive relationship values).

**Why a decision-one (classifier) model makes sense here.**

1. The task shape is classification, not generation. The pipeline reduces to
   many small, well-posed questions, hundreds to thousands of them per run
   (398, 321 and 590 candidate pairs in the sample runs below). A classifier is
   built for exactly that: a fixed question in, one of a fixed set of answers
   out.
2. Calibrated confidence you can threshold. `noul` returns a probability the
   pipeline compares against a tunable threshold (default 0.50) to accept or
   reject, which gives a principled, auditable gate. A generative LLM emits
   prose, and thresholding its text is guesswork.
3. A classifier cannot hallucinate a mapping. A decision engine is
   encoder-based (Laya is a ModernBERT-style encoder): it selects among the
   options it is given and cannot invent a requirement, a control id, or an
   `href` that was not in its inputs. The generative LLM can, which is why its
   output is never trusted as a verdict.
4. Determinism and auditability. The same question yields the same typed
   answer, and that answer is machine-checkable rather than prose needing to be
   parsed after the fact. A compliance mapping must be reproducible and
   defensible.
5. Speed and cost at volume. The decision step runs over every candidate pair;
   a small, fast decision model is far cheaper and lower-latency than a large
   generative model across that many calls.
6. A closed decision space. The classifier is only ever offered the valid
   options: the nine normative RFC 2119 keywords and the five positive OSCAL
   relationships. `no-relationship` is deliberately not offered at
   classification time, because a pair only reaches that stage after the
   relatedness gate already asserted it is related.

Because nothing is emitted unless it survives the classifier gate, the split
between the two models is a safety measure as well as an efficiency one.

### The easel: RunStore

- One SQLite database per `--state-dir` (`WAL`, `synchronous=NORMAL`,
  single-writer thread), storing runs, documents, requirements, catalogs,
  controls, a cross-run domain index, candidate pairs, mappings, attempts,
  evidence and per-stage cursors.
- Content-addressed runs: the run fingerprint is a salted, order-independent
  hash of input and catalog bytes; a separate `config_hash` covers endpoints,
  models, prompts and thresholds. Resuming across a config change prompts for
  an explicit decision (resume / new / cancel); with `--yes` or in a
  non-interactive session it auto-resumes with a printed warning rather than
  silently.
- At-least-once evidence: every request is persisted (redacted, compressed)
  before the call and annotated with the response after; interrupted work is
  re-issued on resume. Deterministic resume issues zero new external calls for
  completed work.
- Deterministic assembly: frozen clock, UUIDv5 identifiers, content-sorted
  emission. Re-assembling the same stored ledger yields byte-identical
  artifacts (proven by test).
- Retry with exponential backoff, jitter and `Retry-After` respect; retries
  only on idempotent-safe conditions (connection/timeout/408/429/5xx). Per-item
  failures are recorded and the run continues; fatal service failures (auth
  rejected, endpoint unreachable) abort with a distinct exit code.

## Running the artist

### Build

```bash
nix build .#smeargle          # produces ./result/bin/smeargle
nix flake check               # runs the test suite as the flake check
```

The flake builds for `x86_64-linux` and `aarch64-linux` and provides
`packages`, `overlays`, `devShells`, `checks` and `apps` outputs.

### Run

```bash
./result/bin/smeargle \
  --state-dir ./.smeargle --output ./out \
  --llm-base-url https://openrouter.ai/api/v1 \
  --llm-model liquid/lfm-2.5-2.6b:free \
  --llm-auth-file ./.secrets/llm-token \
  --jev-base-url http://127.0.0.1:8080 \
  --jev-model laya --yes \
  run -i ./example-policy.md -c ./pci-dss-4.json
```

- `--llm-base-url` accepts any OpenAI-compatible `/v1/chat/completions` endpoint.
- `--jev-base-url` accepts a Laya SystemOne server; `--jev-model` names the
  checkpoint that server exposes (e.g. an `english` alias).
- Secrets come from `--*-auth-file` or `--*-api-key-env` only, never CLI
  tokens, and are redacted before persistence.

### Subcommands

| Command | Purpose |
|---|---|
| `run` | Full pipeline (Stages 0-6) |
| `extract` | Extract requirements only (Stages 0-1) |
| `map` | Map an existing run's requirements to catalogs (Stages 2-6) |
| `resume` | Continue an interrupted run |
| `validate` | Validate input catalogs and/or emitted artifacts |
| `status` | Show per-stage progress, counts and emitted artifacts |

Key options: repeatable `-i/--input` and `-c/--catalog`, `--catalog-format
{auto,oscal}`, `--config` (TOML/YAML), `--log-format {text,json}`, tuning knobs
(`--extract-gate-threshold` 0.50, `--mapped-threshold` 0.50, `--category-high`
0.80, `--category-medium` 0.50, `--nomination-cap`, `--concurrency`,
`--jev-transport {chat,systemone}`, JEV batching via
`--jev-batch/--no-jev-batch`, `--jev-batch-size`,
`--jev-min-confidence`). Configuration precedence: CLI flags > environment
(`SMEARGLE_*`) > config file > defaults.

### Examples

Assuming `smeargle` on `PATH` (or `./result/bin/smeargle`):

**Extract only**: pull requirements from several documents without mapping.

```bash
smeargle --llm-base-url https://openrouter.ai/api/v1 --llm-auth-file ./.secrets/llm-token \
  --jev-base-url http://127.0.0.1:8731/v1 --output out/ --yes \
  extract -i policy.pdf -i standard.docx
```

**Map an existing run** to an additional catalog, reusing the stored extraction.

```bash
smeargle --llm-base-url https://openrouter.ai/api/v1 --llm-auth-file ./.secrets/llm-token \
  --jev-base-url http://127.0.0.1:8731/v1 --output out/ --run-id run-e2e --yes \
  map -c csa-ccm-301.json
```

**Resume** an interrupted run from its checkpoint. Completed work issues zero
new external calls.

```bash
smeargle --llm-base-url https://openrouter.ai/api/v1 --llm-auth-file ./.secrets/llm-token \
  --jev-base-url http://127.0.0.1:8731/v1 --output out/ --run-id run-e2e --yes resume
```

**Validate** input catalogs and emitted artifacts against the OSCAL schemas.

```bash
smeargle --output out/ validate -c NIST_SP-800-53_rev5_catalog.json
```

**Status**: inspect recorded runs, per-stage progress and emitted artifacts.

```bash
smeargle --state-dir ./.smeargle --output out/ status
```

**JEV transport selection**: `chat` (the default) speaks the chat-completions
decisions wire; `systemone` selects the legacy Laya protocol.

```bash
smeargle ... --jev-base-url http://127.0.0.1:8731/v1 --jev-transport chat ...
smeargle ... --jev-base-url http://127.0.0.1:8080 --jev-transport systemone ...
```

**Config file + environment**: stable settings in TOML, secrets via env only.

```toml
# smeargle.toml
[llm]
base_url = "https://openrouter.ai/api/v1"
model = "liquid/lfm-2.5-2.6b:free"
[jev]
base_url = "http://127.0.0.1:8731/v1"
```

```bash
SMEARGLE_LLM__API_KEY_ENV=OPENROUTER_API_KEY \
  smeargle --config smeargle.toml --output out/ --yes \
  run -i example-policy.md -c pci-dss-4.json
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success, no gaps |
| 1 | Unexpected error |
| 2 | Usage/config error |
| 3 | Input/load error (unsupported media, scanned PDF, legacy `.doc`) |
| 4 | Catalog error (duplicate ids, invalid OSCAL) |
| 5 | External service unreachable/auth-rejected (fatal) |
| 6 | Completed with gaps: artifacts still written, gaps stamped in rationale |
| 7 | Post-assembly integrity/validation failure |
| 8 | Aborted by user |

## Outcomes: what the tooling has produced

Real end-to-end runs against full production catalogs. These outputs live in
the development working tree only; the run artifacts, the sample inputs and
the sample catalogs are deliberately not committed to git:

| Run | Target catalog | Requirements proposed | Accepted | Candidate pairs | Mappings | Unmapped | Evidence records |
|---|---|---:|---:|---:|---:|---:|---:|
| `out/` | NIST SP 800-53 rev.5 | 90 | 46 | 398 | 337 | 0 | 1,919 |
| `pci-out/` | PCI DSS v4.0 | 68 | 37 | 321 | 296 | 17 | 2,655 |
| `csa-ccm-out/` | CSA CCM 3.0.1 | 101 | 53 | 590 | 438 | 0 | 1,389 |

Each run emits the complete artifact set (`requirements-catalog.json`,
`profile.json`, `mapping-collection.json`, `rationale.json`, normalised
`catalogs/`, and the `evidence/` export) and passes the OSCAL 1.2.3 integrity
gate: every accepted requirement is accounted for in a mapping, a gap summary,
or the run-level unmapped list.

Engineering outcomes:

- 347 automated tests (unit, client integration via `respx`, end-to-end
  subprocess runs against in-thread HTTP fakes, determinism, resume and
  adversarial fakes), green via `nix build` / `nix flake check`, with `ruff`
  reporting no issues.
- Byte-identical determinism proven by test: re-assembling a stored ledger
  reproduces the exact artifacts.
- Resume correctness proven by test: killing a run between stages and resuming
  issues zero new external calls for completed work.
- Wire-contract hardening: the JEV client was corrected against the real Laya
  SystemOne server (keyed questions and corrected wire shape), and the LLM
  client's schema-instruction ordering was fixed, after live smoke runs
  surfaced the mismatches.
- Non-OSCAL ingestion proven: the PCI DSS and CSA CCM runs both used non-OSCAL
  vendor catalogs normalised through the adapter layer into valid OSCAL.

## Design decisions worth knowing

- No asyncio. Synchronous HTTP (the official `openai` SDK and `httpx`) in a
  `ThreadPoolExecutor` over a single-writer WAL store: simpler, deterministic,
  and sufficient for the I/O-bound fan-out.
- Work is derived, never a mutable ledger. Outstanding items are SQL queries
  over terminal statuses, so crash-resume is trivially correct.
- Rejected candidates are retained, never deleted. They are evidence for the
  rationale, but excluded from downstream stages.
- Fail fast on collisions (duplicate control ids across catalogs, duplicate
  output stems) rather than silently overwriting art.
- The `oscal` library is isolated behind `oscal_build/facade.py`, a young,
  fast-moving dependency contained to a single module.
- Domain layer is pure: frozen stdlib dataclasses, no Pydantic, no I/O;
  dependency direction is enforced by a test.

## Development

```bash
nix develop                      # Python + pytest + ruff + mypy on PATH
nix develop -c pytest -q         # run the suite
nix develop -c ruff check src tests
nix develop -c mypy src
nix build .#smeargle             # build the CLI
```

The layout is a PEP 621 `src/` project (`src/smeargle/`) with modules for
`domain`, `loaders`, `catalog_adapters`, `clients`, `store`, `pipeline`,
`oscal_build`, `prompts`, `config`, `errors` and `observability`, plus a
`tests/` tree of unit, integration and e2e layers with shared fakes and vendored
OSCAL 1.2.3 schemas.

## License

[GPL-3.0](../LICENSE)

<!-- Badge links -->
[python-badge]: https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white
[python-link]: https://www.python.org/
[nix-badge]: https://img.shields.io/badge/nix-flakes-5277C3?logo=nixos&logoColor=white
[nix-link]: https://nixos.org/
[typer-badge]: https://img.shields.io/badge/typer-CLI-teal
[typer-link]: https://typer.tiangolo.com/
[pydantic-badge]: https://img.shields.io/badge/pydantic-v2-E92063?logo=pydantic&logoColor=white
[pydantic-link]: https://docs.pydantic.dev/
[httpx-badge]: https://img.shields.io/badge/httpx-sync%20client-009688
[httpx-link]: https://www.python-httpx.org/
[sqlite-badge]: https://img.shields.io/badge/sqlite-WAL%20store-003B57?logo=sqlite&logoColor=white
[sqlite-link]: https://sqlite.org/
[oscal-badge]: https://img.shields.io/badge/OSCAL-1.2.3-215287
[oscal-link]: https://pages.nist.gov/OSCAL-Reference/models/v1.2.3/
[pytest-badge]: https://img.shields.io/badge/pytest-347%20passed-0A9EDC?logo=pytest&logoColor=white
[pytest-link]: https://docs.pytest.org/
[ruff-badge]: https://img.shields.io/badge/ruff-lint%20%2B%20format-261230?logo=ruff&logoColor=white
[ruff-link]: https://docs.astral.sh/ruff/
[mypy-badge]: https://img.shields.io/badge/mypy-static%20types-1A5DAB
[mypy-link]: https://mypy-lang.org/
[license-badge]: https://img.shields.io/badge/license-GPL--3.0-blue
[license-link]: ../LICENSE
