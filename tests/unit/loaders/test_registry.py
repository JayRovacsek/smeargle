import json

import pytest
from docx import Document as DocxDocument
from pypdf import PdfWriter

from smeargle.errors import InputError
from smeargle.loaders import registry


def test_load_text_and_json(tmp_path):
    txt = tmp_path / "a.md"
    txt.write_text("# Title", encoding="utf-8")
    assert registry.load_document(txt) == ("text/plain", "# Title")
    js = tmp_path / "a.json"
    js.write_text(json.dumps({"a": 1}), encoding="utf-8")
    assert registry.load_document(js) == ("application/json", "a = 1")


def test_load_docx(tmp_path):
    path = tmp_path / "a.docx"
    document = DocxDocument()
    document.add_paragraph("First paragraph")
    document.save(path)
    media_type, content = registry.load_document(path)
    assert media_type.endswith("wordprocessingml.document")
    assert content == "First paragraph"


def test_scanned_pdf_is_rejected(tmp_path):
    path = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with path.open("wb") as handle:
        writer.write(handle)
    with pytest.raises(InputError, match="scanned/image-only"):
        registry.load_document(path)


def test_legacy_doc_is_rejected(tmp_path):
    path = tmp_path / "old.doc"
    path.write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 32)
    with pytest.raises(InputError, match=r"\.doc"):
        registry.load_document(path)


def test_unknown_suffix_is_rejected(tmp_path):
    path = tmp_path / "a.xyz"
    path.write_text("x", encoding="utf-8")
    with pytest.raises(InputError, match="unsupported"):
        registry.load_document(path)


def test_detect_media_type_by_magic_bytes(tmp_path):
    path = tmp_path / "noext"
    path.write_bytes(b"%PDF-1.7\n")
    assert registry.detect_media_type(path) == "application/pdf"


def test_invalid_pdf_bytes_raise_input_error(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"this is not a pdf")
    with pytest.raises(InputError):
        registry.load_document(path)


def test_invalid_docx_zip_raises_input_error(tmp_path):
    path = tmp_path / "broken.docx"
    path.write_bytes(b"this is not a zip archive")
    with pytest.raises(InputError):
        registry.load_document(path)


def test_directory_path_raises_input_error(tmp_path):
    path = tmp_path / "folder"
    path.mkdir()
    with pytest.raises(InputError):
        registry.load_document(path)
