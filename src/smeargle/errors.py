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


class StoreError(SmeargleError):
    exit_code = EXIT_UNEXPECTED


def exit_code_for(exc: BaseException) -> int:
    if isinstance(exc, SmeargleError):
        return exc.exit_code
    return EXIT_UNEXPECTED
