"""E3 — Fusion des sorties des travailleurs et application des addenda (code pur).

Règles :
- champ à valeur unique : la valeur du document de rang le plus élevé gagne (dossier principal
  = rang 0, addenda n = rang n, appliqués dans l'ordre de leur numéro). Les valeurs antérieures
  restent dans la fiche, barrées, avec `superseded_by` vers la nouvelle.
- à rang égal, la confiance la plus élevée gagne; les doublons identiques sont retirés.
- champ à valeurs multiples : chaque élément distinct est conservé.
- un `document_id` qui n'appartient pas au dossier est rejeté (confiance faible).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from api.app.models.base import new_id
from api.app.schemas.ai import ExtractedField
from worker.analysis.catalog import SECTION_OF, SPECS
from worker.analysis.verifier import normalize

CONF_RANK = {"haute": 3, "moyenne": 2, "faible": 1}
CONF_MAP = {"haute": "high", "moyenne": "medium", "faible": "low"}


@dataclass
class MergedField:
    id: str
    section: str
    key: str
    value: str | None
    citation: str | None
    document_id: str | None
    page: int | None
    confidence: str  # high | medium | low
    note: str | None
    step: str
    rank: int = 0
    superseded_by: str | None = None
    notes: list[str] = field(default_factory=list)


def merge_fields(extractions: list[tuple[str, str, list[ExtractedField]]],
                 doc_ranks: dict[str, int]) -> list[MergedField]:
    """extractions : (section, étape, champs). doc_ranks : document_id -> rang (0 ou n° d'addenda)."""
    candidates: list[MergedField] = []
    for section, step, fields in extractions:
        for f in fields:
            key = f.cle.strip()
            if key not in SPECS:
                continue  # clé hors catalogue : ignorée (le schéma de section fait foi)
            sec = SECTION_OF[key] if SECTION_OF.get(key) else section
            doc_ok = f.document_id in doc_ranks
            notes = [] if doc_ok or f.document_id is None else ["Document cité inconnu dans ce dossier."]
            conf = f.confiance if doc_ok else "faible"
            candidates.append(MergedField(
                id=new_id(), section=sec, key=key,
                value=f.valeur.strip() if f.valeur and f.valeur.strip() else None,
                citation=(f.citation or None), document_id=f.document_id if doc_ok else None,
                page=f.page, confidence=CONF_MAP[conf], note=f.remarque, step=step,
                rank=doc_ranks.get(f.document_id or "", 0), notes=notes,
            ))

    out: list[MergedField] = []
    by_key: dict[str, list[MergedField]] = {}
    for c in candidates:
        by_key.setdefault(c.key, []).append(c)

    for key, items in by_key.items():
        spec = SPECS[key]
        found = [i for i in items if i.value is not None]
        if not found:
            # « Non trouvé » : on garde un seul témoin pour signaler l'absence.
            out.append(max(items, key=lambda i: CONF_RANK.get(_back(i.confidence), 0)))
            continue
        if spec.multi:
            seen: dict[str, MergedField] = {}
            for i in sorted(found, key=lambda i: (-i.rank, -CONF_RANK[_back(i.confidence)])):
                k = normalize(i.value or "")
                if k not in seen:
                    seen[k] = i
            out.extend(seen.values())
            continue
        # valeur unique : meilleur candidat par rang, chaîne de remplacement entre rangs
        best_by_rank: dict[int, MergedField] = {}
        for i in found:
            cur = best_by_rank.get(i.rank)
            if cur is None or CONF_RANK[_back(i.confidence)] > CONF_RANK[_back(cur.confidence)]:
                best_by_rank[i.rank] = i
        chain = [best_by_rank[r] for r in sorted(best_by_rank)]
        # Un addenda qui répète la même valeur ne crée pas de remplacement.
        dedup: list[MergedField] = []
        for i in chain:
            if dedup and normalize(dedup[-1].value or "") == normalize(i.value or ""):
                continue
            dedup.append(i)
        for older, newer in zip(dedup, dedup[1:], strict=False):
            older.superseded_by = newer.id
        out.extend(dedup)
    return out


def _back(conf: str) -> str:
    return {"high": "haute", "medium": "moyenne", "low": "faible"}.get(conf, conf)
