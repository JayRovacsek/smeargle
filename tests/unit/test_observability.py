from smeargle.observability import REDACTED, is_secret_key, redact


def test_redacts_secret_keys_recursively():
    data = {"api_key": "s", "nested": {"Authorization": "Bearer x", "path": "a"}}
    out = redact(data)
    assert out["api_key"] == REDACTED
    assert out["nested"]["Authorization"] == REDACTED
    assert out["nested"]["path"] == "a"


def test_redacts_lists():
    assert redact([{"token": "t"}]) == [{"token": REDACTED}]


def test_is_secret_key():
    assert is_secret_key("llm_api_key")
    assert is_secret_key("Authorization")
    assert not is_secret_key("model")
