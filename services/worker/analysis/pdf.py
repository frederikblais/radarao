"""Outils PDF (PyMuPDF) : texte par page, détection du type, tampon de pagination."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

import pymupdf

SCANNED_MIN_CHARS = 40
_ADDENDA_RE = re.compile(r"\baddend(?:a|um)\s*(?:n(?:o|°|º|um[ée]ro)\.?\s*)?(\d{1,2})\b", re.I)


def _plain(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c))


@dataclass
class PdfInfo:
    pages: list[str]
    scanned_pages: list[int]
    encrypted: bool = False
    unreadable: bool = False
    toc: list[str] | None = None


def read_pdf(data: bytes) -> PdfInfo:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:  # noqa: BLE001 — fichier corrompu
        return PdfInfo([], [], unreadable=True)
    if doc.needs_pass:
        return PdfInfo([], [], encrypted=True)
    pages = [doc[i].get_text("text") for i in range(doc.page_count)]
    scanned = [i + 1 for i, t in enumerate(pages) if len(t.strip()) < SCANNED_MIN_CHARS]
    toc = [f"{'  ' * (lvl - 1)}{title} (p. {pno})" for lvl, title, pno in doc.get_toc()][:80]
    return PdfInfo(pages, scanned, toc=toc or None)


def detect_kind(filename: str, first_page: str, is_first: bool) -> tuple[str, int | None]:
    """Règles simples (nom de fichier, première page). L'utilisateur peut corriger."""
    name = _plain(filename)
    head = _plain(first_page[:600])
    for src in (name.replace("_", " ").replace("-", " "), head):
        m = _ADDENDA_RE.search(src)
        if m:
            return "addendum", int(m.group(1))
    if "addenda" in name or "addendum" in name or head.lstrip().startswith("addenda"):
        return "addendum", None
    if "formulaire" in name or "bordereau" in name or "form" in name.split("."):
        return "form", None
    if "devis" in name or "cahier des charges" in head:
        return "devis", None
    return ("main" if is_first else "other"), None


def stamp_pages(data: bytes, alias: str, pages: list[int] | None = None) -> bytes:
    """Copie du PDF où chaque page porte « [[D1 · p. 12]] » en marge supérieure.

    Le modèle lit ainsi le vrai numéro de page même quand on ne lui envoie qu'une plage
    (sous-PDF). Le texte de référence du vérificateur E4 est extrait AVANT le tampon.
    """
    src = pymupdf.open(stream=data, filetype="pdf")
    out = pymupdf.open()
    selected = pages or list(range(1, src.page_count + 1))
    for pno in selected:
        out.insert_pdf(src, from_page=pno - 1, to_page=pno - 1)
        page = out[-1]
        rect = page.rect
        page.insert_text((rect.x0 + 18, rect.y0 + 12), f"[[{alias} · p. {pno}]]", fontsize=7, color=(0.35, 0.35, 0.35))
    result: bytes = out.tobytes(garbage=3, deflate=True)
    return result
