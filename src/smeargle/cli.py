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
