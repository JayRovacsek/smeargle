# smeargle — Design

- **Date:** 2026-10-01
- **Status:** Approved (brainstorming complete; ready for implementation planning)
- **Scope:** A Python CLI that ingests an arbitrary number of source documents,
  extracts RFC 2119 requirements from them, maps those requirements to one or
  more OSCAL control catalogs, and emits valid OSCAL 1.2.3 artifacts.

## 1. Purpose and scope

`smeargle` takes an arbitrary number of inputs (PDF, DOCX, JSON, plain
text/Markdown) of unknown structure and one or more target control catalogs, and
produces a single coherent set of OSCAL 1.2.3 outputs that map the extracted
requirements to the controls.

In scope:

- Document ingestion with a pluggable loader registry.
- Catalog ingestion with a pluggable adapter registry (standard OSCAL **and**
  non-OSCAL container catalogs).
- Requirement extraction using a traditional LLM endpoint, gated by a JEV-style
  (System 1 decision engine) endpoint.
- Requirement-to-control mapping using an LLM prefilter plus JEV verification
  and relationship classification.
- Resumable, checkpointed runs backed by SQLite, with full evidence retention.
- Emitting OSCAL `catalog`, `profile`, and `mapping-collection` documents plus a
  non-OSCAL process record.

Out of scope for v1:

- Running or hosting any model. `smeargle` only calls external HTTP endpoints.
- OCR of scanned/image-only PDFs (rejected with an actionable error).
- Legacy binary `.doc` (rejected with an actionable error; use `.docx`/PDF).
- Control-id namespacing for colliding catalogs (v1 fails fast instead).

### Normative references

