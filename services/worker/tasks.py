"""Tâches Celery. Chaque tâche ouvre sa propre session de base de données."""

from __future__ import annotations

import logging
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from api.app.config import get_settings
from api.app.db import get_sessionmaker
from api.app.models import Company, Dossier, Match, Tender, User
from api.app.services.dossiers import delete_dossier
from worker.analysis.pipeline import run_analysis
from worker.celery_app import app
from worker.ingestion import seao
from worker.llm.client import LlmClient, LlmError
from worker.matching.pipeline import run_match
from worker.notifications import email

log = logging.getLogger("radarao.tasks")


@app.task(name="worker.tasks.ingest_latest", autoretry_for=(OSError,), retry_backoff=True, max_retries=3)
def ingest_latest() -> dict[str, object]:
    name, url = seao.latest_weekly_resource()
    with get_sessionmaker()() as db:
        from api.app.models import IngestionRun

        if db.scalar(
            select(IngestionRun.id).where(IngestionRun.file_name == name, IngestionRun.finished_at.is_not(None))
        ):
            return {"file": name, "status": "déjà ingéré"}
        with tempfile.TemporaryDirectory() as tmp:
            path = seao.download(url, Path(tmp) / name)
            run = seao.ingest_file(db, path)
            result: dict[str, object] = {
                "file": name,
                "inserted": run.inserted,
                "updated": run.updated,
                "errors": run.errors,
            }
            result["lakehouse"] = sync_lakehouse(db, name, path)
    enrich_tenders.delay()
    match_all.delay()
    return result


def sync_lakehouse(db, file_name: str | None = None, path: Path | None = None) -> dict[str, object]:  # type: ignore[no-untyped-def]
    """Tandem PostgreSQL + Databricks : le fichier brut part au lakehouse, la couche or revient en cache."""
    import json

    from worker.lakehouse import local
    from worker.lakehouse.client import LakehouseError
    from worker.lakehouse.pipeline import lakehouse, load_file, refresh, setup, sync_to_postgres

    lh = lakehouse()
    if lh is None:
        return {"backend": "postgres", **local.compute_local(db)}
    try:
        setup(lh)
        if file_name and path:
            load_file(lh, file_name, json.loads(path.read_text(encoding="utf-8")))
        refresh(lh)
        return {"backend": "databricks", **sync_to_postgres(lh, db)}
    except LakehouseError as exc:  # le lakehouse ne doit jamais bloquer l'ingestion opérationnelle
        log.error("lakehouse en échec", extra={"error": str(exc)[:500]})
        return {"backend": "postgres (repli)", "error": str(exc)[:200], **local.compute_local(db)}


@app.task(name="worker.tasks.lakehouse_refresh")
def lakehouse_refresh() -> dict[str, object]:
    with get_sessionmaker()() as db:
        return sync_lakehouse(db)


@app.task(name="worker.tasks.enrich_tenders")
def enrich_tenders() -> dict[str, object]:
    from worker import enrichment

    with get_sessionmaker()() as db:
        try:
            llm = LlmClient()
            batch_id = enrichment.submit(db, llm)
        except LlmError as exc:
            return {"status": f"ignoré : {exc}"}
        if batch_id is None:
            return {"status": "rien à enrichir"}
        deadline = time.monotonic() + 23 * 3600
        while not llm.batch_done(batch_id):
            if time.monotonic() > deadline:
                return {"status": "lot non terminé", "batch_id": batch_id}
            time.sleep(60)
        n = enrichment.collect(db, llm, batch_id)
    match_all.delay()
    return {"enriched": n}


@app.task(name="worker.tasks.match_all")
def match_all() -> int:
    with get_sessionmaker()() as db:
        ids = db.scalars(select(Company.id).where(Company.onboarding_completed.is_(True))).all()
    for cid in ids:
        match_company.delay(cid)
    return len(ids)


@app.task(name="worker.tasks.match_company")
def match_company(company_id: str) -> int:
    with get_sessionmaker()() as db:
        matches = run_match(db, company_id)
        send_instant_alerts(db, company_id)
        return len(matches)


def send_instant_alerts(db, company_id: str) -> None:  # type: ignore[no-untyped-def]
    s = get_settings()
    users = db.scalars(select(User).where(User.company_id == company_id, User.instant_alerts.is_(True))).all()
    if not users:
        return
    threshold = min(u.alert_threshold for u in users)
    rows = db.execute(
        select(Match, Tender)
        .join(Tender, Tender.ocid == Match.ocid)
        .where(
            Match.company_id == company_id,
            Match.score >= threshold,
            Match.alerted_at.is_(None),
            Match.user_feedback.is_(None),
        )
    ).all()
    now = datetime.now(UTC)
    for m, t in rows:
        days = (t.end_date - now).days if t.end_date else None
        for u in users:
            if m.score >= u.alert_threshold:
                email.instant_alert(u.email, t.title, t.buyer_name, m.score, days, f"{s.web_base_url}/avis/{t.ocid}")
        m.alerted_at = now
    db.commit()


@app.task(name="worker.tasks.weekly_digest")
def weekly_digest() -> int:
    s = get_settings()
    sent = 0
    with get_sessionmaker()() as db:
        fresh = seao.freshness(db)
        fresh_txt = fresh.strftime("%Y-%m-%d") if fresh else "inconnue"
        now = datetime.now(UTC)
        for u in db.scalars(select(User).where(User.weekly_digest.is_(True), User.company_id.is_not(None))):
            rows = db.execute(
                select(Match, Tender)
                .join(Tender, Tender.ocid == Match.ocid)
                .where(
                    Match.company_id == u.company_id,
                    Tender.status == "active",
                    Tender.end_date > now,
                    Match.user_feedback.is_distinct_from("not_relevant"),
                )
                .order_by(Match.score.desc())
                .limit(10)
            ).all()
            email.weekly_digest(
                u.email,
                fresh_txt,
                [
                    (
                        t.title,
                        t.buyer_name,
                        m.score,
                        (t.end_date - now).days if t.end_date else None,
                        f"{s.web_base_url}/avis/{t.ocid}",
                    )
                    for m, t in rows
                ],
            )
            sent += 1
    return sent


@app.task(name="worker.tasks.analyze_dossier", bind=True)
def analyze_dossier(self, job_id: str, retry_failed: bool = False) -> str:  # type: ignore[no-untyped-def]
    with get_sessionmaker()() as db:
        job = run_analysis(db, job_id, retry_failed=retry_failed)
        return job.status


@app.task(name="worker.tasks.purge_expired")
def purge_expired() -> int:
    """Loi 25 : suppression des dossiers arrivés au terme de leur durée de conservation."""
    with get_sessionmaker()() as db:
        expired = db.scalars(select(Dossier).where(Dossier.delete_after < datetime.now(UTC))).all()
        for d in expired:
            delete_dossier(db, d)
        return len(expired)
