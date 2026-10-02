"""TokenDatatype-safe control-id sanitisation (spec 9.2)."""

from __future__ import annotations

import re

_DISALLOWED = re.compile(r"[^\w.\-]")


def sanitize_control_id(raw: str) -> str:
    replaced = _DISALLOWED.sub("-", raw)
    if not replaced or not (replaced[0].isalpha() or replaced[0] == "_"):
        return f"c-{replaced}"
    return replaced


def is_token_safe(value: str) -> bool:
    if not value or not (value[0].isalpha() or value[0] == "_"):
        return False
    return _DISALLOWED.search(value) is None
