"""Versioned prompt templates and content-addressed prompt hashes (spec 7.1, 8.1, 10)."""

from __future__ import annotations

from smeargle.domain.ids import sha256_hex

PROMPT_VERSION = "1"

UNTRUSTED_OPEN = "<<<UNTRUSTED-DOCUMENT-DATA>>>"
UNTRUSTED_CLOSE = "<<<END-UNTRUSTED-DOCUMENT-DATA>>>"


def prompt_hash(name: str, template: str) -> str:
    payload = f"smeargle-prompt/{PROMPT_VERSION}/{name}\0{template}"
    return sha256_hex(payload.encode("utf-8"))


def delimit_untrusted(text: str) -> str:
    return f"{UNTRUSTED_OPEN}\n{text}\n{UNTRUSTED_CLOSE}"
