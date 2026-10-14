"""Typer CLI, shared globals, and central exit-code mapping (spec 12)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, List, Optional

import typer

from smeargle import __version__
from smeargle.catalog_adapters.registry import parse_catalog
from smeargle.config import Settings
from smeargle.console import new_progress
from smeargle.domain.clock import SystemClock
from smeargle.domain.ids import UuidIdFactory
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
from smeargle.observability import configure_logging, set_redaction
from smeargle.oscal_build import facade
from smeargle.pipeline import run as run_pipeline
from smeargle.pipeline.run import RunResult as RunPipelineResult  # noqa: F401
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
    llm_base_url: Optional[str] = typer.Option(None, "--llm-base-url", help="Base URL for the LLM API (OpenAI-compatible)."),
    llm_model: Optional[str] = typer.Option(None, "--llm-model"),
    llm_auth_file: Optional[Path] = typer.Option(None, "--llm-auth-file"),
    llm_api_key_env: Optional[str] = typer.Option(None, "--llm-api-key-env"),
    llm_timeout: Optional[float] = typer.Option(None, "--llm-timeout"),
    llm_retries: Optional[int] = typer.Option(None, "--llm-retries"),
    llm_temperature: Optional[float] = typer.Option(None, "--llm-temperature"),
    jev_base_url: Optional[str] = typer.Option(None, "--jev-base-url", help="Base URL for the JEV API."),
    jev_model: Optional[str] = typer.Option(None, "--jev-model"),
    jev_auth_file: Optional[Path] = typer.Option(None, "--jev-auth-file"),
    jev_api_key_env: Optional[str] = typer.Option(None, "--jev-api-key-env"),
    jev_timeout: Optional[float] = typer.Option(None, "--jev-timeout"),
    jev_retries: Optional[int] = typer.Option(None, "--jev-retries"),
    jev_batch: Optional[bool] = typer.Option(None, "--jev-batch/--no-jev-batch"),
    jev_batch_size: Optional[int] = typer.Option(None, "--jev-batch-size"),
    jev_min_confidence: Optional[float] = typer.Option(None, "--jev-min-confidence"),
    extract_gate_threshold: Optional[float] = typer.Option(None, "--extract-gate-threshold"),
    mapped_threshold: Optional[float] = typer.Option(None, "--mapped-threshold"),
    category_high: Optional[float] = typer.Option(None, "--category-high"),
    category_medium: Optional[float] = typer.Option(None, "--category-medium"),
    nomination_cap: Optional[int] = typer.Option(None, "--nomination-cap"),
    concurrency: Optional[int] = typer.Option(None, "--concurrency"),
    version: bool = typer.Option(False, "--version", help="Show version and exit."),
    catalog_format: Optional[str] = typer.Option(
        None, "--catalog-format", help="auto or oscal."
    ),
    redact: Optional[bool] = typer.Option(
        None, "--redact/--no-redact",
        help="Redact secret-looking fields from evidence and logs (default on)."
        " --no-redact writes unredacted payloads and credentials to the state"
        " database, evidence/ and verbose logs.",
    ),
) -> None:
    if version:
        typer.echo(f"smeargle {__version__}")
        raise typer.Exit(code=EXIT_SUCCESS)

    # --- Phase 1 remediation (MUST be preserved) ---
    if log_format is not None and log_format not in {"text", "json"}:
        raise UsageError("--log-format must be 'text' or 'json'")
    if config is not None and not config.exists():
        raise UsageError(f"config file not found: {config}")
    # --- end Phase 1 remediation ---

    if catalog_format is not None and catalog_format not in {"auto", "oscal"}:
        raise UsageError("--catalog-format must be 'auto' or 'oscal'")

    overrides: dict[str, Any] = {}
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
    if redact is not None:
        execution["redact"] = redact
    if execution:
        overrides["execution"] = execution

    llm_overrides = {
        key: value
        for key, value in {
            "base_url": llm_base_url, "model": llm_model, "auth_file": llm_auth_file,
            "api_key_env": llm_api_key_env, "timeout": llm_timeout, "retries": llm_retries,
            "temperature": llm_temperature,
        }.items()
        if value is not None
    }
    if llm_overrides:
        overrides["llm"] = llm_overrides
    jev_overrides = {
        key: value
        for key, value in {
            "base_url": jev_base_url, "model": jev_model, "auth_file": jev_auth_file,
            "api_key_env": jev_api_key_env, "timeout": jev_timeout, "retries": jev_retries,
            "batch": jev_batch, "batch_size": jev_batch_size,
            "min_confidence": jev_min_confidence,
        }.items()
        if value is not None
    }
    if jev_overrides:
        overrides["jev"] = jev_overrides
    mapping_overrides = {
        key: value
        for key, value in {
            "extract_gate_threshold": extract_gate_threshold, "mapped_threshold": mapped_threshold,
            "category_high": category_high, "category_medium": category_medium,
            "nomination_cap": nomination_cap,
        }.items()
        if value is not None
    }
    if mapping_overrides:
        overrides["mapping"] = mapping_overrides
    if concurrency is not None:
        execution_overrides = overrides.setdefault("execution", {})
        execution_overrides["concurrency"] = concurrency

    # --- Phase 1 remediation (MUST be preserved) ---
    try:
        settings = Settings.load(config_file=config, overrides=overrides)
    except SmeargleError:
        raise
    except Exception as exc:
        raise UsageError(f"invalid configuration: {exc}") from exc
    # --- end Phase 1 remediation ---
    configure_logging(settings.execution.log_format, verbose=settings.execution.verbose)
    set_redaction(settings.execution.redact)
    if not settings.execution.redact:
        typer.secho(
            "warning: redaction disabled - unredacted model payloads and credentials may"
            " be written to the state database, evidence/ and verbose logs",
            fg=typer.colors.YELLOW,
            err=True,
        )
    ctx.obj = settings

    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(code=EXIT_SUCCESS)


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
    if not settings.llm.base_url:
        raise UsageError("run requires --llm-base-url")
    if not settings.jev.base_url:
        raise UsageError("run requires --jev-base-url")

    _configure_oscal(settings)
    fingerprint = run_pipeline.compute_fingerprint(input_paths, catalog_paths)
    config = run_pipeline.redact(run_pipeline._phase3_config_snapshot(settings))
    selected = settings.execution.run_id or _select_run_id(
        settings, fingerprint, run_pipeline.config_hash(config)
    )
    with new_progress() as progress:
        result = run_pipeline.run_pipeline(
            state_dir=settings.state_dir, output=settings.output, input_paths=input_paths,
            catalog_paths=catalog_paths, settings=settings, clock=SystemClock(),
            id_factory=UuidIdFactory(), run_id=selected, estimate=_estimate_printer(),
            progress=progress,
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
    if not settings.llm.base_url:
        raise UsageError("extract requires --llm-base-url")
    if not settings.jev.base_url:
        raise UsageError("extract requires --jev-base-url")
    _configure_oscal(settings)
    with new_progress() as progress:
        result = run_pipeline.run_extract_only(
            state_dir=settings.state_dir, output=settings.output, input_paths=input_paths,
            settings=settings, clock=SystemClock(), id_factory=UuidIdFactory(),
            run_id=settings.execution.run_id, estimate=_estimate_printer(),
            progress=progress,
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
    if not settings.llm.base_url:
        raise UsageError("map requires --llm-base-url")
    if not settings.jev.base_url:
        raise UsageError("map requires --jev-base-url")
    _configure_oscal(settings)
    with new_progress() as progress:
        result = run_pipeline.run_map(
            state_dir=settings.state_dir, output=settings.output, catalog_paths=catalog_paths,
            settings=settings, clock=SystemClock(), id_factory=UuidIdFactory(),
            run_id=settings.execution.run_id, estimate=_estimate_printer(),
            progress=progress,
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
    if not settings.llm.base_url:
        raise UsageError("resume requires --llm-base-url")
    if not settings.jev.base_url:
        raise UsageError("resume requires --jev-base-url")
    _configure_oscal(settings)
    with new_progress() as progress:
        result = run_pipeline.resume_run(
            state_dir=settings.state_dir, output=settings.output, settings=settings,
            clock=SystemClock(), id_factory=UuidIdFactory(),
            run_id=settings.execution.run_id, estimate=_estimate_printer(),
            progress=progress,
        )
    _finish(result)


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
            facade.validate(
                model, facade.load_document(path), href=path.absolute().as_uri()
            )
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
