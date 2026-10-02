"""DOCX loading via python-docx (spec 9.1)."""

from __future__ import annotations

from pathlib import Path

from docx import Document as DocxDocument

from smeargle.errors import InputError

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def load_docx(path: Path) -> tuple[str, str]:
    path = Path(path)
    document = DocxDocument(str(path))
    paragraphs = [paragraph.text for paragraph in document.paragraphs]
    content = "\n".join(paragraphs).strip()
    if not content:
        raise InputError(
            f"'{path}' contains no extractable paragraph text;"
            " scanned/image-only documents are not supported"
        )
    return DOCX_MEDIA_TYPE, content
