from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.app.db import get_db
from api.app.models import Company, CompanyUnspsc, User
from api.app.schemas.api import ProfileIn, ProfileOut, SuggestIn, UnspscOut
from api.app.security import current_user, own_company, rate_limit
from api.app.services.tasks import enqueue

router = APIRouter(tags=["companies"])


def to_out(c: Company) -> ProfileOut:
    return ProfileOut(
        id=c.id,
        name=c.name,
        neq=c.neq,
        size=c.size,
        description=c.description,
        categories=c.categories or [],
        unspsc=[
            {"code": u.unspsc_code, "label": u.label, "source": u.source, "accepted": u.accepted} for u in c.unspsc
        ],
        regions=c.regions or [],
        postal_code=c.postal_code,
        radius_km=c.radius_km,
        value_min=c.value_min,
        value_max=c.value_max,
        qualifications=c.qualifications or {},
        buyer_preferences=c.buyer_preferences or {},
        onboarding_completed=c.onboarding_completed,
    )


def apply(c: Company, body: ProfileIn) -> None:
    if body.value_min is not None and body.value_max is not None and body.value_min > body.value_max:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "La valeur minimale dépasse la valeur maximale.")
    for k in (
        "name",
        "neq",
        "size",
        "description",
        "categories",
        "regions",
        "postal_code",
        "radius_km",
        "value_min",
        "value_max",
        "onboarding_completed",
    ):
        setattr(c, k, getattr(body, k))
    c.qualifications = body.qualifications.model_dump()
    c.buyer_preferences = body.buyer_preferences.model_dump()
    seen: dict[str, CompanyUnspsc] = {u.unspsc_code: u for u in c.unspsc}
    wanted = {u.code for u in body.unspsc}
    c.unspsc = [u for u in c.unspsc if u.unspsc_code in wanted]
    for u in body.unspsc:
        row = seen.get(u.code)
        if row is None:
            row = CompanyUnspsc(unspsc_code=u.code)
            c.unspsc.append(row)
        row.label, row.source, row.accepted = u.label, u.source, u.accepted


@router.post("/companies", response_model=ProfileOut, status_code=status.HTTP_201_CREATED)
def create_company(body: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> ProfileOut:
    if user.company_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Vous avez déjà un profil d'entreprise.")
    c = Company(name=body.name)
    db.add(c)
    apply(c, body)
    db.flush()
    user.company_id = c.id
    db.commit()
    if c.onboarding_completed:
        enqueue("worker.tasks.match_company", c.id)
    return to_out(c)


@router.get("/companies/{company_id}/profile", response_model=ProfileOut)
def get_profile(company: Company = Depends(own_company)) -> ProfileOut:
    return to_out(company)


@router.put("/companies/{company_id}/profile", response_model=ProfileOut)
def put_profile(body: ProfileIn, company: Company = Depends(own_company), db: Session = Depends(get_db)) -> ProfileOut:
    apply(company, body)
    db.commit()
    enqueue("worker.tasks.match_company", company.id)  # F1 : toute modification relance le tri
    return to_out(company)


@router.post(
    "/companies/{company_id}/unspsc/suggest",
    response_model=list[UnspscOut],
    dependencies=[Depends(rate_limit("suggest", "rate_limit_chat_per_hour"))],
)
def suggest_unspsc(
    body: SuggestIn, company: Company = Depends(own_company), db: Session = Depends(get_db)
) -> list[UnspscOut]:
    from worker.llm.client import LlmClient, LlmContext, LlmError
    from worker.matching.unspsc import suggest

    llm: LlmClient | None
    try:
        llm = LlmClient(LlmContext(company_id=company.id))
        _ = llm.backend
    except LlmError:
        llm = None
    return [UnspscOut(**s) for s in suggest(db, body.description, llm)]


@router.get("/unspsc", response_model=list[UnspscOut])
def search_unspsc(
    q: str = Query(min_length=2, max_length=100), _: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[UnspscOut]:
    from worker.matching.unspsc import search

    return [UnspscOut(code=c, label=lab) for c, lab in search(db, q)]


@router.get("/regions")
def regions() -> list[dict[str, str]]:
    from worker.ingestion.regions import REGIONS

    return [{"code": k, "name": v} for k, v in REGIONS.items()]
