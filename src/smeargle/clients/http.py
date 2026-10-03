"""Shared thread-safe httpx client construction and auth resolution (spec 6, 8, 15)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import httpx

from smeargle.errors import ServiceError
from smeargle.observability import redact

_logger = logging.getLogger("smeargle.clients")


def load_bearer_token(*, auth_file: Optional[Path], api_key_env: Optional[str]) -> Optional[str]:
    if auth_file is not None:
        try:
            token = Path(auth_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ServiceError(f"could not read auth file '{auth_file}': {exc}") from exc
        if token:
            return token
    if api_key_env:
        env_token = os.environ.get(api_key_env)
        if env_token:
            return env_token
    return None


def _log_request(request: httpx.Request) -> None:
    _logger.debug(
        "http request",
        extra={"smeargle": {"method": request.method, "url": str(request.url),
                            "headers": redact(dict(request.headers))}},
    )


def _log_response(response: httpx.Response) -> None:
    _logger.debug(
        "http response",
        extra={"smeargle": {"status": response.status_code, "url": str(response.request.url)}},
    )


def build_client(
    *,
    base_url: str,
    timeout: float,
    token: Optional[str] = None,
    max_connections: int = 8,
) -> httpx.Client:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    limits = httpx.Limits(
        max_connections=max_connections, max_keepalive_connections=max_connections
    )
    return httpx.Client(
        base_url=base_url,
        timeout=httpx.Timeout(timeout),
        headers=headers,
        limits=limits,
        event_hooks={"request": [_log_request], "response": [_log_response]},
    )
