"""F2 — Ingestion des fichiers JSON des données ouvertes du SEAO.

Idempotence : clé (ocid, release.id) dans `tender_releases`. Une publication déjà vue est
ignorée; une publication plus récente (selon release.id) met à jour l'avis, une plus ancienne
est seulement archivée dans l'historique.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError
from sqlalchemy import delete, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from api.app.config import get_settings
from api.app.models import ContractAward, IngestionRun, Party, Tender, TenderItem, TenderRelease
from worker.ingestion.ocds import ReleaseIn, parse_seao_date

log = logging.getLogger("radarao.ingestion")

FILE_RE = re.compile(r"(hebdo|mensuel)_(\d{8})_(\d{8})[\w-]*\.json$")


@dataclass
class IngestStats:
    releases: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0


def file_period_end(file_name: str) -> datetime | None:
    m = FILE_RE.search(file_name)
    if not m:
        return None
    return datetime.strptime(m.group(3), "%Y%m%d").replace(tzinfo=UTC)


def _status_for(rel: ReleaseIn) -> str:
    assert rel.tender is not None
    if "tenderCancellation" in rel.tag:
        return "cancelled"
    return rel.tender.status


def _value_of(rel: ReleaseIn) -> float | None:
    t = rel.tender
    if t is None:
        return None
    for v in (t.value, t.minValue):
        if v and v.amount:
            return v.amount
    amounts = [c.value.amount for c in rel.contracts if c.value and c.value.amount]
    return sum(amounts) if amounts else None


def _apply_release(db: Session, rel: ReleaseIn, tender: Tender | None) -> Tender:
    t = rel.tender
    assert t is not None
    buyer = rel.buyer_party()
    if tender is None:
        tender = Tender(ocid=rel.ocid, source="open_data")
        db.add(tender)
    tender.tender_id = t.id
    tender.title = t.title.strip()
    tender.status = _status_for(rel)
    tender.buyer_party_id = buyer.id if buyer else None
    tender.buyer_name = buyer.name if buyer else (t.procuringEntity.name if t.procuringEntity else None)
    tender.procurement_method = t.procurementMethod
    tender.procurement_method_details = t.procurementMethodDetails
    tender.main_category = t.mainProcurementCategory
    tender.start_date = parse_seao_date(t.tenderPeriod.startDate if t.tenderPeriod else None)
    tender.end_date = parse_seao_date(t.tenderPeriod.endDate if t.tenderPeriod else None)
    tender.value_amount = _value_of(rel)
    tender.number_of_tenderers = t.numberOfTenderers
    # Seul lien documenté : tender/documents[].url (ne jamais construire d'URL à la main).
    tender.seao_url = next((d.url for d in t.documents if d.url), None)
    tender.region_code = buyer.region_code if buyer else None
    tender.raw = rel.model_dump(mode="json", exclude_none=True)
    tender.last_release_date = parse_seao_date(rel.date)
    tender.last_release_id = rel.id
    tender.updated_at = datetime.now(UTC)
    if tender.status != "active":
        tender.enriched_at = tender.enriched_at  # conservé; l'enrichissement ne vise que les actifs

    db.flush()
    db.execute(delete(TenderItem).where(TenderItem.ocid == rel.ocid))
    seen: set[str] = set()
    for item in t.items:
        classes = ([item.classification] if item.classification else []) + item.additionalClassifications
        for i, c in enumerate(classes):
            if (c.scheme or "UNSPSC").upper() != "UNSPSC" or c.id in seen:
                continue
            seen.add(c.id)
            db.add(
                TenderItem(
                    ocid=rel.ocid,
                    unspsc_code=c.id[:8],
                    description=c.description,
                    is_main=(i == 0 and item.classification is not None),
                )
            )
    return tender


def _upsert_parties(db: Session, releases: Iterable[ReleaseIn]) -> None:
    rows: dict[str, dict[str, Any]] = {}
    for rel in releases:
        for p in rel.parties:
            prev = rows.get(p.id)
            roles = sorted(set(p.roles) | set(prev["roles"] if prev else []))
            rows[p.id] = {
                "id": p.id[:64],
                "name": p.name[:500],
                "neq": (p.neq or None) and str(p.neq)[:20],
                "locality": (p.address.locality or "")[:200] if p.address else None,
                "region": (p.address.region or "")[:60] if p.address else None,
                "region_code": p.region_code,
                "postal_code": (p.address.postalCode or "")[:40] if p.address else None,
                "roles": roles,
            }
    if not rows:
        return
    values = list(rows.values())
    for chunk_start in range(0, len(values), 1000):
        stmt = pg_insert(Party).values(values[chunk_start : chunk_start + 1000])
        stmt = stmt.on_conflict_do_update(
            index_elements=[Party.id],
            set_={
                "name": stmt.excluded.name,
                "neq": stmt.excluded.neq,
                "locality": stmt.excluded.locality,
                "region": stmt.excluded.region,
                "region_code": stmt.excluded.region_code,
                "postal_code": stmt.excluded.postal_code,
            },
        )
        db.execute(stmt)


def _upsert_awards(db: Session, rel: ReleaseIn, tender: Tender) -> None:
    if not rel.awards:
        return
    parties = {p.id: p for p in rel.parties}
    main_unspsc = next(
        (it.classification.id[:8] for it in (rel.tender.items if rel.tender else []) if it.classification), None
    )
    contract_amount = {c.awardID or c.id: c.value.amount for c in rel.contracts if c.value and c.value.amount}
    rows = []
    for a in rel.awards:
        amount = (a.value.amount if a.value and a.value.amount else None) or contract_amount.get(a.id)
        for s in a.suppliers or [None]:  # type: ignore[list-item]
            if s is None or not s.id:
                continue
            rows.append(
                {
                    "ocid": rel.ocid,
                    "award_id": a.id,
                    "supplier_party_id": s.id,
                    "supplier_name": (s.name or (parties[s.id].name if s.id in parties else ""))[:500],
                    "buyer_party_id": tender.buyer_party_id,
                    "buyer_name": tender.buyer_name,
                    "amount": amount,
                    "date": parse_seao_date(a.date),
                    "unspsc_main": main_unspsc,
                    "region_code": tender.region_code,
                    "main_category": tender.main_category,
                    "procurement_method": tender.procurement_method,
                    "number_of_tenderers": tender.number_of_tenderers,
                }
            )
    if rows:
        stmt = pg_insert(ContractAward).values(rows)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_award",
            set_={
                "amount": stmt.excluded.amount,
                "date": stmt.excluded.date,
                "number_of_tenderers": stmt.excluded.number_of_tenderers,
                "region_code": stmt.excluded.region_code,
            },
        )
        db.execute(stmt)


def ingest_payload(db: Session, payload: dict[str, Any], file_name: str) -> IngestionRun:
    """Ingère un fichier déjà chargé. Idempotent. Retourne l'exécution enregistrée."""
    started = time.monotonic()
    run = IngestionRun(
        file_name=file_name,
        file_date=file_period_end(file_name),
        published_date=parse_seao_date(payload.get("publishedDate")),
    )
    db.add(run)
    db.flush()
    stats = IngestStats()

    releases: list[ReleaseIn] = []
    for raw in payload.get("releases", []):
        stats.releases += 1
        try:
            releases.append(ReleaseIn.model_validate(raw))
        except ValidationError as exc:
            stats.errors += 1
            log.warning("publication invalide ignorée", extra={"error": str(exc)[:500]})
    releases.sort(key=lambda r: r.sort_key)

    # Publications déjà connues (idempotence) — une seule requête.
    keys = [(r.ocid, r.id) for r in releases]
    known: set[tuple[str, str]] = set()
    for i in range(0, len(keys), 2000):
        chunk = keys[i : i + 2000]
        known.update(
            (o, rid)
            for o, rid in db.execute(
                select(TenderRelease.ocid, TenderRelease.release_id).where(
                    tuple_(TenderRelease.ocid, TenderRelease.release_id).in_(chunk)
                )
            ).all()
        )
    new = [r for r in releases if (r.ocid, r.id) not in known]
    stats.skipped = len(releases) - len(new)

    _upsert_parties(db, new)
    ocids = list({r.ocid for r in new})
    tenders: dict[str, Tender] = {}
    for i in range(0, len(ocids), 2000):
        for t in db.scalars(select(Tender).where(Tender.ocid.in_(ocids[i : i + 2000]))):
            tenders[t.ocid] = t

    for rel in new:
        db.add(
            TenderRelease(
                ocid=rel.ocid,
                release_id=rel.id,
                tag=rel.tag,
                date=parse_seao_date(rel.date),
                raw=rel.model_dump(mode="json", exclude_none=True),
                ingestion_run_id=run.id,
            )
        )
        if rel.tender is None:
            continue
        existing = tenders.get(rel.ocid)
        if existing is not None and existing.last_release_id and existing.last_release_id.rjust(20, "0") > rel.sort_key:
            continue  # publication plus ancienne : historique seulement
        is_new = existing is None
        tenders[rel.ocid] = _apply_release(db, rel, existing)
        _upsert_awards(db, rel, tenders[rel.ocid])
        if is_new:
            stats.inserted += 1
        else:
            stats.updated += 1

    run.releases_count = stats.releases
    run.inserted, run.updated, run.skipped, run.errors = stats.inserted, stats.updated, stats.skipped, stats.errors
    run.duration_s = round(time.monotonic() - started, 2)
    run.finished_at = datetime.now(UTC)
    db.commit()
    log.info("ingestion terminée", extra={"file": file_name, **stats.__dict__, "duration_s": run.duration_s})
    return run


