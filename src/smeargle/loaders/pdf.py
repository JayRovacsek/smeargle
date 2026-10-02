"""PDF loading with pypdf; scanned/image-only PDFs are rejected (spec 9.1)."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from smeargle.errors import InputError


def load_pdf(path: Path) -> tuple[str, str]:
    path = Path(path)
    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    content = "\n".join(pages).strip()
    if not content:
        raise InputError(
            f"'{path}' is a scanned/image-only PDF with no extractable text;"
            " OCR is not supported - supply a text, Markdown, DOCX, or text-based PDF"
        )
    return "application/pdf", content
