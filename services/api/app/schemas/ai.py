"""Schémas des sorties structurées de Claude. Bornes et longueurs validées ici, côté code
(elles sont retirées du JSON Schema envoyé à l'API, voir worker/llm/schema.py)."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Confiance = Literal["haute", "moyenne", "faible"]


# ---------- P-MATCH ----------
class MatchJudgement(BaseModel):
    score: int = Field(ge=0, le=100)
    raisons: list[str]
    bloquants_potentiels: list[str]
    valeur_probable_dans_fourchette: Literal["oui", "non", "inconnu"]

    @field_validator("raisons", "bloquants_potentiels")
    @classmethod
    def _trim(cls, v: list[str]) -> list[str]:
        return [s.strip()[:160] for s in v if s.strip()][:3]


class UnspscSuggestion(BaseModel):
    code: str
    raison: str


class UnspscSuggestions(BaseModel):
    suggestions: list[UnspscSuggestion]


class TenderEnrichment(BaseModel):
    resume: str
    mots_cles: list[str]


# ---------- P-ANALYSE ----------
SectionName = Literal["calendrier", "admissibilite", "portee", "adjudication", "clauses", "documents"]


class PageRange(BaseModel):
    document_id: str
    premiere_page: int = Field(ge=1)
    derniere_page: int = Field(ge=1)


class WorkerPlan(BaseModel):
    travailleur: SectionName
    plages: list[PageRange]
    remarque: str | None


class AddendumOrder(BaseModel):
    document_id: str
    numero: int


class AnalysisPlan(BaseModel):
    travailleurs: list[WorkerPlan]
    addenda: list[AddendumOrder]


class ExtractedField(BaseModel):
    cle: str
    valeur: str | None
    citation: str | None
    document_id: str | None
    page: int | None
    confiance: Confiance
    remarque: str | None


class SectionExtraction(BaseModel):
    champs: list[ExtractedField]


class Reextraction(BaseModel):
    travailleur: SectionName
    plages: list[PageRange]
    consigne: str


class Contradiction(BaseModel):
    cle: str
    description: str


class EvaluationReport(BaseModel):
    champs_critiques_manquants: list[str]
    contradictions: list[Contradiction]
    a_reextraire: list[Reextraction]
    commentaire: str | None


class ChecklistRewrite(BaseModel):
    field_id: str
    libelle: str


class ChecklistRewrites(BaseModel):
    elements: list[ChecklistRewrite]


class CitedPoint(BaseModel):
    texte: str
    field_id: str


class GoNoGoOut(BaseModel):
    recommandation: Literal["go", "go_avec_reserves", "no_go"]
    effort: Literal["faible", "moyen", "eleve"]
    resume: str
    forces: list[CitedPoint]
    risques: list[CitedPoint]
    bloquants: list[CitedPoint]


class MarketSummary(BaseModel):
    resume: str
