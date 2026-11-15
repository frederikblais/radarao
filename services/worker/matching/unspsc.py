"""Codes UNSPSC : autocomplétion et suggestions à partir d'une description libre (F1)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.app.models import TenderItem
from api.app.schemas.ai import UnspscSuggestions
from worker.embeddings import _stem, normalize_text, tokens
from worker.llm.client import LlmClient, LlmError
from worker.llm.prompts import load_prompt

CATALOG_PATH = Path(__file__).with_name("unspsc_catalog.json")
MIN_SUGGESTIONS = 5


@lru_cache
def base_catalog() -> dict[str, str]:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return {c["code"]: c["label"] for c in data["codes"]}


def catalog(db: Session | None = None) -> dict[str, str]:
    cat = dict(base_catalog())
    if db is not None:
        rows = db.execute(
            select(TenderItem.unspsc_code, func.max(TenderItem.description)).group_by(TenderItem.unspsc_code)
        ).all()
        for code, label in rows:
            if label and code not in cat:
                cat[code] = label
    return cat


def search(db: Session | None, q: str, limit: int = 20) -> list[tuple[str, str]]:
    cat = catalog(db)
    q = q.strip()
    if q.isdigit():
        return [(c, lab) for c, lab in sorted(cat.items()) if c.startswith(q)][:limit]
    terms = [_stem(t) for t in tokens(q)]
    if not terms:
        return []
    scored = []
    for code, label in cat.items():
        lt = [_stem(t) for t in tokens(label)]
        hits = sum(1 for t in terms if any(x.startswith(t) for x in lt))
        if hits:
            scored.append((hits / len(terms) + (0.2 if normalize_text(q) in normalize_text(label) else 0), code, label))
    scored.sort(key=lambda x: (-x[0], len(x[2])))
    return [(c, lab) for _, c, lab in scored[:limit]]


def candidates(db: Session | None, description: str, k: int = 60) -> list[tuple[str, str]]:
    cat = catalog(db)
    words = {_stem(t) for t in tokens(description)}
    scored = []
    for code, label in cat.items():
        lt = {_stem(t) for t in tokens(label)}
        overlap = len(words & lt)
        if overlap:
            scored.append((overlap / (len(lt) ** 0.5), code, label))
    scored.sort(key=lambda x: -x[0])
    return [(c, lab) for _, c, lab in scored[:k]]


def suggest(db: Session | None, description: str, llm: LlmClient | None) -> list[dict[str, str]]:
    """Au moins 5 suggestions, toujours tirées du catalogue (le LLM ne peut pas inventer de code)."""
    cands = candidates(db, description)
    cat = dict(cands)
    out: list[dict[str, str]] = []
    if llm is not None and cands:
        listing = "\n".join(f"{c} — {lab}" for c, lab in cands)
        try:
            res = llm.structured(
                "F1_unspsc",
                "unspsc_suggest",
                load_prompt("unspsc_suggest"),
                [
                    {
                        "role": "user",
                        "content": f"<description>\n{description}\n</description>\n<codes_candidats>\n{listing}\n"
                        "</codes_candidats>",
                    }
                ],
                UnspscSuggestions,
            )
            for s in res.suggestions:
                if s.code in cat and all(o["code"] != s.code for o in out):
                    out.append({"code": s.code, "label": cat[s.code], "reason": s.raison[:120], "source": "llm"})
        except LlmError:
            pass
    for c, lab in cands:  # complément lexical pour garantir le minimum
        if len(out) >= max(MIN_SUGGESTIONS, 8):
            break
        if all(o["code"] != c for o in out):
            out.append({"code": c, "label": lab, "reason": "Mots communs avec votre description", "source": "lexical"})
    return out