- RFC 2119 / RFC 8174 (`MUST`, `SHOULD`, `MAY`, …).
- OSCAL 1.2.3: catalog, profile, and control-mapping models
  (<https://pages.nist.gov/OSCAL-Reference/models/v1.2.3/>).
- Laya SystemOne HTTP API (`POST /v1/systemone`, `POST /v1/systemone/batch`) as
  the reference JEV-compatible wire protocol.

## 2. Glossary

| Term | Meaning |
|---|---|
| Requirement | A single normative statement extracted from a source document, labelled with its RFC 2119 level. |
| Control | A single control from an input catalog, normalised into the internal `Control` model. |
| Catalog adapter | Normalises a standard or non-OSCAL catalog into the internal `Control` model. |
| JEV | A System 1 decision engine (Laya-style) called over HTTP; returns typed answers (`noul`, `choice`, …). |
| Run | One content-addressed processing identity over a set of inputs and catalogs. |

## 3. High-level architecture

A single process executes a linear **stage pipeline** over a SQLite **RunStore**.
Each stage is idempotent and resume-safe: it derives the outstanding work from
the store, processes it, and writes results back. The orchestrator owns the only
database writer; HTTP work fans out to a thread pool.

```
CLI (subcommand)
  → resolve config (defaults → file → env → CLI flags)
  → RunStore.open(state_dir)
  → compute content fingerprint (+ config_hash)
  → resume decision (explicit --run-id, or prompt on fingerprint match)
  → run stages:
        load          inputs → Document[]                          (ledger)
        extract ‖ index   (run concurrently — independent streams)
            extract   Document[] → Requirement[]  (LLM propose → JEV gate)
            index     catalogs → normalised Control[] + DomainIndex
        retrieve      Requirement → candidate Control[]
        verify        (Requirement, Control) → JEV noul
        classify      confirmed pair → JEV choice (OSCAL relationship)
        assemble      pure function of ledger → artifacts
  → integrity gate (validate everything)
  → write outputs/ + export evidence
```

Stages 1 (`extract`) and 2 (`index`) operate on disjoint data (inputs versus
catalogs) and **run concurrently** as two work-streams. All writes are
serialised through the orchestrator.

## 4. Repository and module layout

```
flake.nix
overlays/default.nix
package/oscal/default.nix
package/ruf-common/default.nix
pyproject.toml                 # PEP 621, src layout, console script
src/smeargle/
  __init__.py  __main__.py
  cli.py                       # Typer app; subcommands; config merge
  config.py                    # Pydantic Settings; TOML/YAML/env/CLI
  errors.py                    # typed errors → exit codes
  observability.py             # logging, progress, redaction
  domain/                      # frozen stdlib dataclasses; no Pydantic, no I/O
    clock.py ids.py documents.py requirements.py controls.py
    mapping.py run.py
  prompts/                     # versioned templates + PROMPT_HASH
    extraction.py indexing.py retrieval.py
  loaders/                     # document loaders
    registry.py pdf.py docx.py json_text.py text.py
  catalog_adapters/            # catalog loaders/adapters
    registry.py oscal.py vendor_security_controls.py
  clients/
    ports.py                   # Protocols (LLMClient, JevClient)
    dto.py                     # Pydantic v2 wire models (boundary only)
    http.py retry.py llm.py jev.py
  store/
    db.py schema.py run_store.py
  pipeline/
    work.py load.py extract.py index.py retrieve.py verify.py
    classify.py assemble.py run.py
  oscal_build/
    facade.py                  # ONLY module importing `oscal`
    emit.py requirements_catalog.py profile.py mapping.py rationale.py
tests/
  conftest.py fakes/ schemas/oscal-1.2.3/ unit/ integration/ e2e/
```

**Dependency direction** (enforced by a test):

```
cli → config / pipeline / clients / store → domain
oscal_build → domain (only)
domain → (nothing project-internal)
```

No Pydantic in `domain/` or `oscal_build/`. `oscal_build/facade.py` is the only
module that imports `oscal`.

## 5. Domain model

Frozen, hashable stdlib dataclasses; no I/O, no serialisation behaviour.

- `Document(run_id, doc_id, ordinal, path, uri, external_id, media_type,
  content_sha256, size_bytes, text)`
- `Requirement(run_id, req_id, doc_id, ordinal, text, normalized_text, keyword,
  extract_status, gate_status, gate_noul_prob, gate_choice, retrieve_status)`
- `Control(run_id, catalog_id, control_id, title, text, domain, family, path)`
- `DomainIndex(index_id, content_sha256, model_id, prompt_hash,
  domains: mapping[str, list[str]])` (content-keyed, cross-run)
- `CandidatePair(run_id, pair_id, req_id, catalog_id, control_id,
  verify_status, noul_prob)`
- `MappingRecord(run_id, req_id, catalog_id, control_id, relation,
  confidence_percentage, confidence_category)`

Identity is run-scoped: `doc_id`, `req_id`, `pair_id`, and mapping UUIDs are
derived from content and are not globally unique across runs, so every
run-scoped table is keyed by `(run_id, id)`. Derivations: `doc_id = sha256(raw
bytes)`; `catalog_id = sha256(raw catalog bytes)`;
`req_id = "req-" + sha256(doc_content_sha256 ‖ normalised_text)`;
`pair_id = sha256(req_id ‖ catalog_id ‖ control_id)`; `map_uuid =
uuid_for("map", f"{run_id}:{req_id}:{catalog_id}:{control_id}")`;
`index_id = sha256(content_sha256 ‖ model_id ‖ prompt_hash)`. `run_id` is a fresh
`IdFactory.run_uuid()` issued per run and is distinct from `fingerprint` (content
identity), so a new or `--force` run over identical content gets its own rows.
Artifact UUIDs are run-stable but run-specific.

Every emitted OSCAL identifier is `TokenDatatype`-safe (must start with a letter
or `_`): requirement control ids use `req_id` (already `req-`-prefixed) and
source-document group ids use `doc-<doc_id>`. The internal `doc_id`/`catalog_id`/
`pair_id` hex digests are never emitted directly.
- `RunFingerprint`, `RunConfig` (effective; secrets redacted), `config_hash`

The store rows carry additional status/evidence columns (e.g. `classify_status`,
`relation`, confidence values) that the in-flight dataclasses do not: the store
is the durable ledger, while the dataclasses are the values passed between
stages.

Enums:

- `Keyword` — normative RFC 2119 levels only: `MUST`, `MUST_NOT`, `SHALL`,
  `SHALL_NOT`, `REQUIRED`, `SHOULD`, `SHOULD_NOT`, `RECOMMENDED`,
  `NOT_RECOMMENDED`. (`MAY`/`OPTIONAL` are excluded.)
- `Relationship` — the six OSCAL values: `equivalent-to`, `equal-to`,
  `subset-of`, `superset-of`, `intersects-with`, `no-relationship`.

Protocols (injected for determinism and testing):

- `Clock.now_utc() -> datetime` — timezone-aware UTC; frozen to the run's
  `created_at` for all artifact timestamps.
- `IdFactory.uuid_for(kind, stable_key) -> str` (UUIDv5) and `.run_uuid()` —
  stable, reproducible OSCAL UUIDs.

## 6. Configuration

`config.py` (Pydantic Settings). Precedence: **CLI flags > environment
(`SMEARGLE_*`) > TOML/YAML file (`--config`) > defaults**.

Groups:

- Paths: `inputs`, `catalogs`, `output`, `state_dir`
  (default `./.smeargle/`, git-ignored).

Path requiredness is per subcommand: `run` requires `inputs`, `catalogs`, and
`output`; `extract` requires `inputs` and `output` (no catalogs needed); `map`
requires `catalogs`, `output`, and a run selector; `resume` requires a run
selector; `validate` acts on whatever inputs/catalogs/artifacts it is given.
- `llm`: endpoint, model, auth (`--llm-auth-file` / `--llm-api-key-env`),
  timeout, retries, temperature (default 0; folded into `config_hash`),
  structured-output mode.
- `jev`: endpoint, model, auth, timeout, retries, `batch` (default off),
  `batch_size` (≤ 64), `min_confidence` (default off), `max_len`,
  `head_max_len`.
- Mapping: `extract_gate_threshold` (0.50), `mapped_threshold` (0.50),
  `category_high` (0.80), `category_medium` (0.50), `nomination_cap` (0 =
  disabled; retained as a safety valve for very large runs).
- Execution: `concurrency` (4), chunk sizes, `log_format` (`text`/`json`),
  gap handling, `run_id`, `force`, `catalog_format` (`auto`/`oscal`).

Secrets are supplied only via environment or auth files, never as plain CLI
tokens, and are redacted before any persistence.

## 7. RunStore (SQLite)

One SQLite file per `--state-dir`. Pragmas: `journal_mode=WAL`,
`synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=5000`. Migrations use
`PRAGMA user_version` with ordered scripts; the binary refuses to open a
database newer than itself.

Tables:

- `runs(run_id PK, fingerprint, config_hash, status, oscal_version, created_at,
  updated_at, finished_at)` + index `(fingerprint, created_at DESC)`
- `documents((run_id, doc_id) PK, ordinal, path, uri, external_id, media_type,
  content_sha256, size_bytes, status, error, loaded_at,
  UNIQUE(run_id, content_sha256), UNIQUE(run_id, ordinal))`
- `requirements((run_id, req_id) PK, doc_id, ordinal, text, normalized_text,
  keyword, extract_status, gate_status, gate_noul_prob, gate_choice,
  retrieve_status, UNIQUE(run_id, doc_id, normalized_text))`
  - `retrieve_status ∈ {nominated, none}` (`NULL` = not yet retrieved):
    `nominated` once Stage 3 emitted at least one candidate pair, `none` when
    retrieval found no plausible control. `none` is the terminal marker for an
    unmapped requirement.
- `catalogs((run_id, catalog_id) PK, ordinal, uri, path, external_id,
  content_sha256, oscal_version, status)`
- `controls((run_id, catalog_id, control_id) PK, title, text, domain, family,
  path)`
- `domain_index(index_id PK, content_sha256, model_id, prompt_hash, index_json,
  UNIQUE(content_sha256, model_id, prompt_hash))`
  - Deliberately keyed without `run_id`: the domain index is an expensive,
    deterministic parse of a catalog, cached across runs and reused only when
    `content_sha256`, model, and prompt hash all match.
- `candidate_pairs((run_id, pair_id) PK, req_id, catalog_id, control_id,
  verify_status, noul_prob, mapped_threshold, classify_status, relation,
  confidence_percentage, confidence_category,
  UNIQUE(run_id, req_id, catalog_id, control_id))`
  - `verify_status`: inserted by Stage 3 as `'pending'`; Stage 4 sets `'passed'`
    or `'rejected'` (terminal).
  - `classify_status`: `NULL` at insert (not yet classified); Stage 5 sets
    `'done'` (positive relationship chosen), `'unmapped'` (`no-relationship` or
    unparseable), or `'skipped'` (suppressed by the reliability gate). All
    terminal; Stage 5 work = `verify_status='passed' AND classify_status IS
    NULL`.
- `mappings((run_id, map_uuid) PK, req_id, catalog_id, control_id, relation,
  confidence_percentage, confidence_category, rationale,
  UNIQUE(run_id, req_id, catalog_id, control_id))`
- `attempts(attempt_id PK, run_id, stage, item_ref, call_type, attempt_no,
  http_status, error_class, error, duration_ms, created_at)`
- `evidence(evidence_id PK, run_id, stage, item_ref, call_type,
  request_json [compressed + redacted], response_json [compressed + redacted],
  request_sha256,
  http_status, attempt_no, prompt_hash, created_at,
  UNIQUE(run_id, item_ref, call_type, request_sha256))`
- `stage_runs((run_id, stage) PK, status, cursor, started_at, finished_at,
  error)`

Rules:

- **Work is derived, never a mutable ledger.** E.g.
  `requirements WHERE run_id=? AND gate_status IS NULL` (extract gate);
  `requirements WHERE run_id=? AND gate_status='passed' AND retrieve_status IS
  NULL` (Stage 3 retrieval);
  `candidate_pairs WHERE run_id=? AND verify_status='pending'` (Stage 4 verify);
  `candidate_pairs WHERE run_id=? AND verify_status='passed' AND
  classify_status IS NULL` (Stage 5 classify).
- **All proposed candidates are persisted before the gate.** Stage 1 inserts
  every LLM-proposed candidate as a `requirements` row with
  `extract_status='proposed'` and `gate_status=NULL`; the JEV gate then sets
  `gate_status ∈ {passed, rejected}`. Rejected rows are retained (never deleted)
  as gap/rationale evidence but excluded from Stage 3 by the
  `gate_status='passed'` filter.
- Stage 3 sets `requirements.retrieve_status` to `nominated` or `none` in the
  same transaction that writes its candidate pairs, so a crash cannot lose the
  outcome.
- `stage_runs.status='complete'` short-circuits a finished stage.
- Unmapped requirements are recorded via `retrieve_status='none'` (no candidates)
  or by all their candidate pairs being `verify_status='rejected'`,
  `classify_status='unmapped'`, or `classify_status='skipped'`; all are terminal,
  so resume never retries them.
- **Evidence is at-least-once:** persist the request (redacted) and a pending
  row before the call, write the response after; on resume, pending calls are
  re-issued and annotated.

### 7.1 Run fingerprint

Content only, order-independent, version-salted:

```
h = sha256(); h.update(b"smeargle-run/1\0")
for d in sorted(sha256_file(p) for p in inputs):  h.update(d.encode() + b"\0")
h.update(b"|")
for d in sorted(sha256_file(p) for p in catalogs): h.update(d.encode() + b"\0")
fingerprint = h.hexdigest()
```

A separate `runs.config_hash` covers endpoints, model ids, prompt hashes,
thresholds, batch mode, scoring thresholds, and temperature/sampling parameters.
On a fingerprint hit with a **different** `config_hash`, the user is prompted:
resume (config differs) / new / cancel. There is no silent cross-config resume.

## 8. External clients

`clients/ports.py` defines Protocols:

- `LLMClient.complete_json(schema, messages) -> dict`
- `JevClient.systemone(state, questions) -> JevResult`
- `JevClient.systemone_batch(states, questions) -> list[JevResult]`

`clients/dto.py` holds Pydantic v2 wire models (structured LLM outputs and JEV
payloads) which are converted to domain dataclasses on ingress.

### 8.1 LLM client

OpenAI-compatible `POST /v1/chat/completions`. Structured-output strategy, in
order:

1. `response_format={"type": "json_schema", ..., "strict": true}` derived from
   the DTO's `model_json_schema()`.
2. `{"type": "json_object"}` with the schema embedded in the prompt.
3. Plain prompt, extract the first JSON object.

Then a bounded validate → repair loop (≤ 2 attempts, feeding the validation
error back). `temperature=0`; all sampling parameters are recorded. Document
content is delimited and explicitly declared untrusted data (prompt-injection
defence).

> **Amended 2026-11-15 (intentional deviation):** the transport is the official
> `openai` Python SDK rather than a hand-rolled `httpx.Client`, but it is
> constructed with `max_retries=0` so the application-level loop below still
> observes and records every attempt. The loop honours `Retry-After`
> (`retry-after-ms` → `retry-after` seconds → HTTP-date, matching the SDK's own
> precedence) and caps exponential backoff at 60 seconds.

### 8.2 JEV client

`POST {jev}/v1/systemone` with `state` + `questions`, or
`POST {jev}/v1/systemone/batch` with `states[]` (≤ 64) returning results in the
same order. For `noul` questions the returned probability **is** that response's
`answer_confidence`; `choice` questions return a label plus `answer_confidence`
(and a separate entropy-based `confidence`, recorded but not used for decisions).
`--jev-min-confidence` is a **separate reliability gate applied uniformly to
every JEV response's `answer_confidence`** (default disabled) and does not
replace `--extract-gate-threshold` / `--mapped-threshold`.

### 8.3 Retry policy

Retry only idempotent calls, only on connection/timeout/408/429/5xx, with
exponential backoff plus jitter and respect for `Retry-After`. No retries on
other 4xx. Each attempt is recorded in `attempts`. Retries run inside the worker
so in-flight calls remain bounded by `--concurrency`.

## 9. Loaders and catalog adapters

### 9.1 Document loaders

`loaders/registry.py` maps media type to a loader returning a `Document`.
v1 loaders: PDF (`pypdf`), DOCX (`python-docx`), plain text/Markdown, and JSON.

JSON is flattened to text by a **deterministic rule**: object keys are visited
in sorted order and emitted as dotted paths; array elements use `[i]` indices;
scalars render as `null`, `true`/`false`, JSON numbers, or quoted strings; each
leaf becomes one `path = value` line, and lines are joined by newlines (a root
scalar renders as `$ = value`). The document `content_sha256` is always the
hash of the **raw input bytes**, so flattening never affects run identity.

Scanned/image-only PDFs and legacy binary `.doc` are rejected with actionable
errors. Identical content is de-duplicated per run.

### 9.2 Catalog adapters

`catalog_adapters/registry.py` maps catalog format to an adapter returning
`Control[]`. v1 adapters:

- **Standard OSCAL** catalog (JSON/XML/YAML) read via `oscal_build/facade.py`.
- **Container (non-OSCAL) catalog** — a vendor JSON shape whose root is
  `{"catalog": {"securityControls": [ {controlId, title, family, description,
  ...} ]}}`. Normalised into the internal `Control` model. The adapter has a
  neutral internal name; no vendor brand is surfaced.

`--catalog-format {auto,oscal}` (default `auto`) selects sniffing or forcing the
OSCAL reader. Control ids are **sanitised to a `TokenDatatype`-safe form**: if the
id does not already start with a letter or `_`, prefix `c-`; replace each
character outside `[\p{L}\p{N}._-]` with `-` (order: replacement first, then the
`c-` prefix). The **original id** is preserved as
`prop name=original-id` on the normalised control, alongside the source-document
reference. Profiles and all references use the sanitised id. Duplicate sanitised
ids across all input catalogs cause a **fail-fast error** naming the colliding
catalogs and ids.

## 10. Pipeline stages

### Stage 0 — load

Detect media type → registry loader → `Document(text, content_sha256)`; dedup
identical content; reject unsupported/scanned inputs with actionable errors.
Emission ordering is canonical (by `content_sha256`).

### Stage 1 — extract (per document; concurrent with Stage 2)

1. Chunk the document text (token-bounded, with overlap).
2. One LLM structured call per chunk → `[{text, keyword, rationale}]`
   (normative RFC 2119 only).
3. Normalise and de-duplicate. `normalised_text` = NFKC Unicode normalisation,
   `\r\n`/`\r` → `\n`, runs of whitespace collapsed to one space, trimmed, case
   preserved. `req_id = "req-" + hex(sha256(doc_content_sha256 || normalised_text))`.
4. **JEV gate** per candidate: a `noul` authenticity check ("is this a genuine,
   actionable requirement?") compared against `--extract-gate-threshold`
   (default 0.50), followed by a `choice` call over the `Keyword` set to confirm
   the RFC 2119 level. The confirmed `choice` label **replaces** the LLM-proposed
   keyword: it becomes `Requirement.keyword` (and the emitted `keyword` prop);
   the raw `choice` answer is stored in `gate_choice`. An unparseable `choice`,
   or a response below `--jev-min-confidence`, is treated as a rejected candidate
   (recorded as evidence).
5. Every proposed candidate is written as a `Requirement` row immediately
   (`extract_status='proposed'`, `gate_status=NULL`). Below the gate →
   `extract_status='rejected'`, `gate_status='rejected'` (persisted as evidence,
   excluded from retrieval). Passed → `gate_status='passed'` and eligible for
   Stage 3.
6. Extraction results are **immutable evidence**: a completed run is never
   re-extracted.

### Stage 2 — index (per catalog; concurrent with Stage 1)

1. Parse via the catalog adapter → `Control[]` (fail fast on duplicate ids).
2. Chunk controls; LLM assigns domain/family labels.
3. Aggregate a `DomainIndex` (`domain → control_ids`), cached by
   `(content_sha256, model_id, prompt_hash)`.

### Stage 3 — retrieve (per requirement)

1. LLM call 1: requirement + domain list → relevant domain(s).
2. LLM call 2 per domain: requirement + domain controls (id + short text) →
   nominate **all** plausibly-relevant controls (no cap).
3. Emit one `CandidatePair` per nominated control (`verify_status='pending'`) and
   set `requirements.retrieve_status='nominated'` in the same write.
4. **No candidates → the requirement is marked UNMAPPED (terminal) and JEV is
   skipped entirely.**

### Stage 4 — verify (per candidate pair)

JEV `noul` ("does this requirement relate to this control?") → probability.
`probability >= mapped_threshold` → `verify_status='passed'`, otherwise
`verify_status='rejected'`. Both are terminal.

### Stage 5 — classify (per passed pair)

JEV `choice` over the **five positive** OSCAL `Relationship` values
(`equivalent-to`, `equal-to`, `subset-of`, `superset-of`, `intersects-with`) →
relation + the answer's `answer_confidence`. `no-relationship` is deliberately not
offered: a Stage-4 `passed` pair is already asserted to be related, so offering
it would only allow a contradictory answer.

On success the pair is written with `classify_status='done'`. If the `choice`
call returns `no-relationship` or an unparseable value, the pair is treated as
**unmapped**: `classify_status='unmapped'`, no `map` entry is emitted, the
requirement is counted unmapped for that catalog, and the anomaly is recorded in
`evidence` and `rationale.json`. A call suppressed by `--jev-min-confidence` is
recorded as `classify_status='skipped'` (also a terminal unmapped outcome).

### Stage 6 — assemble

See Section 11.

### Thresholds and confidence semantics

- `--extract-gate-threshold` (default 0.50) compares the Stage-1 **`noul`
  authenticity probability** only, to accept/reject a proposed candidate.
- `--mapped-threshold` (default 0.50) compares the Stage-4 **`noul` probability**
  only, to decide mapped/unmapped. It is never used for an emitted confidence.
- The emitted confidence is the Stage-5 **`choice` answer's `answer_confidence`**.
  This single value drives both the mapping-collection
  `confidence-score.percentage` and the profile's `confidence-category`, so the
  two artifacts always describe the same confidence.
- Category cutoffs apply to that `answer_confidence`:
  `high ≥ 0.80`, `medium ≥ 0.50`, `low < 0.50` (configurable).
- The entropy-based `choice` `confidence` is recorded in `rationale.json` but
  does not drive any emitted score.
- `--jev-min-confidence` (default disabled) is a separate reliability gate
  applied to every JEV response's `answer_confidence`. A response below the
  threshold is flagged `low_confidence` and treated as "no decision" for the
  step that depends on it: an extraction-gate candidate is rejected; a Stage-4
  `noul` pair is rejected; a Stage-5 `choice` pair is treated as unmapped. The
  low-confidence response is still recorded in the evidence and `rationale.json`.
  It does not replace `--mapped-threshold`.
- Nomination cap: none by default (knob retained, `0` = disabled).

## 11. Output artifacts

`--output DIR` is **required** and names a folder containing all processed
outputs/evidence:

```
<output>/
  requirements-catalog.json
  profile.json
  mapping-collection.json
  rationale.json
  catalogs/<source-stem>.json          # normalised OSCAL catalogs (one per input)
  evidence/                            # exported raw LLM/JEV call records
```

Assembly is a pure function of the ledger plus the injected `Clock`/`IdFactory`.

`<source-stem>` is the input filename without its extension. If two inputs share a
stem (e.g. `a.json` and `a.xml`), `smeargle` fails fast with a clear error rather
than overwriting a normalised catalog — consistent with the duplicate-control-id
policy.

### 11.1 `requirements-catalog.json`

An OSCAL catalog whose `metadata` carries the required `title`, `version`,
`last-modified`, and `oscal-version: 1.2.3` fields (using the run timestamp).
`back-matter` links each source document. One OSCAL `group` per source document
(id `doc-<doc_id>`; a `title` plus props for source path/URI, document-id,
content hash). One `control` per accepted requirement: its `id` **equals `req_id`** (so profile
`mapped-requirement` props, mapping `sources` items, and `source-gap-summary`
references resolve unambiguously), a truncated `title`, a `part[name=statement]`
holding the prose, props `keyword` (RFC 2119 level) and `requirement-source`, and
a `link rel=reference` to the source document. `req_id` collisions within a run
fail fast.

### 11.2 `profile.json`

A tailoring profile that imports **every** input catalog so every control exists
even when unmapped. One `import` per normalised catalog (relative href
`catalogs/<source-stem>.json`, `include-all`). Per **mapped** control, one
`modify.alters[]` entry (keyed by `control-id`) carries an `adds[]` list, and
each `add` holds **one set per mapped requirement**, ordered by requirement id:
`prop name=mapped-requirement value=<req_id>`,
`prop name=confidence-category value=<high|medium|low> group=<req_id>` (the
`group` ties the category to its requirement unambiguously), and a
`link rel=reference href="#<requirements-catalog-resource-uuid>"
resource-fragment="<req_id>"` pointing into the `requirements-catalog.json`
`back-matter` resource (added for this purpose). A control mapped by several
requirements therefore carries one such set per requirement, each with its own
category — matching the per-relation confidence in the mapping-collection.
Unmapped controls receive no `add`. `back-matter` holds a resource for
`requirements-catalog.json` (the target of each per-requirement `link`) plus
resources for `mapping-collection.json` (when emitted) and `rationale.json`.

Because imports must be OSCAL, the profile imports the **normalised** catalogs,
not the raw non-OSCAL originals. Provenance back to the original source is kept
as props/links on the normalised catalog and in `rationale.json`.

### 11.3 `mapping-collection.json`

`provenance = {method: automation, matching-rationale: semantic, status: draft,
mapping-description: <concrete prose summary of the run's mappings>}`.
`mapping-description` is required by the schema, so a concrete value is always
emitted. One `mapping` object **per input catalog**, each with
`source-resource` = the requirements catalog and
`target-resource = {type: catalog, href: catalogs/<source-stem>.json}`. Each
mapping lists only the relations whose controls live in that catalog; each
relation carries `relationship`, `confidence-score.percentage`, and
`sources`/`targets` mapping-items. `source-gap-summary` is scoped to its own
`mapping` object: within a per-catalog mapping it lists the requirement ids that
have no mapping **in that catalog**, including pairs whose Stage-5 `choice`
returned `no-relationship`/unparseable and pairs suppressed by
`--jev-min-confidence` (`classify_status='skipped'`).

Because `mapping.maps` requires ≥ 1 entry and `gap-summary.unmapped-controls`
requires ≥ 1 entry: a catalog with **no** relations emits **no** `mapping` object
at all, and a per-catalog `source-gap-summary` is emitted only when that catalog
has ≥ 1 unmapped accepted requirement. A requirement unmapped in a catalog that
emits no mapping is therefore not listed in that catalog's (non-existent) gap
summary. The run-level `unmapped_requirements` list covers requirements with no
mapping in **any** catalog — not per-catalog omissions — so global coverage
still holds.

If the run produces **zero relations globally** (no accepted requirements, or all
unmapped/rejected), `mapping-collection.json` is **omitted** entirely, and the
profile/`rationale.json` drop their references to it; the §11.6 integrity gate
treats its absence as valid in that case (an empty `mappings` array would violate
`minItems: 1`).

The mapping-collection uses **`confidence-score.percentage`** (0–1) only. The
derived **`category`** appears only as a `prop` in the profile and in
`rationale.json`, so percentage and category are never emitted in the same
`confidence-score` object. (`confidence-score` is an `anyOf` with
`additionalProperties:false` per branch: exactly one of `category`/`percentage`
is permitted.) Both derive from the Stage-5 `choice` answer's
`answer_confidence`.

### 11.4 `rationale.json`

A non-OSCAL process record, the human/audit-facing evidence:

- Run block: run id, fingerprint, `config_hash`, timestamps, model ids, prompt
  hashes, thresholds, redacted config snapshot.
- Per requirement: source doc, text, keyword, gate results, mapped/unmapped
  status and reason.
- Run-level `unmapped_requirements`: the requirement ids with no mapping in any
  catalog, with the reason (no nominated candidates; all candidates rejected; all
  passed candidates classified `no-relationship`/unparseable; or all candidate
  classifications suppressed by `--jev-min-confidence`
  (`classify_status='skipped'`)).
- Run-level `rejected_candidates`: gate-rejected proposed requirements (id, text,
  source doc, gate probability), retained as evidence but excluded from the
  requirements catalog, mappings, and gap summaries.
- Per pair: retrieval rationale, **both** the `noul` probability and the
  `choice` numbers/`answer_confidence`, relation, derived percentage + category,
  prose rationale, and evidence pointers.
- Summary counts.

### 11.5 `evidence/`

The raw LLM/JEV request/response records exported from the run store
(redacted), one record per call, preserving `stage`, `item_ref`, `call_type`,
`attempt_no`, `http_status`, `request_sha256`, and `prompt_hash`.

### 11.6 Integrity gate (run fails if violated)

- Every **accepted** requirement (`gate_status='passed'`) appears in at least one
  of: a mapping, a per-catalog gap summary, or the run-level
  `unmapped_requirements` list. Gate-rejected candidates are retained in
  `rationale.json` (`rejected_candidates`) and are exempt from this coverage rule.
- Every control from every input catalog is covered by a profile `import`
  (`include-all`), checked against each catalog's control list and the import
  list — not against `modify` `adds`, which legitimately omit unmapped controls.
- Every `#uuid` reference resolves to a `back-matter` resource.
- Every `link[rel=reference]` non-fragment `href` is an absolute URI; every
  fragment `href` (`#uuid`) resolves to a `back-matter` resource, and any
  `resource-fragment` resolves within that resource. Relative references for
  `import` and resource `href`s (`catalogs/<stem>.json`) are permitted, as
  OSCAL's absolute-URI constraint applies to `link` elements.
- Control ids are globally unique.
- All artifacts validate against both the bundled metaschema and the vendored
  official OSCAL 1.2.3 JSON Schemas. `mapping-collection.json` is validated when
  present; a globally zero-relation run omits it and that absence is accepted.
  For the `extract` partial assemble, only the emitted requirements catalog is
  validated (profile/mapping-collection/rationale are not produced).

### 11.7 Determinism

Documents and catalogs are sorted by `content_sha256` before emission; all UUIDs
come from `IdFactory.uuid_for`; all timestamps come from the frozen run `Clock`.
Re-assembling the **same stored ledger** (which includes the recorded external
responses) yields byte-identical artifacts. A fresh run is only byte-identical
when both the external clients and `IdFactory.run_uuid()` are frozen/stubbed (as
in tests); live LLM/JEV responses are not byte-stable and are instead captured in
the ledger.

## 12. CLI

Subcommands (Typer), sharing globals `--config`, `--state-dir`, `--output`,
`--log-format {text,json}`, `--run-id`, `--force`, `--verbose`, `--yes`:

- `run` — full pipeline.
- `extract` — Stages 0–1 only → runs a partial assemble that emits the
  requirements catalog + ledger; it does not emit the profile, mapping-collection,
  or rationale artifacts, and its integrity gate validates only the emitted
  requirements catalog.
- `map` — Stages 2–6 from an existing run.
- `resume` — continue an interrupted run.
- `validate` — validate input catalogs and/or emitted artifacts.
- `status` — show per-stage progress/counts.

Key options: inputs `-i/--input` (repeatable); catalogs `-c/--catalog`
(repeatable); `--catalog-format {auto,oscal}`; LLM group (`--llm-endpoint`,
`--llm-model`, `--llm-auth-file`/`--llm-api-key-env`, `--llm-timeout`,
`--llm-retries`, `--llm-temperature`); JEV group (`--jev-endpoint`,
`--jev-model`, `--jev-auth-file`/`--jev-api-key-env`, `--jev-timeout`,
`--jev-retries`, `--jev-batch/--no-jev-batch`, `--jev-batch-size`,
`--jev-min-confidence`, `--jev-max-len`, `--jev-head-max-len`); mapping group
(`--extract-gate-threshold`, `--mapped-threshold`, `--category-high`,
`--category-medium`, `--nomination-cap`, `--concurrency`).

### 12.1 Run/resume UX

Compute the fingerprint on start. If a run with the same fingerprint exists:

- same `config_hash` → prompt resume / new / cancel;
- different `config_hash` → prompt resume (config differs) / new / cancel, with a
  mixing warning.

`--run-id` selects a run explicitly; `--force` starts a new one. After
Stage 1 (extract) the requirement count is known; after Stage 3 (retrieve) the
exact candidate-pair count is known. The pre-flight estimate is printed at those
two points (requirement count, then the actual candidate-pair count) immediately
before the verification fan-out. `--yes` skips confirmation. The estimate is
informational only — there is no cap.

### 12.2 Exit codes

| Code | Meaning |
|---|---|
| 0 | Success, no gaps |
| 1 | Unexpected error |
| 2 | Usage/config error |
| 3 | Input/load error (unsupported, scanned PDF, `.doc`) |
| 4 | Catalog error (duplicate ids, invalid OSCAL) |
| 5 | External service unreachable/auth-rejected (fatal, affects all calls) |
| 6 | Completed with gaps (artifacts still written) |
| 7 | Post-assembly integrity/validation failure |
| 8 | Aborted by user |

## 13. Nix packaging

- Python is taken from the pinned nixpkgs' `python3Packages` (floating with the
  flake lock; no hard-pinned minor version).
- Missing upstream packages live one-per-directory under `package/<name>/`
  (`package/oscal/`, `package/ruf-common/`), each `buildPythonPackage` with
  `fetchPypi` pinned to an exact version and hash, and correct
  `propagatedBuildInputs` (`oscal` → `jsonschema-rs`, `jsonpath-python`,
  `xmlschema`, `pyyaml`, `markdown`, `ruf-common`). `pythonRelaxDeps` is used
  surgically only for genuine clashes. `pythonImportsCheck` catches a missing
  bundled support database.
- `overlays/default.nix` extends `python3Packages` with the new packages and
  aliases PyPI `jsonschema_rs` to the existing nixpkgs `jsonschema-rs`.
- Flake outputs (hand-rolled `forAllSystems` over `x86_64-linux` and
  `aarch64-linux`, **no new flake inputs**): `packages.<sys>.default` /
  `.smeargle` (`buildPythonApplication`), `overlays.default`,
  `devShells.<sys>.default` (uv/`mkVirtualEnv` + pytest + ruff + mypy),
  `checks.<sys>.default` (test suite incl. artifact schema validation),
  `apps.<sys>.default` (the CLI).
- The derivation supplies every dependency so builds never reach PyPI.

## 14. Testing strategy

- **Unit:** in-process `FakeLLMClient`/`FakeJevClient` implementing the
  Protocols (no sockets).
- **Client integration:** `respx` against `httpx` to assert exact request bodies
  and headers and to exercise retry/backoff.
- **End-to-end:** an in-thread real HTTP fake per service, exercised via a
  subprocess CLI run.
- **Determinism:** inject a frozen `Clock` and a stubbed `IdFactory` (including a
  fixed `run_uuid()`); assert byte-identical artifacts across two runs; assert
  fingerprint order-independence and content-sensitivity.
- **Resume:** kill between stages (after a committed batch), resume, assert
  completed work issues no new external calls (only the in-flight batch may be
  re-issued, per the at-least-once rule) and output is unchanged.
- **Validation:** every artifact validated against the vendored official JSON
  Schemas and the metaschema.
- **Adversarial fakes:** out-of-range probabilities, unknown relationship
  strings, duplicate JSON keys — validation must reject, not coerce.
- **Nix:** `nix flake check` and `nix build .#smeargle` in CI.

## 15. Error handling and observability

Per-item failures (a single call that times out or returns 5xx after exhausting
retries) are recorded and the run continues by default; a run that produces
artifacts with gaps exits non-zero (code 6) and stamps the gaps in the
mapping-collection and `rationale.json`. A **fatal** service failure — the
endpoint unreachable when first contacted (connection/DNS refused) or auth
rejected (401/403), i.e. a condition affecting all calls — aborts the run with
exit code 5. Errors are centralised in `errors.py`
and mapped to exit codes in the CLI. Structured logging
(`--log-format json`), progress reporting, and central redaction live in
`observability.py`.

## 16. Risks and open items

- **`oscal` API churn:** a young, single-maintainer project with rapid majors.
  Mitigated by the `oscal_build/facade.py` isolation and an exact version pin.
- **Metaschema vs JSON Schema:** the bundled validator uses the metaschema; the
  vendored JSON Schemas are validated in tests as a second opinion.
- **Relationship enum:** not enforced by JSON Schema; validate explicitly.
- **JEV option budget:** `choice` accuracy degrades with very many options;
  `head_max_len` and batch sizing are configurable.
- **Call volume:** the prefilter reduces but does not bound pairs; a pre-flight
  estimate is printed, and a nomination cap knob exists though disabled by
  default.
- **Sequencing:** plan the v1 core (`run`/`extract`/`map`/assemble) before the
  optional surface (`status`, JEV batching, nomination cap, extra loaders).

## 17. Decisions log

| # | Decision |
|---|---|
| Q1 | Emit both an OSCAL profile and an OSCAL mapping-collection. |
| Q2 | Traditional LLM proposes requirements; JEV gates them. LLM is an OpenAI-compatible endpoint passed as an argument with optional auth. |
| Q3 | Hybrid mapping: LLM retrieval shortlist, then per-pair JEV verification. |
| Q4 | Many-to-many mappings; every requirement appears even if unmapped; OSCAL relationship enums; confidence where the schema allows. |
| Q5 | Checkpoints in SQLite; content-addressed, order-independent runs; fine-grained resume; raw call payloads retained. |
| Q6 | Stage-1 prefilter is the LLM, hierarchically: chunked domain index → domain selection → candidate nomination; no candidates → UNMAPPED, skip JEV; domain index cached. |
| Q7 | Relationship type via a second JEV `choice` call over the **five positive** OSCAL relationship values; `noul` first; `no-relationship`/unparseable → unmapped + logged. |
| Q8 | Inputs: PDF, DOCX, JSON, text/Markdown; no OCR; no binary `.doc`; pluggable loader registry. |
| Q9 | Normative RFC 2119 levels only; JEV gate = `noul` then `choice`. |
| Q10 | Output set: requirements catalog + profile + mapping-collection + rationale sidecar; references prefer document ids. |
| Q11 | Subcommand CLI; TOML/YAML config; `--state-dir`. |
| Q12 | Bounded parallel execution; optional JEV batching; OpenAI-compatible chat endpoint; timeout + retry/backoff recorded as evidence. |
| Q13 | Package/CLI `smeargle`; PEP 621 `src/` layout; `buildPythonApplication`; deps via nixpkgs; dev shell with pytest; fake LLM/JEV fixtures + e2e subprocess smoke test. |
| Q14 | Nix: per-upstream packages in `package/<name>/`, exposed via the flake; Python from `python3Packages`. |
| Q15 | Non-OSCAL (container) catalogs are normalised and emitted as OSCAL catalogs; `--catalog-format {auto,oscal}`; no vendor brand surfaced. |
| Q16 | `--output DIR` required; fixed artifact filenames; normalised catalogs at `catalogs/<source-stem>.json`; raw call evidence exported to `evidence/`. |
| R1 | `confidence-score`: profile uses `category`, mapping-collection uses `percentage`; never both; sidecar is `rationale.json`. |
| R2 | Deterministic `Clock` + `IdFactory` (UUIDv5). |
| R3 | Config-drift resume is gated by a separate `config_hash` with an explicit prompt. |
| R4 | No asyncio: sync `httpx` in a `ThreadPoolExecutor` over a single-writer WAL store. |
| R5 | Colliding control ids across catalogs fail fast. |

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
