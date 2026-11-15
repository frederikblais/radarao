"""Données de démonstration locales (make seed).

- ingère un fichier SEAO (le vrai fichier hebdomadaire si fourni, sinon l'extrait des tests);
- crée le compte julie@example.com (entretien ménager, Estrie) et lance le tri;
- crée un dossier « [DÉMO] » analysé avec des réponses SIMULÉES (aucun appel à Claude) pour
  montrer l'interface sans clé API. Ce dossier est étiqueté comme tel.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from api.app.db import get_sessionmaker
from api.app.models import Company, CompanyUnspsc, Dossier, Job, User
from api.app.services.documents import add_document
from worker.analysis.pipeline import run_analysis
from worker.embeddings import Embedder
from worker.ingestion.seao import ingest_file
from worker.lakehouse.local import compute_local
from worker.llm.client import LlmClient, LlmContext
from worker.matching.pipeline import run_match
from worker.tests.fakes import FakeBackend, make_pdf
from worker.tests.test_analysis_pipeline import ADDENDUM, MAIN, responder

FIXTURE = Path(__file__).parents[1] / "worker" / "tests" / "fixtures" / "hebdo_20261102_20261108_extrait.json"
EMAIL = "julie@example.com"


def main(path: str | None) -> None:
    with get_sessionmaker()() as db:
        run = ingest_file(db, Path(path) if path else FIXTURE)
        print(f"ingestion : {run.file_name} +{run.inserted} ~{run.updated} (déjà vus : {run.skipped})")
        print("repères et prévisions (repli PostgreSQL) :", compute_local(db))
        user = db.scalar(select(User).where(User.email == EMAIL)) or User(email=EMAIL, role="admin")
        db.add(user)
        db.flush()
        if not user.company_id:
            c = Company(
                name="Entretien Julie inc. (démo)",
                size=12,
                categories=["services"],
                regions=["05", "16", "06"],
                description="Entretien ménager commercial et institutionnel : écoles, bureaux, centres de santé. "
                "Conciergerie, nettoyage de vitres et de planchers.",
                value_min=25_000,
                value_max=750_000,
                onboarding_completed=True,
                qualifications={
                    "rbq": {"held": False, "subcategories": []},
                    "amp": False,
                    "revenu_quebec": True,
                    "iso": [],
                    "insurance_amount": 2_000_000,
                    "bonding_capacity": None,
                },
            )
            db.add(c)
            db.flush()
            for code, label in [
                ("76111500", "Services de nettoyage et d'entretien de bâtiments"),
                ("76111501", "Services de nettoyage de bâtiments"),
                ("47131700", "Produits d'entretien"),
            ]:
                db.add(CompanyUnspsc(company_id=c.id, unspsc_code=code, label=label))
            user.company_id = c.id
            db.commit()
        cid = user.company_id
        matches = run_match(
            db, cid, llm=None, embedder=Embedder(), now=min(datetime.now(UTC), datetime(2026, 11, 9, tzinfo=UTC))
        )
        print(f"tri : {len(matches)} avis classés")
        if not db.scalar(select(Dossier).where(Dossier.company_id == cid, Dossier.title.like("[DÉMO]%"))):
            d = Dossier(
                company_id=cid,
                title="[DÉMO] Entretien ménager des immeubles municipaux — réponses simulées",
                consent_at=datetime.now(UTC),
            )
            db.add(d)
            db.flush()
            add_document(db, d, "Devis-principal.pdf", make_pdf(MAIN))
            add_document(db, d, "Addenda_no_1.pdf", make_pdf(ADDENDUM))
            job = Job(type="analysis", dossier_id=d.id, company_id=cid)
            db.add(job)
            db.commit()
            run_analysis(db, job.id, LlmClient(LlmContext(job.id, cid, d.id), backend=FakeBackend(responder)))
            print("dossier de démonstration analysé (réponses simulées)")
    print(f"Connexion : {EMAIL} (le lien magique s'affiche dans la console de l'API)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
