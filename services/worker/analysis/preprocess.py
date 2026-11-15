"""E0 — Prétraitement (code, sans LLM)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from api.app.models import Document, DocumentPage, Dossier
from api.app.services.storage import get_storage
from worker.analysis.context import aliases, stamped_key
from worker.analysis.pdf import detect_kind, read_pdf, stamp_pages
from worker.embeddings import Embedder
from worker.llm.client import files_backend

log = logging.getLogger("radarao.analysis")
FILES_TTL_S = 30 * 24 * 3600


def preprocess(db: Session, dossier: Dossier, fb: Any = None) -> dict[str, object]:
    docs = list(db.scalars(select(Document).where(Document.dossier_id == dossier.id)))
    storage = get_storage()
    embedder = Embedder()
    fb = fb if fb is not None else files_backend()
    problems: list[str] = []
    seen_hashes: dict[str, str] = {}
    first = True
    for doc in sorted(docs, key=lambda d: d.uploaded_at):
        if doc.sha256 in seen_hashes:
            doc.status = "duplicate"
            problems.append(f"{doc.filename} est identique à un autre fichier du dossier : ignoré.")
            continue
        seen_hashes[doc.sha256] = doc.id
        already = db.scalar(select(DocumentPage.page_number).where(DocumentPage.document_id == doc.id).limit(1))
        if already is not None and doc.status == "ready":
            first = False
            continue  # fichier déjà prétraité : pas de réanalyse
        data = storage.get(doc.s3_key)
        info = read_pdf(data)
        if info.encrypted:
            doc.status = "encrypted"
            problems.append(f"{doc.filename} est protégé par un mot de passe.")
            continue
        if info.unreadable or not info.pages:
            doc.status = "unreadable"
            problems.append(f"{doc.filename} est illisible.")
            continue
        doc.pages = len(info.pages)
        doc.scanned_pages = info.scanned_pages
        if doc.kind in (None, "", "other") or doc.kind == "auto":
            kind, num = detect_kind(doc.filename, info.pages[0], first)
            doc.kind, doc.addendum_number = kind, num if kind == "addendum" else doc.addendum_number
        first = False
        db.execute(delete(DocumentPage).where(DocumentPage.document_id == doc.id))
        vectors = embedder.embed([p[:8000] or " " for p in info.pages], input_type="document")
        for i, (text, vec) in enumerate(zip(info.pages, vectors, strict=True), start=1):
            db.add(DocumentPage(document_id=doc.id, page_number=i, text=text, embedding=vec))
        doc.status = "ready"
        if info.scanned_pages:
            problems.append(f"{doc.filename} : {len(info.scanned_pages)} page(s) numérisée(s) lue(s) en image.")
    db.flush()

    ready = [d for d in docs if d.status == "ready"]
    alias_map = aliases(ready)
    for alias, doc in alias_map.items():
        stamped = stamp_pages(storage.get(doc.s3_key), alias)
        storage.put(stamped_key(doc), stamped)
        if fb is not None and not doc.claude_file_id:
            # file_id conservé côté serveur seulement; jamais accepté du client.
            doc.claude_file_id = fb.upload_file(f"{doc.id}.pdf", stamped, FILES_TTL_S)
    db.commit()
    return {
        "aliases": {a: d.id for a, d in alias_map.items()},
        "total_pages": sum(d.pages for d in ready),
        "problems": problems,
    }
