"""Catalogue des champs de la fiche d'analyse (section 6, F5). Source unique pour les
travailleurs (prompts), la fusion, le vérificateur et l'interface."""

from dataclasses import dataclass
from typing import Literal

FieldType = Literal["datetime", "date", "amount", "percent_or_amount", "int", "bool", "text"]


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    type: FieldType = "text"
    critical: bool = False
    multi: bool = False  # plusieurs valeurs possibles (une par élément)
    future: bool = False  # date qui doit être dans le futur


SECTIONS: dict[str, tuple[str, list[FieldSpec]]] = {
    "calendrier": (
        "Calendrier et logistique",
        [
            FieldSpec("date_limite_depot", "Date et heure limite de dépôt", "datetime", critical=True, future=True),
            FieldSpec("mode_depot", "Mode de dépôt", critical=True),
            FieldSpec("adresse_depot", "Adresse de dépôt"),
            FieldSpec("visite_obligatoire", "Visite obligatoire", "bool", critical=True),
            FieldSpec("date_visite", "Date de la visite", "datetime"),
            FieldSpec("lieu_visite", "Lieu de la visite"),
            FieldSpec("date_limite_questions", "Date limite des questions", "datetime"),
            FieldSpec("ouverture_soumissions", "Ouverture des soumissions", "datetime"),
            FieldSpec("validite_soumission_jours", "Durée de validité de la soumission (jours)", "int"),
        ],
    ),
    "admissibilite": (
        "Admissibilité et conformité",
        [
            FieldSpec("licence_rbq", "Licence RBQ", critical=True),
            FieldSpec("sous_categories_rbq", "Sous-catégories RBQ"),
            FieldSpec("autorisation_amp", "Autorisation de contracter (AMP)", critical=True),
            FieldSpec("attestation_revenu_quebec", "Attestation de Revenu Québec"),
            FieldSpec("etablissement_quebec", "Établissement au Québec"),
            FieldSpec("garantie_soumission", "Garantie de soumission", "percent_or_amount", critical=True),
            FieldSpec("garantie_execution", "Garantie d'exécution", "percent_or_amount"),
            FieldSpec(
                "garantie_obligations", "Garantie des obligations (main-d'œuvre et matériaux)", "percent_or_amount"
            ),
            FieldSpec("assurances_requises", "Assurances requises"),
            FieldSpec("experience_minimale", "Expérience minimale", multi=True),
            FieldSpec("autre_exigence", "Autre exigence d'admissibilité", multi=True),
        ],
    ),
    "portee": (
        "Portée et exigences techniques",
        [
            FieldSpec("description_travaux", "Description des travaux ou services"),
            FieldSpec("lieu_execution", "Lieu d'exécution"),
            FieldSpec("quantites", "Quantités", multi=True),
            FieldSpec("normes_citees", "Normes citées", multi=True),
            FieldSpec("livrables", "Livrables", multi=True),
            FieldSpec("duree_contrat", "Durée du contrat"),
            FieldSpec("options_renouvellement", "Options de renouvellement"),
        ],
    ),
    "adjudication": (
        "Mode d'adjudication",
        [
            FieldSpec("mode_adjudication", "Mode d'adjudication", critical=True),
            FieldSpec("grille_evaluation", "Critère de la grille d'évaluation", multi=True),
            FieldSpec("seuil_qualite", "Seuil de qualité minimal"),
            FieldSpec("formule_prix_ajuste", "Formule du prix ajusté"),
        ],
    ),
    "clauses": (
        "Clauses contractuelles et risques",
        [
            FieldSpec("penalites_retard", "Pénalités de retard"),
            FieldSpec("retenues", "Retenues"),
            FieldSpec("modalites_paiement", "Modalités de paiement"),
            FieldSpec("resiliation", "Résiliation"),
            FieldSpec("indexation", "Indexation"),
            FieldSpec("autre_risque", "Autre clause à risque", multi=True),
        ],
    ),
    "documents": (
        "Documents à remettre",
        [
            FieldSpec("document_a_remettre", "Document à remettre", multi=True),
        ],
    ),
}

SECTION_ORDER = list(SECTIONS.keys())
SPECS: dict[str, FieldSpec] = {f.key: f for _, fields in SECTIONS.values() for f in fields}
SECTION_OF: dict[str, str] = {f.key: s for s, (_, fields) in SECTIONS.items() for f in fields}
CRITICAL_KEYS = [k for k, f in SPECS.items() if f.critical]


def catalog_for_prompt(section: str) -> str:
    _, fields = SECTIONS[section]
    lines = []
    for f in fields:
        flags = []
        if f.critical:
            flags.append("CRITIQUE")
        if f.multi:
            flags.append("plusieurs entrées possibles, une par élément")
        fmt = {
            "datetime": "date ISO 8601 avec heure et fuseau (ex. 2026-11-20T11:00:00-05:00)",
            "date": "date ISO 8601 (aaaa-mm-jj)",
            "amount": "montant numérique en dollars (ex. 25000.00)",
            "percent_or_amount": "pourcentage (ex. « 10 % ») ou montant (ex. « 25000.00 $ »)",
            "int": "nombre entier",
            "bool": "« oui » ou « non »",
            "text": "texte court et fidèle au document",
        }[f.type]
        extra = f" [{', '.join(flags)}]" if flags else ""
        lines.append(f"- `{f.key}` — {f.label} — format : {fmt}{extra}")
    return "\n".join(lines)
