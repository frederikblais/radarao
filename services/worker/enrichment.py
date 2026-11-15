"""Enrichissement hebdomadaire des avis actifs (Haiku, API Message Batches : -50 %)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.app.models import Tender, TenderEmbedding, TenderItem
from api.app.schemas.ai import TenderEnrichment
from worker.ingestion.regions import REGIONS
from worker.llm.client import LlmClient
from worker.llm.prompts import load_prompt

MAX_PER_BATCH = 2000


def pending_tenders(db: Session) -> list[Tender]:
    return list(
        db.scalars(
            select(Tender)
            .where(Tender.status == "active", Tender.enriched_at.is_(None), Tender.source == "open_data")
            .limit(MAX_PER_BATCH)
        )
    )


def submit(db: Session, llm: LlmClient) -> str | None:
    tenders = pending_tenders(db)
    if not tenders:
        return None
    items: dict[str, list[str]] = {}
    for it in db.scalars(select(TenderItem).where(TenderItem.ocid.in_([t.ocid for t in tenders]))):
        items.setdefault(it.ocid, []).append(it.description or it.unspsc_code)
    system = load_prompt("tender_enrichment")
    reqs = []
    for t in tenders:
        meta = (
            f"Titre : {t.title}\nOrganisme : {t.buyer_name}\nCatégorie : {t.main_category}\n"
            f"Région : {REGIONS.get(t.region_code or '', 'inconnue')}\n"
            f"Classification : {'; '.join(items.get(t.ocid, []))}"
        )
        reqs.append((t.ocid.replace(":", "_")[:64], system, [{"role": "user", "content": f"<avis>\n{meta}\n</avis>"}]))
    return llm.submit_batch("enrichment", reqs, TenderEnrichment)


def collect(db: Session, llm: LlmClient, batch_id: str) -> int:
    results = llm.collect_batch("enrichment", batch_id, TenderEnrichment)
    n = 0
    for ocid, res in results.items():
        t = db.get(Tender, ocid)
        if t is None or res is None:
            continue
        t.summary_fr = res.resume[:400]
        t.keywords = [k[:60] for k in res.mots_cles[:8]]
        t.enriched_at = datetime.now(UTC)
        db.query(TenderEmbedding).filter(TenderEmbedding.ocid == ocid).delete()  # recalcul au prochain tri
        n += 1
    db.commit()
    return n
