"""Représentations du profil d'entreprise. `profile_for_llm` exclut les renseignements
personnels et identifiants (nom, NEQ, coordonnées) — section 10.6."""

from __future__ import annotations

import json
from typing import Any

from api.app.models import Company
from worker.ingestion.regions import REGIONS

QUALIF_LABELS = {
    "rbq": "Licence RBQ", "amp": "Autorisation de contracter de l'AMP",
    "revenu_quebec": "Attestation de Revenu Québec", "iso": "Certifications ISO",
    "insurance_amount": "Assurance responsabilité ($)", "bonding_capacity": "Capacité de cautionnement ($)",
}


def accepted_codes(company: Company) -> list[tuple[str, str | None]]:
    return [(u.unspsc_code, u.label) for u in company.unspsc if u.accepted]


def profile_text(company: Company) -> str:
    """Texte embarqué (input_type « query »)."""
    codes = "; ".join(f"{c} {label or ''}".strip() for c, label in accepted_codes(company))
    cats = ", ".join(company.categories or [])
    return f"{company.description}\nCatégories : {cats}\nCodes UNSPSC : {codes}".strip()


def qualifications_summary(q: dict[str, Any]) -> dict[str, Any]:
    rbq = q.get("rbq") or {}
    return {
        "licence_rbq": {"detenue": bool(rbq.get("held")), "sous_categories": rbq.get("subcategories", [])},
        "autorisation_amp": bool(q.get("amp")),
        "attestation_revenu_quebec": bool(q.get("revenu_quebec")),
        "certifications_iso": q.get("iso", []),
        "assurance_responsabilite": q.get("insurance_amount"),
        "capacite_cautionnement": q.get("bonding_capacity"),
    }


def profile_for_llm(company: Company) -> str:
    data = {
        "description_activites": company.description,
        "taille_employes": company.size,
        "categories": company.categories,
        "regions_desservies": [REGIONS.get(r, r) for r in company.regions or []],
        "fourchette_valeur_contrats": {"min": company.value_min, "max": company.value_max},
        "codes_unspsc": [{"code": c, "libelle": label} for c, label in accepted_codes(company)],
        "qualifications": qualifications_summary(company.qualifications or {}),
    }
    return json.dumps(data, ensure_ascii=False, indent=1)
