"""E6 — Synthèse : liste de vérification (F6) et recommandation go / no-go (F7)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from api.app.models import Company, FicheField
from api.app.schemas.ai import ChecklistRewrites, GoNoGoOut
from worker.analysis.catalog import SPECS
from worker.analysis.verifier import normalize
from worker.llm.client import LlmClient, LlmError
from worker.llm.prompts import load_prompt
from worker.matching.profile import profile_for_llm

CHECKLIST_KEYS_T2 = {
    "licence_rbq",
    "sous_categories_rbq",
    "autorisation_amp",
    "attestation_revenu_quebec",
    "etablissement_quebec",
    "garantie_soumission",
    "garantie_execution",
    "garantie_obligations",
    "assurances_requises",
    "experience_minimale",
    "autre_exigence",
}
DISCLAIMER = (
    "Cette recommandation est une aide à la décision. Elle ne remplace ni la lecture complète "
    "du dossier ni l'avis d'un conseiller juridique. La décision et le dépôt vous appartiennent."
)

_NOT_REQUIRED = ("non requis", "non requise", "aucun", "aucune", "non exige", "non exigee", "n/a", "non")


def _required(value: str | None) -> bool:
    if not value:
        return False
    v = normalize(value)
    v_plain = v.replace("é", "e").replace("è", "e")
    return not any(v_plain.startswith(x) for x in _NOT_REQUIRED)


@dataclass
class Blocker:
    field_id: str
    reason: str


def find_blockers(fields: list[FicheField], company: Company) -> list[Blocker]:
    """Comparaison déterministe fiche ↔ profil (qualifications détenues)."""
    q = company.qualifications or {}
    rbq = q.get("rbq") or {}
    held_sub = {normalize(s) for s in rbq.get("subcategories", [])}
    out: list[Blocker] = []
    for f in fields:
        val = f.value if isinstance(f.value, str) else (json.dumps(f.value) if f.value is not None else None)
        if f.superseded_by_field_id or not _required(val):
            continue
        if f.key == "licence_rbq" and not rbq.get("held"):
            out.append(Blocker(f.id, "Licence RBQ exigée : votre profil n'indique aucune licence RBQ."))
        elif f.key == "sous_categories_rbq" and rbq.get("held") and val:
            import re

            needed = {normalize(m) for m in re.findall(r"\b\d{1,2}\.\d{1,2}(?:\.\d{1,2})?\b", val)}
            missing = needed - held_sub
            if missing:
                out.append(
                    Blocker(
                        f.id,
                        f"Sous-catégorie(s) RBQ exigée(s) absente(s) de votre profil : {', '.join(sorted(missing))}.",
                    )
                )
        elif f.key == "autorisation_amp" and not q.get("amp"):
            out.append(Blocker(f.id, "Autorisation de contracter de l'AMP exigée : absente de votre profil."))
        elif f.key == "attestation_revenu_quebec" and not q.get("revenu_quebec"):
            out.append(Blocker(f.id, "Attestation de Revenu Québec exigée : absente de votre profil."))
        elif f.key in ("garantie_soumission", "garantie_execution") and not q.get("bonding_capacity"):
            out.append(Blocker(f.id, "Garantie exigée : votre profil n'indique aucune capacité de cautionnement."))
    return out


def checklist_candidates(fields: list[FicheField]) -> list[FicheField]:
    return [
        f
        for f in fields
        if f.superseded_by_field_id is None
        and f.value not in (None, "")
        and (f.key in CHECKLIST_KEYS_T2 or f.key == "document_a_remettre")
        and (
            f.key not in ("licence_rbq", "autorisation_amp", "attestation_revenu_quebec", "etablissement_quebec")
            or _required(str(f.value))
        )
    ]


MOIS = [
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
]


def human_value(value: object) -> str:
    """Les dates ISO deviennent « 20 novembre 2027 à 11 h 00 » dans les textes affichés."""
    s = str(value)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?([+-]\d{2}:\d{2}|Z)?)?", s):
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        out = f"{dt.day} {MOIS[dt.month - 1]} {dt.year}"
        return out + (f" à {dt.hour} h {dt.minute:02d}" if "T" in s else "")
    return s


def default_label(f: FicheField) -> str:
    if f.key == "document_a_remettre":
        return f"Joindre : {f.value}"
    return f"{SPECS[f.key].label} : {human_value(f.value)}"


def rewrite_labels(llm: LlmClient | None, items: list[FicheField]) -> dict[str, str]:
    labels = {f.id: default_label(f) for f in items}
    if llm is None or not items:
        return labels
    payload = [{"field_id": f.id, "exigence": default_label(f), "citation": f.citation} for f in items]
    try:
        out = llm.structured(
            "E6_checklist",
            "synthesis",
            load_prompt("synthesis_checklist"),
            [{"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=1)}],
            ChecklistRewrites,
        )
    except LlmError:
        return labels
    for e in out.elements:
        if e.field_id in labels and e.libelle.strip():
            labels[e.field_id] = e.libelle.strip()[:300]
    return labels


def fiche_for_llm(fields: list[FicheField], id_to_alias: dict[str, str]) -> list[dict[str, Any]]:
    return [
        {
            "field_id": f.id,
            "section": f.section,
            "champ": SPECS[f.key].label if f.key in SPECS else f.key,
            "valeur": f.value,
            "document": id_to_alias.get(f.document_id or ""),
            "page": f.page,
            "confiance": f.confidence,
            "verification": f.verified_status,
        }
        for f in fields
        if f.superseded_by_field_id is None
    ]


def heuristic_go_no_go(fields: list[FicheField], blockers: list[Blocker]) -> GoNoGoOut:
    from api.app.schemas.ai import CitedPoint

    current = [f for f in fields if f.superseded_by_field_id is None and f.value is not None]
    docs = sum(1 for f in current if f.key == "document_a_remettre")
    low = [f for f in current if f.critical and f.confidence == "low"]
    effort = "eleve" if docs > 12 else ("moyen" if docs > 5 else "faible")
    by_key = {f.key: f for f in current}
    strengths = [
        CitedPoint(texte=f"{SPECS[k].label} : {human_value(by_key[k].value)}", field_id=by_key[k].id)
        for k in ("mode_adjudication", "date_limite_depot", "description_travaux")
        if k in by_key
    ]
    risks = [CitedPoint(texte=f"{SPECS[f.key].label} à vérifier à la main", field_id=f.id) for f in low]
    risks += [
        CitedPoint(texte=f"{SPECS[k].label} : {by_key[k].value}", field_id=by_key[k].id)
        for k in ("penalites_retard", "garantie_soumission", "visite_obligatoire")
        if k in by_key
    ]
    rec = "no_go" if blockers else ("go_avec_reserves" if low else "go")
    return GoNoGoOut(
        recommandation=rec,
        effort=effort,
        resume="Synthèse générée par règles (IA indisponible). " + DISCLAIMER,
        forces=strengths,
        risques=risks,
        bloquants=[CitedPoint(texte=b.reason, field_id=b.field_id) for b in blockers],
    )


def go_no_go(
    llm: LlmClient | None,
    fields: list[FicheField],
    company: Company,
    blockers: list[Blocker],
    id_to_alias: dict[str, str],
) -> tuple[GoNoGoOut, str | None]:
    """Retourne (synthèse, avertissement). Les points qui citent un field_id inexistant sont retirés."""
    out: GoNoGoOut | None = None
    if llm is not None:
        user = (
            "<fiche>\n" + json.dumps(fiche_for_llm(fields, id_to_alias), ensure_ascii=False, indent=1) + "\n</fiche>\n"
            "<profil>\n" + profile_for_llm(company) + "\n</profil>\n"
            "<bloquants_detectes>\n"
            + json.dumps([b.__dict__ for b in blockers], ensure_ascii=False)
            + "\n</bloquants_detectes>"
        )
        try:
            out = llm.structured(
                "E6_go_no_go", "synthesis", load_prompt("go_no_go"), [{"role": "user", "content": user}], GoNoGoOut
            )
        except LlmError:
            out = None
    if out is None:
        out = heuristic_go_no_go(fields, blockers)
    valid = {f.id for f in fields}
    out.forces = [p for p in out.forces if p.field_id in valid]
    out.risques = [p for p in out.risques if p.field_id in valid]
    out.bloquants = [p for p in out.bloquants if p.field_id in valid]
    from api.app.schemas.ai import CitedPoint

    if len(out.forces) + len(out.risques) + len(out.bloquants) < 3:  # F7 : au moins 3 éléments cités
        h = heuristic_go_no_go(fields, blockers)
        cited = {p.field_id for p in [*out.forces, *out.risques, *out.bloquants]}
        for p in h.forces:
            if p.field_id not in cited:
                out.forces.append(p)
                cited.add(p.field_id)
        for p in h.risques:
            if p.field_id not in cited:
                out.risques.append(p)
                cited.add(p.field_id)
    for b in blockers:  # tout bloquant du code apparaît, même si le LLM l'a omis
        if not any(p.field_id == b.field_id for p in out.bloquants):
            out.bloquants.append(CitedPoint(texte=b.reason, field_id=b.field_id))
    warning = None
    if out.bloquants and out.recommandation == "go":
        out.recommandation = "go_avec_reserves"
        warning = "Un bloquant non résolu empêche une recommandation « Go » sans réserve."
    if out.bloquants:
        warning = warning or "Au moins un bloquant n'est pas résolu : vérifiez-le avant de soumissionner."
    if DISCLAIMER not in out.resume:
        out.resume = out.resume.rstrip() + "\n\n" + DISCLAIMER
    return out, warning
