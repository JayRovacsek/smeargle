"""Deterministic identifiers, fingerprints, and config hashing (spec 5, 7.1)."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Iterable, Mapping, Protocol

SMEARGLE_NAMESPACE = uuid.UUID("c1a9f7e2-4d3b-4a6e-9f21-8b7c6d5e4f30")
RUN_FINGERPRINT_SALT = b"smeargle-run/1\0"


class IdFactory(Protocol):
    def run_uuid(self) -> str: ...

    def uuid_for(self, kind: str, stable_key: str) -> str: ...


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def doc_id_for(content: bytes) -> str:
    return sha256_hex(content)


def catalog_id_for(content: bytes) -> str:
    return sha256_hex(content)


def _sha256_text(*parts: str) -> str:
    hasher = hashlib.sha256()
    for part in parts:
        hasher.update(part.encode("utf-8"))
    return hasher.hexdigest()


def req_id_for(doc_content_sha256: str, normalized_text: str) -> str:
    return "req-" + _sha256_text(doc_content_sha256, normalized_text)


def pair_id_for(req_id: str, catalog_id: str, control_id: str) -> str:
    return _sha256_text(req_id, catalog_id, control_id)


def index_id_for(content_sha256: str, model_id: str, prompt_hash: str) -> str:
    return _sha256_text(content_sha256, model_id, prompt_hash)


def fingerprint(input_digests: Iterable[str], catalog_digests: Iterable[str]) -> str:
    hasher = hashlib.sha256()
    hasher.update(RUN_FINGERPRINT_SALT)
    for digest in sorted(input_digests):
        hasher.update(digest.encode("utf-8") + b"\0")
    hasher.update(b"|")
    for digest in sorted(catalog_digests):
        hasher.update(digest.encode("utf-8") + b"\0")
    return hasher.hexdigest()


def config_hash(config: Mapping[str, Any]) -> str:
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"), default=str)
    return sha256_hex(canonical.encode("utf-8"))


class UuidIdFactory:
    def run_uuid(self) -> str:
        return str(uuid.uuid4())

    def uuid_for(self, kind: str, stable_key: str) -> str:
        return str(uuid.uuid5(SMEARGLE_NAMESPACE, f"{kind}:{stable_key}"))
