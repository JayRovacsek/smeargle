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

    # --- Phase 1 remediation (MUST be preserved) ---
    if log_format is not None and log_format not in {"text", "json"}:
        raise UsageError("--log-format must be 'text' or 'json'")
    if config is not None and not config.exists():
        raise UsageError(f"config file not found: {config}")
    # --- end Phase 1 remediation ---

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

    # --- Phase 1 remediation (MUST be preserved) ---
    try:
        settings = Settings.load(config_file=config, overrides=overrides)
    except SmeargleError:
        raise
    except Exception as exc:
        raise UsageError(f"invalid configuration: {exc}") from exc
    # --- end Phase 1 remediation ---
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
