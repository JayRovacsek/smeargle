import codecs

import pytest

from smeargle.errors import InputError
from smeargle.loaders import text


def test_strips_utf8_bom_and_normalises_newlines():
    raw = codecs.BOM_UTF8 + b"line one\r\nline two\rline three"
    assert text.decode_bytes(raw) == "line one\nline two\nline three"


def test_decodes_utf16_with_bom():
    raw = "hello \u2713".encode("utf-16")
    assert text.decode_bytes(raw) == "hello \u2713"


def test_rejects_undecodable_bytes():
    with pytest.raises(InputError):
        text.decode_bytes(b"\xff\xff\xff")


def test_load_text_returns_media_type(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("hello", encoding="utf-8")
    media_type, content = text.load_text(path)
    assert media_type == "text/plain"
    assert content == "hello"
