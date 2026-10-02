"""Media-type detection and loader registry (spec 9.1)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from smeargle.errors import InputError
from smeargle.loaders import docx, json_text, pdf, text

Loader = Callable[[Path], tuple[str, str]]

SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".json", ".txt", ".md", ".markdown")
OLE_MAGIC = b"\xd0\xcf\x11\xe0"

_SUFFIX_LOADERS: dict[str, Loader] = {
    ".pdf": pdf.load_pdf,
    ".docx": docx.load_docx,
    ".json": json_text.load_json,
    ".txt": text.load_text,
    ".md": text.load_text,
    ".markdown": text.load_text,
}


def detect_media_type(path: Path) -> str:
    path = Path(path)
    raw = path.read_bytes()
    if raw.startswith(b"%PDF-"):
        return "application/pdf"
    if raw.startswith(OLE_MAGIC):
        return "application/msword"
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return docx.DOCX_MEDIA_TYPE
    if suffix == ".json":
        return "application/json"
    if suffix in {".txt", ".md", ".markdown"}:
        return "text/plain"
    return "application/octet-stream"


def loader_for(path: Path) -> Loader:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".doc":
        raise InputError(
            f"'{path}' is a legacy binary .doc file, which is not supported;"
            " convert it to .docx or PDF"
        )
    if path.read_bytes().startswith(OLE_MAGIC):
        raise InputError(
            f"'{path}' looks like a legacy binary .doc/OLE file, which is not supported;"
            " convert it to .docx or PDF"
        )
    loader = _SUFFIX_LOADERS.get(suffix)
    if loader is None:
        supported = ", ".join(SUPPORTED_EXTENSIONS)
        raise InputError(f"unsupported input type '{suffix or path.name}'; supported: {supported}")
    return loader


def load_document(path: Path) -> tuple[str, str]:
    path = Path(path)
    return loader_for(path)(path)
