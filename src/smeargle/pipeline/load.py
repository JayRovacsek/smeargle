"""Stage 0: detect, load, deduplicate, and persist input documents (spec 10)."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from smeargle.domain.documents import Document
from smeargle.domain.ids import doc_id_for
from smeargle.loaders import registry
from smeargle.store.run_store import RunStore


def run_load(store: RunStore, run_id: str, input_paths: Iterable[Path]) -> list[Document]:
    store.start_stage(run_id, "load")
    loaded: list[Document] = []
    seen: set[str] = set()
    for path in (Path(p) for p in input_paths):
        raw = path.read_bytes()
        content_sha256 = doc_id_for(raw)
        if content_sha256 in seen:
            continue
        seen.add(content_sha256)
        media_type, text = registry.load_document(path)
        loaded.append(
            Document(
                run_id=run_id,
                doc_id=content_sha256,
                ordinal=0,
                path=str(path),
                uri=path.absolute().as_uri(),
                external_id=None,
                media_type=media_type,
                content_sha256=content_sha256,
                size_bytes=len(raw),
                text=text,
            )
        )

    loaded.sort(key=lambda document: document.content_sha256)
    ordered = [
        Document(
            run_id=document.run_id,
            doc_id=document.doc_id,
            ordinal=ordinal,
            path=document.path,
            uri=document.uri,
            external_id=document.external_id,
            media_type=document.media_type,
            content_sha256=document.content_sha256,
            size_bytes=document.size_bytes,
            text=document.text,
        )
        for ordinal, document in enumerate(loaded)
    ]
    for document in ordered:
        store.add_document(document)
    store.complete_stage(run_id, "load")
    return ordered
