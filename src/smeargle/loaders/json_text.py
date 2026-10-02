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
