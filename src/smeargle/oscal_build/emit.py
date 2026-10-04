"""Assemble, write, and gate the §11 output layout (pure builders + gate)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from smeargle.observability import redact

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _evidence_name(record: Mapping[str, Any]) -> str:
    # `request_sha256` distinguishes repair-loop / fallback rows that share the same
    # (stage, item_ref, call_type, attempt_no); dropping it would overwrite records.
    stem = "-".join(
        [
            str(record.get("stage", "stage")),
            str(record.get("item_ref", "item")),
            str(record.get("call_type", "call")),
            str(record.get("attempt_no", 0)),
            str(record.get("request_sha256", "")),
        ]
    )
    return _UNSAFE.sub("-", stem).strip("-") + ".json"


def export_evidence(evidence: Sequence[Mapping[str, Any]], output: Path) -> list[Path]:
    directory = Path(output) / "evidence"
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for record in evidence:
        payload = {
            "stage": record.get("stage"),
            "item_ref": record.get("item_ref"),
            "call_type": record.get("call_type"),
            "attempt_no": record.get("attempt_no"),
            "http_status": record.get("http_status"),
            "request_sha256": record.get("request_sha256"),
            "prompt_hash": record.get("prompt_hash"),
            "request": redact(record.get("request")),
            "response": redact(record.get("response")),
        }
        path = directory / _evidence_name(record)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8"
        )
        written.append(path)
    return written