def ingest_file(db: Session, path: Path) -> IngestionRun:
    with path.open("rb") as fh:
        payload = json.load(fh)
    return ingest_payload(db, payload, path.name)


def latest_weekly_resource() -> tuple[str, str]:
    """Retourne (nom, url) du dernier fichier hebdomadaire publié sur Données Québec (API CKAN)."""
    s = get_settings()
    r = httpx.get(f"{s.ckan_api_url}/package_show", params={"id": s.seao_dataset_id}, timeout=30)
    r.raise_for_status()
    resources = r.json()["result"]["resources"]
    weekly = [res for res in resources if FILE_RE.search(res.get("name", "")) and res["name"].startswith("hebdo_")]
    if not weekly:
        raise RuntimeError("Aucun fichier hebdomadaire trouvé dans le jeu de données SEAO")
    latest = max(weekly, key=lambda res: FILE_RE.search(res["name"]).group(3))  # type: ignore[union-attr]
    return latest["name"], latest["url"]


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", url, timeout=300, follow_redirects=True) as r:
        r.raise_for_status()
        with dest.open("wb") as fh:
            for chunk in r.iter_bytes():
                fh.write(chunk)
    return dest


def freshness(db: Session) -> datetime | None:
    """Date de fraîcheur des données : fin de la période du dernier fichier ingéré."""
    return db.scalar(
        select(IngestionRun.file_date)
        .where(IngestionRun.finished_at.is_not(None))
        .order_by(IngestionRun.file_date.desc().nulls_last())
        .limit(1)
    )
