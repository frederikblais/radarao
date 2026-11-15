"""Téléversement de PDF : validation, assainissement, empreinte, stockage."""

from __future__ import annotations

import hashlib
import re
import unicodedata

from sqlalchemy.orm import Session

from api.app.config import get_settings
from api.app.models import Document, Dossier
from api.app.services.storage import get_storage


class UploadError(ValueError):
    pass


def sanitize_filename(name: str) -> str:
    name = unicodedata.normalize("NFKC", name).replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^\w.\- ()À-ÿ]", "_", name).strip(" .") or "document.pdf"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name[:200]


def add_document(db: Session, dossier: Dossier, filename: str, data: bytes, kind: str | None = None,
                 addendum_number: int | None = None) -> Document:
    s = get_settings()
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise UploadError(f"Fichier trop volumineux (maximum {s.max_upload_mb} Mo).")
    if not data.startswith(b"%PDF-"):
        raise UploadError("Seuls les fichiers PDF sont acceptés.")
    if kind is not None and kind not in ("main", "devis", "form", "addendum", "other"):
        raise UploadError("Type de document invalide.")
    doc = Document(dossier_id=dossier.id, filename=sanitize_filename(filename), kind=kind or "auto",
                   addendum_number=addendum_number, sha256=hashlib.sha256(data).hexdigest(),
                   size_bytes=len(data), s3_key="")
    db.add(doc)
    db.flush()
    doc.s3_key = f"companies/{dossier.company_id}/dossiers/{dossier.id}/{doc.id}.pdf"
    get_storage().put(doc.s3_key, data)
    db.commit()
    return doc
