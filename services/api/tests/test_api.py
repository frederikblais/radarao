import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.app.main import app
from api.app.models import Job
from worker.analysis.pipeline import run_analysis
from worker.ingestion.seao import ingest_payload
from worker.llm.client import LlmClient, LlmContext
from worker.tests.fakes import FakeBackend, make_pdf
from worker.tests.test_analysis_pipeline import ADDENDUM, MAIN, responder

FIXTURE = Path(__file__).parents[2] / "worker" / "tests" / "fixtures" / "hebdo_20261102_20261108_extrait.json"
PROFILE = {
    "name": "Entretien Julie inc.",
    "size": 12,
    "description": "Entretien ménager commercial et institutionnel",
    "categories": ["services"],
    "unspsc": [{"code": "76111500", "label": "Services de nettoyage"}],
    "regions": [],
    "qualifications": {"rbq": {"held": False}},
}


def login(client: TestClient, email: str, capsys: pytest.CaptureFixture[str]) -> str:
    assert client.post("/auth/magic-link", json={"email": email}).status_code == 202
    token = re.findall(r"token=([\w-]+)", capsys.readouterr().out)[-1]
    r = client.post("/auth/verify", json={"token": token})
    assert r.status_code == 200
    assert client.post("/auth/verify", json={"token": token}).status_code == 400  # usage unique
    return str(r.json()["token"])


def test_auth_required() -> None:
    with TestClient(app) as c:
        assert c.get("/me").status_code == 401
        assert c.get("/health/live").json() == {"status": "ok"}


