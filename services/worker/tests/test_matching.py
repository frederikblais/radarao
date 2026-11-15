import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.app.models import Company, CompanyUnspsc, Match, Tender
from worker.embeddings import Embedder
from worker.ingestion.seao import ingest_payload
from worker.llm.client import LlmClient, LlmContext
from worker.matching.pipeline import run_match, unspsc_bonus
from worker.matching.unspsc import search, suggest
from worker.tests.fakes import FakeBackend

FIXTURE = Path(__file__).parent / "fixtures" / "hebdo_20261102_20261108_extrait.json"
NOW = datetime(2026, 11, 6, tzinfo=UTC)


def _company(db: Session, **kw: Any) -> Company:
    c = Company(
        name="Entretien Julie inc.",
        description="Entretien ménager commercial et institutionnel, conciergerie et nettoyage d'écoles et de bureaux",
        categories=["services", "goods"],
        regions=[],
        **kw,
    )
    db.add(c)
    db.flush()
    db.add(CompanyUnspsc(company_id=c.id, unspsc_code="76111500", label="Services de nettoyage"))
    db.add(CompanyUnspsc(company_id=c.id, unspsc_code="46171511", label="Dispositifs de verrouillage"))
    db.commit()
    db.refresh(c)
    return c


def test_unspsc_bonus() -> None:
    assert unspsc_bonus({"46171511"}, ["46171511"])[0] == 0.15
    assert unspsc_bonus({"46171599"}, ["46171511"])[0] == 0.10
    assert unspsc_bonus({"46179999"}, ["46171511"])[0] == 0.05
    assert unspsc_bonus({"72000000"}, ["46171511"])[0] == 0.0


def test_unspsc_search_and_suggestions() -> None:
    assert any(code == "76111501" or "nettoyage" in label.lower() for code, label in search(None, "nettoyage"))
    sugg = suggest(None, "Nous faisons de l'entretien ménager et du nettoyage de bureaux et d'écoles", None)
    assert len(sugg) >= 5 and all(len(s["code"]) == 8 for s in sugg)


def test_unspsc_llm_cannot_invent_codes() -> None:
    def responder(kind: str, params: dict[str, Any]) -> Any:
        return {"suggestions": [{"code": "99999999", "raison": "inventé"}, {"code": "46171511", "raison": "ok"}]}

    sugg = suggest(None, "serrures et clés, dispositifs de verrouillage", LlmClient(backend=FakeBackend(responder)))
    codes = [s["code"] for s in sugg]
    assert "99999999" not in codes and "46171511" in codes and len(codes) >= 5


def test_match_pipeline_filters_and_scores(db: Session) -> None:
    ingest_payload(db, json.loads(FIXTURE.read_text()), FIXTURE.name)
    c = _company(db)

    def responder(kind: str, params: dict[str, Any]) -> Any:
        assert kind == "judge"
        text = json.dumps(params["messages"], ensure_ascii=False)
        assert "Entretien Julie" not in text  # aucun nom d'entreprise envoyé au LLM
        return {
            "score": 95 if "entretien ménager" in text.lower() else 20,
            "raisons": ["Produit correspondant"],
            "bloquants_potentiels": [],
            "valeur_probable_dans_fourchette": "inconnu",
        }

    llm = LlmClient(LlmContext(company_id=c.id), backend=FakeBackend(responder))
    matches = run_match(db, c.id, llm=llm, embedder=Embedder(), now=NOW)
    assert matches, "au moins un avis doit passer les filtres"
    for m in matches:
        t = db.get(Tender, m.ocid)
        assert t is not None and t.status == "active" and t.end_date > NOW  # type: ignore[operator]
        assert t.main_category in ("goods", "services")
        assert 1 <= len(m.reasons) <= 3 and 0 <= m.score <= 100
    assert "ocds-ec9k95-20117866" not in {m.ocid for m in matches}  # avis annulé : jamais affiché
    top = matches[0]
    assert db.get(Tender, top.ocid).title == "Service d'entretien ménager"  # type: ignore[union-attr]
    assert "Code UNSPSC 76111500 correspondant" in top.reasons


def test_feedback_is_kept_on_rerun(db: Session) -> None:
    ingest_payload(db, json.loads(FIXTURE.read_text()), FIXTURE.name)
    c = _company(db)
    first = run_match(db, c.id, llm=None, embedder=Embedder(), now=NOW)
    first[0].user_feedback = "not_relevant"
    db.commit()
    run_match(db, c.id, llm=None, embedder=Embedder(), now=NOW)
    m = db.scalar(select(Match).where(Match.company_id == c.id, Match.ocid == first[0].ocid))
    assert m is not None and m.user_feedback == "not_relevant"
