from __future__ import annotations

import base64
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from api.app.db import get_db
from api.app.models import Company, Dossier, IngestionRun, Match, Party, Tender, TenderItem, TenderRelease
from api.app.schemas.api import FeedbackIn, FeedOut, ManualTenderIn, TenderCard, TenderDetail, TrackIn
from api.app.security import current_company

router = APIRouter(tags=["tenders"])


def _region_name(code: str | None) -> str | None:
    from worker.ingestion.regions import REGIONS

    return REGIONS.get(code or "")


def _card(t: Tender, m: Match | None, dossier_id: str | None) -> TenderCard:
    return TenderCard(
        ocid=t.ocid,
        tender_id=t.tender_id,
        title=t.title,
        buyer_name=t.buyer_name,
        buyer_party_id=t.buyer_party_id,
        main_category=t.main_category,
        region_code=t.region_code,
        region_name=_region_name(t.region_code),
        end_date=t.end_date,
        seao_url=t.seao_url,
        source=t.source,
        score=m.score if m else None,
        reasons=m.reasons if m else [],
        blockers=m.blockers if m else [],
        feedback=m.user_feedback if m else None,
        tracked=m.tracked if m else False,
        dossier_id=dossier_id,
    )


def _visible(company: Company) -> Any:
    """Avis publics, ou avis manuels de l'entreprise elle-même seulement."""
    return or_(Tender.source == "open_data", Tender.created_by_company_id == company.id)


def freshness_date(db: Session) -> datetime | None:
    return db.scalar(
        select(IngestionRun.file_date)
        .where(IngestionRun.finished_at.is_not(None))
        .order_by(IngestionRun.file_date.desc().nulls_last())
        .limit(1)
    )


@router.get("/freshness")
def freshness(db: Session = Depends(get_db)) -> dict[str, object]:
    f = freshness_date(db)
    return {
        "date": f.date().isoformat() if f else None,
        "note": "Les données ouvertes du SEAO ont jusqu'à une semaine de décalage sur le SEAO en direct.",
    }


