"""Suppression complète d'un dossier (Loi 25) : base de données, stockage S3 ET Files API."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.app.models import Document, Dossier
from api.app.services.storage import get_storage

log = logging.getLogger("radarao.dossiers")


def delete_dossier(db: Session, dossier: Dossier) -> None:
    from worker.llm.client import files_backend

    docs = list(db.scalars(select(Document).where(Document.dossier_id == dossier.id)))
    fb = files_backend()
    for d in docs:
        if d.claude_file_id and fb is not None:
            try:
                fb.delete_file(d.claude_file_id)
            except Exception as exc:  # noqa: BLE001 — on poursuit, l'expiration (30 j) fait le reste
                log.warning("suppression Files API en échec", extra={"document_id": d.id, "error": str(exc)[:200]})
    get_storage().delete_prefix(f"companies/{dossier.company_id}/dossiers/{dossier.id}")
    db.delete(dossier)  # cascade : documents, pages, fiche, liste, go/no-go, messages, jobs
    db.commit()
