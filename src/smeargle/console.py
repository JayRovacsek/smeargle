"""Shared rich console and progress rendering for user-facing CLI output (spec UI)."""

from __future__ import annotations

from typing import Callable, Optional

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

_console: Console | None = None


def console() -> Console:
    """Return the process-wide console writing to stderr.

    A single instance keeps rich's colour detection and live-display state
    consistent across logging handlers and progress bars.
    """
    global _console
    if _console is None:
        _console = Console(stderr=True)
    return _console


def new_progress() -> Progress:
    """Build a progress renderer for the pipeline's per-stage bars.

    Live display is disabled automatically when stderr is not an interactive
    terminal (for example under pytest or when redirected), so machine-readable
    output is never polluted by progress frames.
    """
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console(),
        disable=not console().is_terminal,
        transient=True,
        redirect_stdout=False,
    )


def stage_task(
    progress: Optional[Progress], description: str, total: int
) -> Optional[Callable[[], None]]:
    """Register a per-stage bar and return a callable advancing it once per item.

    Returns None when there is no progress renderer or nothing to count, so
    callers can pass the result straight into ``_fan_out``'s ``on_done``.
    """
    if progress is None or total <= 0:
        return None
    task = progress.add_task(description, total=total)
    return lambda: progress.advance(task)