@router.get("/tenders", response_model=FeedOut)
def feed(
    min_score: int = Query(0, ge=0, le=100),
    category: str | None = None,
    region: str | None = None,
    buyer: str | None = None,
    deadline_before: datetime | None = None,
    follow: str | None = Query(None, pattern="^(tracked|relevant|not_relevant|new)$"),
    cursor: str | None = None,
    limit: int = Query(25, ge=1, le=100),
    company: Company = Depends(current_company),
    db: Session = Depends(get_db),
) -> FeedOut:
    now = datetime.now(UTC)
    conds: list[Any] = [
        Match.company_id == company.id,
        Tender.status == "active",
        Tender.end_date > now,
        _visible(company),
        Match.score >= min_score,
    ]
    if category:
        conds.append(Tender.main_category == category)
    if region:
        conds.append(Tender.region_code == region)
    if buyer:
        conds.append(Tender.buyer_party_id == buyer)
    if deadline_before:
        conds.append(Tender.end_date <= deadline_before)
    if follow == "tracked":
        conds.append(Match.tracked.is_(True))
    elif follow in ("relevant", "not_relevant"):
        conds.append(Match.user_feedback == follow)
    elif follow == "new":
        conds.append(Match.user_feedback.is_(None))
    else:
        conds.append(Match.user_feedback.is_distinct_from("not_relevant"))
    total = (
        db.scalar(select(func.count()).select_from(Match).join(Tender, Tender.ocid == Match.ocid).where(*conds)) or 0
    )
    q = select(Tender, Match).join(Match, Match.ocid == Tender.ocid).where(*conds)
    if cursor:
        try:
            score_s, ocid = base64.urlsafe_b64decode(cursor.encode()).decode().split("|", 1)
            score = int(score_s)
        except (ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Curseur invalide.") from exc
        q = q.where(or_(Match.score < score, and_(Match.score == score, Tender.ocid > ocid)))
    rows = db.execute(q.order_by(Match.score.desc(), Tender.ocid).limit(limit + 1)).all()
    page, more = rows[:limit], len(rows) > limit
    dossiers = dict(
        db.execute(
            select(Dossier.ocid, Dossier.id).where(
                Dossier.company_id == company.id, Dossier.ocid.in_([t.ocid for t, _ in page])
            )
        ).all()
    )
    nxt = None
    if more:
        t, m = page[-1]
        nxt = base64.urlsafe_b64encode(f"{m.score}|{t.ocid}".encode()).decode()
    f = freshness_date(db)
    return FeedOut(
        items=[_card(t, m, dossiers.get(t.ocid)) for t, m in page],
        next_cursor=nxt,
        freshness=f.date() if f else None,
        total=total,
    )


@router.get("/buyers")
def buyers(
    q: str = Query(min_length=2), company: Company = Depends(current_company), db: Session = Depends(get_db)
) -> list[dict[str, str]]:
    rows = db.execute(
        select(Party.id, Party.name)
        .where(Party.roles.contains(["buyer"]), Party.name.ilike(f"%{q}%"))
        .order_by(Party.name)
        .limit(20)
    ).all()
    return [{"id": i, "name": n} for i, n in rows]


def _get_tender(db: Session, ocid: str, company: Company) -> Tender:
    t = db.get(Tender, ocid)
    if t is None or (t.source == "manual" and t.created_by_company_id != company.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Avis introuvable.")
    return t


@router.get("/tenders/{ocid}", response_model=TenderDetail)
def tender_detail(
    ocid: str, company: Company = Depends(current_company), db: Session = Depends(get_db)
) -> TenderDetail:
    t = _get_tender(db, ocid, company)
    m = db.get(Match, (company.id, ocid))
    dossier_id = db.scalar(select(Dossier.id).where(Dossier.company_id == company.id, Dossier.ocid == ocid))
    items = [
        {"code": i.unspsc_code, "label": i.description, "is_main": i.is_main}
        for i in db.scalars(select(TenderItem).where(TenderItem.ocid == ocid))
    ]
    history = [
        {"release_id": r.release_id, "tags": r.tag, "date": r.date.isoformat() if r.date else None}
        for r in db.scalars(select(TenderRelease).where(TenderRelease.ocid == ocid).order_by(TenderRelease.release_id))
    ]
    card = _card(t, m, dossier_id)
    return TenderDetail(
        **card.model_dump(),
        status=t.status,
        procurement_method=t.procurement_method,
        procurement_method_details=t.procurement_method_details,
        start_date=t.start_date,
        value_amount=t.value_amount,
        number_of_tenderers=t.number_of_tenderers,
        summary_fr=t.summary_fr,
        items_unspsc=items,
        history=history,
        value_in_range=m.value_in_range if m else None,
    )


@router.post("/tenders/manual", response_model=TenderCard, status_code=status.HTTP_201_CREATED)
def manual_tender(
    body: ManualTenderIn, company: Company = Depends(current_company), db: Session = Depends(get_db)
) -> TenderCard:
    """F2 : ajout à la main (numéro et titre), pour ne pas rater une échéance courte."""
    ocid = f"manual-{company.id[:8]}-{body.tender_id}"[:80]
    t = db.get(Tender, ocid) or Tender(ocid=ocid)
    t.tender_id, t.title, t.status, t.source = body.tender_id, body.title, "active", "manual"
    t.buyer_name, t.end_date, t.main_category = body.buyer_name, body.end_date, body.main_category
    t.region_code, t.seao_url, t.created_by_company_id = body.region_code, body.seao_url, company.id
    db.add(t)
    m = db.get(Match, (company.id, ocid)) or Match(company_id=company.id, ocid=ocid, score=100)
    m.reasons, m.blockers, m.tracked, m.model = ["Ajouté à la main"], [], True, "manual"
    db.add(m)
    db.commit()
    return _card(t, m, None)


@router.post("/tenders/{ocid}/feedback", response_model=TenderCard)
def feedback(
    ocid: str, body: FeedbackIn, company: Company = Depends(current_company), db: Session = Depends(get_db)
) -> TenderCard:
    t = _get_tender(db, ocid, company)
    m = db.get(Match, (company.id, ocid))
    if m is None:
        m = Match(company_id=company.id, ocid=ocid, score=0, reasons=[], blockers=[], model="none")
        db.add(m)
    m.user_feedback = body.feedback  # enregistré : sert à évaluer et améliorer le tri (evals/)
    db.commit()
    return _card(t, m, None)


@router.post("/tenders/{ocid}/track", response_model=TenderCard)
def track(
    ocid: str, body: TrackIn, company: Company = Depends(current_company), db: Session = Depends(get_db)
) -> TenderCard:
    t = _get_tender(db, ocid, company)
    m = db.get(Match, (company.id, ocid))
    if m is None:
        m = Match(company_id=company.id, ocid=ocid, score=0, reasons=[], blockers=[], model="none")
        db.add(m)
    m.tracked = body.tracked
    db.commit()
    return _card(t, m, None)
