import json
import logging

import pytest

from smeargle.observability import (
    REDACTED,
    JsonFormatter,
    configure_logging,
    is_secret_key,
    redact,
)


@pytest.fixture(autouse=True)
def restore_root_logger():
    root = logging.getLogger()
    handlers = list(root.handlers)
    level = root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


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


def test_json_formatter_redacts_smeargle_extra():
    record = logging.LogRecord(
        name="smeargle.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    record.smeargle = {"api_key": "s", "path": "a"}
    payload = json.loads(JsonFormatter().format(record))
    assert payload["data"]["api_key"] == REDACTED
    assert payload["data"]["path"] == "a"
    assert payload["level"] == "info"
    assert payload["logger"] == "smeargle.test"
    assert payload["message"] == "hello world"


def test_json_formatter_includes_exception_info():
    try:
        raise ValueError("boom")
    except ValueError as err:
        record = logging.LogRecord(
            name="smeargle.test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="failed",
            args=(),
            exc_info=(type(err), err, err.__traceback__),
        )
    payload = json.loads(JsonFormatter().format(record))
    assert isinstance(payload["exc_info"], str)
    assert payload["exc_info"]


def test_configure_logging_json_uses_json_formatter():
    configure_logging("json")
    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, JsonFormatter)


def test_configure_logging_text_uses_plain_formatter():
    configure_logging("text")
    root = logging.getLogger()
    assert len(root.handlers) == 1
    formatter = root.handlers[0].formatter
    assert isinstance(formatter, logging.Formatter)
    assert not isinstance(formatter, JsonFormatter)


def test_configure_logging_verbose_sets_debug():
    configure_logging(verbose=True)
    assert logging.getLogger().level == logging.DEBUG


def test_configure_logging_non_verbose_sets_info():
    configure_logging(verbose=False)
    assert logging.getLogger().level == logging.INFO


def test_redacts_tuples_to_lists():
    assert redact(({"token": "t"},)) == [{"token": REDACTED}]


def test_redact_preserves_non_string_keys():
    assert redact({1: "x"}) == {1: "x"}
