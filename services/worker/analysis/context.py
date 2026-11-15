"""Construction des blocs « document » envoyés aux travailleurs (E2)."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

from api.app.models import Document
from api.app.services.storage import get_storage
from worker.analysis.pdf import stamp_pages

# En deçà, chaque travailleur reçoit les documents complets via la Files API (préfixe
# identique -> cache partagé entre les 6 travailleurs). Au-delà : sous-PDF par plages.
FULL_DOSSIER_MAX_PAGES = 150


@dataclass
class DocRef:
    alias: str
    doc: Document


def aliases(docs: list[Document]) -> dict[str, Document]:
    ordered = sorted(docs, key=lambda d: (d.kind == "addendum", d.addendum_number or 0, d.uploaded_at, d.id))
    return {f"D{i + 1}": d for i, d in enumerate(ordered)}


def stamped_key(doc: Document) -> str:
    return doc.s3_key.rsplit("/", 1)[0] + f"/stamped/{doc.id}.pdf"


def document_block(alias: str, doc: Document, pages: list[int] | None, use_file: bool) -> dict[str, Any]:
    title = f"{alias} — {doc.filename}"
    if use_file and doc.claude_file_id and pages is None:
        return {"type": "document", "source": {"type": "file", "file_id": doc.claude_file_id}, "title": title}
    data = get_storage().get(doc.s3_key)
    pdf = stamp_pages(data, alias, pages)
    if pages:
        title += f" (pages {pages[0]} à {pages[-1]})" if len(pages) > 1 else f" (page {pages[0]})"
    return {"type": "document", "title": title,
            "source": {"type": "base64", "media_type": "application/pdf", "data": base64.b64encode(pdf).decode()}}


def build_document_blocks(alias_map: dict[str, Document], plan_ranges: list[tuple[str, int, int]] | None,
                          total_pages: int) -> list[dict[str, Any]]:
    """plan_ranges : (alias, première, dernière) ou None pour tout le dossier."""
    blocks: list[dict[str, Any]] = []
    if plan_ranges is None or total_pages <= FULL_DOSSIER_MAX_PAGES:
        for alias, doc in alias_map.items():
            blocks.append(document_block(alias, doc, None, use_file=True))
    else:
        per_doc: dict[str, set[int]] = {}
        for alias, first, last in plan_ranges:
            per_doc.setdefault(alias, set()).update(range(first, last + 1))
        for alias, doc in alias_map.items():
            if alias in per_doc:
                pages = sorted(p for p in per_doc[alias] if 1 <= p <= doc.pages)
                if pages:
                    blocks.append(document_block(alias, doc, pages, use_file=False))
    if blocks:
        blocks[-1]["cache_control"] = {"type": "ephemeral"}
    return blocks