def test_full_flow_and_isolation(db: Session, capsys: pytest.CaptureFixture[str]) -> None:
    ingest_payload(db, json.loads(FIXTURE.read_text()), FIXTURE.name)
    julie, marc = TestClient(app), TestClient(app)
    login(julie, "julie@example.com", capsys)
    tok_marc = login(marc, "marc@example.com", capsys)

    # F1 — onboarding
    assert julie.get("/tenders").status_code == 409  # profil à créer
    r = julie.post("/companies", json=PROFILE)
    assert r.status_code == 201
    cid = r.json()["id"]
    assert julie.get(f"/companies/{cid}/profile").json()["unspsc"][0]["code"] == "76111500"
    marc_c = marc.post("/companies", json={**PROFILE, "name": "Électricité Marc"}).json()["id"]
    assert marc.get(f"/companies/{cid}/profile").status_code == 404  # isolation
    assert marc.put(f"/companies/{cid}/profile", json=PROFILE).status_code == 404
    sugg = julie.post(
        f"/companies/{cid}/unspsc/suggest",
        json={"description": "Entretien ménager et nettoyage d'écoles et de bureaux"},
    ).json()
    assert len(sugg) >= 5

    # F3 / F4 — tri et fil
    from datetime import UTC, datetime

    from worker.embeddings import Embedder
    from worker.matching.pipeline import run_match

    run_match(db, cid, llm=None, embedder=Embedder(), now=datetime(2026, 11, 6, tzinfo=UTC))
    feed = julie.get("/tenders").json()
    assert feed["items"] and feed["freshness"] == "2026-11-08"
    ocid = feed["items"][0]["ocid"]
    assert julie.post(f"/tenders/{ocid}/feedback", json={"feedback": "not_relevant"}).status_code == 200
    assert ocid not in [i["ocid"] for i in julie.get("/tenders").json()["items"]]
    assert ocid in [i["ocid"] for i in julie.get("/tenders?follow=not_relevant").json()["items"]]
    assert marc.get("/tenders").json()["total"] == 0

    # F2 — avis manuel, visible seulement par son entreprise
    m = julie.post(
        "/tenders/manual",
        json={
            "tender_id": "AO-2027-1",
            "title": "Entretien du garage municipal",
            "end_date": "2027-01-15T11:00:00-05:00",
        },
    ).json()
    assert julie.get(f"/tenders/{m['ocid']}").status_code == 200
    assert marc.get(f"/tenders/{m['ocid']}").status_code == 404

    # F5 — dossier, téléversement, analyse (faux backend), fiche
    d = julie.post("/dossiers", json={"title": "Entretien ménager"}).json()
    files = [("files", ("devis.pdf", make_pdf(MAIN), "application/pdf"))]
    assert julie.post(f"/dossiers/{d['id']}/documents", files=files).status_code == 400  # consentement requis
    r = julie.post(f"/dossiers/{d['id']}/documents", files=files, data={"consent": "true"})
    assert r.status_code == 201
    julie.post(
        f"/dossiers/{d['id']}/documents", files=[("files", ("Addenda 1.pdf", make_pdf(ADDENDUM), "application/pdf"))]
    )
    bad = julie.post(f"/dossiers/{d['id']}/documents", files=[("files", ("x.pdf", b"pas un pdf", "application/pdf"))])
    assert bad.status_code == 422
    assert marc.get(f"/dossiers/{d['id']}").status_code == 404
    assert marc.post(f"/dossiers/{d['id']}/documents", files=files, data={"consent": "true"}).status_code == 404

    job = julie.post(f"/dossiers/{d['id']}/analyze").json()
    assert job["status"] == "queued"
    assert marc.get(f"/jobs/{job['id']}").status_code == 404
    db_job = db.get(Job, job["id"])
    assert db_job is not None
    run_analysis(db, job["id"], LlmClient(LlmContext(job["id"], cid, d["id"]), backend=FakeBackend(responder)))
    assert julie.get(f"/jobs/{job['id']}").json()["progress"] == 100

    fiche = julie.get(f"/dossiers/{d['id']}/fiche").json()
    all_fields = [f for s in fiche["sections"] for f in s["fields"]]
    assert all(f["page"] for f in all_fields if f["value"] is not None)
    assert fiche["addenda"] and fiche["addenda"][0]["changes"][0]["old"]
    mode = next(f for f in all_fields if f["key"] == "mode_depot")
    assert mode["to_verify"]
    r = julie.patch(f"/dossiers/{d['id']}/fiche/fields/{mode['id']}", json={"action": "correct", "value": "papier"})
    assert r.json()["verified_status"] == "user_corrected" and not r.json()["to_verify"]

    # Le visualiseur reçoit le PDF; jamais de file_id Claude exposé
    doc = julie.get(f"/dossiers/{d['id']}").json()["documents"][0]
    assert "claude_file_id" not in doc
    assert julie.get(f"/dossiers/{d['id']}/documents/{doc['id']}/file").content.startswith(b"%PDF")
    assert marc.get(f"/dossiers/{d['id']}/documents/{doc['id']}/file").status_code == 404

    # F6 — liste de vérification
    items = julie.get(f"/dossiers/{d['id']}/checklist").json()
    assert items[0]["blocking"] and items[0]["source_page"]
    new = julie.post(
        f"/dossiers/{d['id']}/checklist",
        json={"label": "Faire signer le bordereau par Julie", "assignee": "Julie", "due_date": "2027-11-15"},
    ).json()
    assert julie.patch(f"/dossiers/{d['id']}/checklist/{new['id']}", json={"done": True}).json()["done"]
    pdf = julie.get(f"/dossiers/{d['id']}/checklist.pdf")
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    assert julie.delete(f"/dossiers/{d['id']}/checklist/{new['id']}").status_code == 204

    # F7 — go / no-go
    g = julie.get(f"/dossiers/{d['id']}/go-no-go").json()
    assert g["recommendation"] != "go" and g["warning"]
    assert all(p["page"] for p in g["strengths"] + g["risks"] + g["blockers"])

    # Loi 25 — suppression complète
    assert julie.delete(f"/dossiers/{d['id']}").status_code == 204
    assert julie.get(f"/dossiers/{d['id']}").status_code == 404

    # Jeton Bearer (clients iOS / macOS)
    assert TestClient(app).get("/me", headers={"Authorization": f"Bearer {tok_marc}"}).status_code == 200
    assert marc_c


def test_openapi_is_generated() -> None:
    spec = TestClient(app).get("/openapi.json").json()
    for path in ("/dossiers/{dossier_id}/fiche", "/tenders", "/market/insights", "/market/renewals", "/devices"):
        assert path in spec["paths"]
