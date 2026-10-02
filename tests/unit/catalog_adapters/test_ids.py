import pytest

from smeargle.catalog_adapters import ids


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ac-2", "ac-2"),
        ("AC-2(1)", "AC-2-1-"),
        ("1.1.1", "c-1.1.1"),
        ("_private", "_private"),
        ("a/b c", "a-b-c"),
        ("9a", "c-9a"),
        ("-leading", "c--leading"),
    ],
)
def test_sanitize_control_id(raw, expected):
    assert ids.sanitize_control_id(raw) == expected


def test_sanitize_is_token_safe_and_deterministic():
    assert ids.is_token_safe(ids.sanitize_control_id("1 bad/id")) is True
    assert ids.is_token_safe(ids.sanitize_control_id("ac-2")) is True
    assert ids.is_token_safe("1bad") is False


def test_empty_id_becomes_prefixed():
    assert ids.sanitize_control_id("") == "c-"
