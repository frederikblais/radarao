"""Export PDF de la liste de vérification (F6), imprimable."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pymupdf


def checklist_to_pdf(title: str, items: list[Any], doc_names: dict[str, str]) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    y = 50.0

    def write(
        text: str,
        size: float = 10,
        bold: bool = False,
        color: tuple[float, float, float] = (0, 0, 0),
        indent: float = 0,
    ) -> None:
        nonlocal page, y
        rect = pymupdf.Rect(50 + indent, y, 545, y + 200)
        h = page.insert_textbox(rect, text, fontsize=size, fontname="hebo" if bold else "helv", color=color)
        used = 200 - h if h >= 0 else 200
        y += max(used, size * 1.4) + 4
        if y > 780:
            page = doc.new_page()
            y = 50.0

    write("Liste de vérification de soumission", 16, True, (0.06, 0.2, 0.45))
    write(title, 12, True)
    write(
        f"Générée par RadarAO le {datetime.now(UTC):%Y-%m-%d}. Aide à la préparation : lisez le dossier complet.",
        8,
        color=(0.35, 0.35, 0.35),
    )
    y += 6
    for i in items:
        box = "[x]" if i.done else "[  ]"
        flag = "  BLOQUANT" if i.blocking else ""
        src = ""
        if i.source_page:
            src = f" (source : {doc_names.get(i.source_document_id or '', 'document')}, p. {i.source_page})"
        write(f"{box} {i.label}{flag}", 10, i.blocking, (0.7, 0.1, 0.1) if i.blocking else (0, 0, 0))
        details = [
            d
            for d in [
                i.blocking_reason,
                f"Responsable : {i.assignee}" if i.assignee else None,
                f"Échéance interne : {i.due_date}" if i.due_date else None,
                src.strip() or None,
            ]
            if d
        ]
        if details:
            write(" · ".join(details), 8, color=(0.35, 0.35, 0.35), indent=22)
    data: bytes = doc.tobytes()
    return data
