"""_build_jev transport selection: chat default vs systemone (construction only)."""

from __future__ import annotations

import httpx
import openai

from smeargle.clients.jev import LayaJevClient
from smeargle.clients.jev_openai import OpenAiJevClient
from smeargle.config import Settings
from smeargle.pipeline.run import _build_jev


def _settings(**overrides):
    return Settings.load(overrides=overrides)


def test_build_jev_chat_default_returns_openai_jev_client():
    settings = _settings(
        llm={"base_url": "https://llm.example"},
        jev={"base_url": "https://jev.example"},
    )
    client, jev = _build_jev(settings, None)
    try:
        assert isinstance(jev, OpenAiJevClient)
        assert isinstance(client, openai.OpenAI)
        assert str(client.base_url).rstrip("/") == "https://jev.example/v1"
    finally:
        client.close()


def test_build_jev_chat_appends_v1_without_double_prefix():
    settings = _settings(
        llm={"base_url": "https://llm.example"},
        jev={"base_url": "https://jev.example/v1"},
    )
    client, jev = _build_jev(settings, None)
    try:
        assert isinstance(jev, OpenAiJevClient)
        assert str(client.base_url).rstrip("/").endswith("/v1")
        assert "/v1/v1" not in str(client.base_url)
    finally:
        client.close()


def test_build_jev_systemone_returns_laya_client():
    settings = _settings(
        llm={"base_url": "https://llm.example"},
        jev={"base_url": "https://jev.example", "transport": "systemone"},
    )
    client, jev = _build_jev(settings, None)
    try:
        assert isinstance(jev, LayaJevClient)
        assert isinstance(client, httpx.Client)
    finally:
        client.close()
