"""E4 — Vérificateur déterministe des citations (section 10.4). Aucun LLM ici.

Pour chaque champ : la citation est normalisée puis cherchée par correspondance approximative
(ratio ≥ 0,90) sur la page indiquée, puis sur les pages voisines (±1).
- trouvée sur la page indiquée  -> auto_ok
- trouvée sur une page voisine  -> page corrigée, auto_ok
- introuvable                   -> quote_not_found, confiance forcée à « faible »
Les valeurs sont aussi validées selon leur type (dates analysables, dépôt dans le futur,
montants numériques).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher

from dateutil import parser as dateparser

from worker.analysis.catalog import SPECS

THRESHOLD = 0.90

_QUOTES = {"‘": "'", "’": "'", "‚": "'", "′": "'", "`": "'", "´": "'", "“": '"', "”": '"', "«": '"', "»": '"', "„": '"'}
_DASHES = {"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-", "­": ""}


def normalize(text: str) -> str:
    """Minuscules, espaces, traits d'union, apostrophes et guillemets typographiques."""
    t = unicodedata.normalize("NFKC", text)
    for src, dst in {**_QUOTES, **_DASHES}.items():
        t = t.replace(src, dst)
    t = t.replace(" ", " ").replace(" ", " ").lower()
    t = re.sub(r"-\s*\n\s*", "", t)  # mot coupé en fin de ligne : « soumis-\nsion »
    t = re.sub(r"[\"']", "'", t)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s*([-'])\s*", r"\1", t)
    return t.strip(" .;:,")


def best_ratio(quote: str, page_text: str) -> float:
    q, p = normalize(quote), normalize(page_text)
    if not q or not p:
        return 0.0
    if q in p:
        return 1.0
    n = len(q)
    if n > len(p):
        return SequenceMatcher(None, q, p, autojunk=False).ratio()
    step = max(1, n // 4)
    best, best_i = 0.0, 0
    for i in range(0, len(p) - n + 1, step):
        sm = SequenceMatcher(None, q, p[i : i + n], autojunk=False)
        if sm.real_quick_ratio() < best or sm.quick_ratio() < best:
            continue
        r = sm.ratio()
        if r > best:
            best, best_i = r, i
    # Affinage autour du meilleur emplacement (fenêtres décalées et de longueur variable).
    for i in range(max(0, best_i - step), min(len(p) - n, best_i + step) + 1):
        for width in (n - max(1, n // 10), n, n + max(1, n // 10)):
            r = SequenceMatcher(None, q, p[i : i + width], autojunk=False).ratio()
            best = max(best, r)
    return best


@dataclass
class Verification:
    status: str  # auto_ok | quote_not_found | not_found
    page: int | None
    ratio: float
    value_error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "auto_ok" and self.value_error is None


def verify_quote(quote: str | None, page: int | None, pages: dict[int, str]) -> Verification:
    if not quote or page is None:
        return Verification("quote_not_found", page, 0.0)
    order = [page, page - 1, page + 1]
    best_page, best = page, 0.0
    for p in order:
        if p not in pages:
            continue
        r = best_ratio(quote, pages[p])
        if r >= THRESHOLD:
            return Verification("auto_ok", p, r)
        if r > best:
            best, best_page = r, p
    return Verification("quote_not_found", page, best if best_page else 0.0)


_AMOUNT_RE = re.compile(r"^\s*-?\d[\d\s  ]*([.,]\d+)?\s*(\$|\$ ?ca|cad)?\s*$", re.I)
_PERCENT_RE = re.compile(r"^\s*\d+([.,]\d+)?\s*%\s*$")


def validate_value(key: str, value: str | None, now: datetime | None = None) -> str | None:
    """Retourne un message d'erreur si la valeur ne respecte pas le type attendu, sinon None."""
    if value is None:
        return None
    spec = SPECS.get(key)
    if spec is None:
        return None
    v = value.strip()
    if spec.type in ("datetime", "date"):
        try:
            dt = dateparser.isoparse(v)
        except (ValueError, OverflowError):
            return "Date non analysable (format ISO 8601 attendu)."
        if spec.future:
            ref = now or datetime.now(UTC)
            cmp = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
            if cmp < ref:
                return "Date limite de dépôt déjà passée ou incohérente."
    elif spec.type == "amount":
        if not _AMOUNT_RE.match(v):
            return "Montant non numérique."
    elif spec.type == "percent_or_amount":
        if not (_PERCENT_RE.match(v) or _AMOUNT_RE.match(v) or re.search(r"\d", v)):
            return "Pourcentage ou montant attendu."
    elif spec.type == "int":
        if not re.fullmatch(r"\d+", v):
            return "Nombre entier attendu."
    elif spec.type == "bool" and normalize(v) not in ("oui", "non"):
        return "Valeur « oui » ou « non » attendue."
    return None
