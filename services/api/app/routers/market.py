from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.app.db import get_db
from api.app.models import Company
from api.app.security import current_company

router = APIRouter(tags=["market"])


@router.get("/market/insights")
def market_insights(
    unspsc: str | None = Query(None, pattern=r"^\d{2,8}$"),
    region: str | None = Query(None, pattern=r"^\d{2}$"),
    summarize: bool = False,
    company: Company = Depends(current_company),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    from api.app.services.benchmarks import market_insights as compute

    return compute(db, unspsc, region, company_id=company.id, summarize=summarize)


@router.get("/market/renewals")
def renewals(
    limit: int = Query(20, ge=1, le=100), company: Company = Depends(current_company), db: Session = Depends(get_db)
) -> dict[str, object]:
    """Renouvellements de contrats probables (prévisions du lakehouse), filtrés selon le profil."""
    from api.app.services.benchmarks import renewals_for_company

    return renewals_for_company(db, company, limit)
