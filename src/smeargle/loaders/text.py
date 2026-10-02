"""Plain-text/Markdown loading with encoding and BOM normalisation (spec 9.1)."""

from __future__ import annotations

import codecs
from pathlib import Path

from smeargle.errors import InputError

_BOMS = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def decode_bytes(raw: bytes) -> str:
    for bom, encoding in _BOMS:
        if raw.startswith(bom):
            decoded = raw.decode(encoding)
            break
    else:
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InputError(f"could not decode text as UTF-8: {exc}") from exc
    return decoded.replace("\r\n", "\n").replace("\r", "\n")


def load_text(path: Path) -> tuple[str, str]:
    return "text/plain", decode_bytes(Path(path).read_bytes())
