import json

import pytest

from smeargle.errors import InputError
from smeargle.loaders import json_text


def _flatten(value):
    return json_text.flatten_value(value)


def test_root_scalar_uses_dollar():
    assert _flatten(42) == "$ = 42"
    assert _flatten("x") == '$ = "x"'
    assert _flatten(None) == "$ = null"


def test_object_keys_are_sorted_and_dotted():
    value = {"b": 2, "a": {"d": True, "c": None}}
    assert _flatten(value) == "a.c = null\na.d = true\nb = 2"


def test_arrays_use_index_paths():
    value = {"items": [1, "two", {"x": 3}]}
    assert _flatten(value) == 'items[0] = 1\nitems[1] = "two"\nitems[2].x = 3'


def test_empty_containers_render_as_leaves():
    assert _flatten({"a": {}, "b": []}) == "a = {}\nb = []"


def test_json_to_text_is_deterministic():
    text = '{"b": 1, "a": 2}'
    assert json_text.json_to_text(text) == "a = 2\nb = 1"
    assert json_text.json_to_text(text) == json_text.json_to_text(text)


def test_invalid_json_is_rejected():
    with pytest.raises(InputError):
        json_text.json_to_text("{not json")


def test_load_json_returns_media_type(tmp_path):
    path = tmp_path / "a.json"
    path.write_text(json.dumps({"a": 1}), encoding="utf-8")
    media_type, content = json_text.load_json(path)
    assert media_type == "application/json"
    assert content == "a = 1"
