"""F9 — Historique et intelligence concurrentielle. Les chiffres viennent du SQL, jamais d'un LLM.

Deux sources interchangeables :
- PostgreSQL (`contract_awards`, alimenté par l'ingestion hebdomadaire) : toujours disponible;
- Databricks (couche « or » du lakehouse, historique complet depuis 2009) : voir worker/lakehouse/.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.app.models import ContractAward
from worker.ingestion.regions import REGIONS

SOURCE = "Données ouvertes du SEAO (Secrétariat du Conseil du trésor), licence CC-BY 4.0"


@dataclass
class MarketInsights:
    unspsc: str | None
    region: str | None
    contracts: int
    period_start: str | None
    period_end: str | None
    avg_tenderers: float | None
    amount_p25: float | None
    amount_median: float | None
    amount_p75: float | None
    amount_total: float | None
    top_buyers: list[dict[str, Any]] = field(default_factory=list)
    top_suppliers: list[dict[str, Any]] = field(default_factory=list)
    amount_histogram: list[dict[str, Any]] = field(default_factory=list)
    source: str = SOURCE
    backend: str = "postgres"
    summary: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


BUCKETS = [0, 25_000, 100_000, 500_000, 1_000_000, 5_000_000, float("inf")]


def _filters(unspsc: str | None, region: str | None) -> list[Any]:
    conds: list[Any] = []
    if unspsc:
        # Code partiel accepté : « 7611 » (famille), « 761115 » (classe) ou code complet.
        conds.append(ContractAward.unspsc_main.like(unspsc.rstrip("0")[:8] + "%"))
    if region:
        conds.append(ContractAward.region_code == region)
    return conds


def insights_postgres(
    db: Session, unspsc: str | None, region: str | None, since: datetime | None = None
) -> MarketInsights:
    conds = _filters(unspsc, region)
    if since:
        conds.append(ContractAward.date >= since)
    a = ContractAward
    row = db.execute(
        select(
            func.count(),
            func.min(a.date),
            func.max(a.date),
            func.avg(a.number_of_tenderers),
            func.percentile_cont(0.25).within_group(a.amount),
            func.percentile_cont(0.5).within_group(a.amount),
            func.percentile_cont(0.75).within_group(a.amount),
            func.sum(a.amount),
        ).where(*conds)
    ).one()
    buyers = db.execute(
        select(a.buyer_name, func.count().label("n"), func.sum(a.amount))
        .where(*conds, a.buyer_name.is_not(None))
        .group_by(a.buyer_name)
        .order_by(func.count().desc())
        .limit(5)
    ).all()
    suppliers = db.execute(
        select(a.supplier_name, func.count().label("n"), func.sum(a.amount))
        .where(*conds)
        .group_by(a.supplier_name)
        .order_by(func.count().desc())
        .limit(5)
    ).all()
    hist = []
    for lo, hi in zip(BUCKETS, BUCKETS[1:], strict=False):
        cond = [a.amount >= lo] + ([a.amount < hi] if hi != float("inf") else [])
        n = db.scalar(select(func.count()).where(*conds, *cond)) or 0
        hist.append({"min": lo, "max": None if hi == float("inf") else hi, "count": n})
    return MarketInsights(
        unspsc=unspsc,
        region=region,
        contracts=int(row[0] or 0),
        period_start=row[1].date().isoformat() if row[1] else None,
        period_end=row[2].date().isoformat() if row[2] else None,
        avg_tenderers=round(float(row[3]), 2) if row[3] is not None else None,
        amount_p25=_f(row[4]),
        amount_median=_f(row[5]),
        amount_p75=_f(row[6]),
        amount_total=_f(row[7]),
        top_buyers=[{"name": n, "contracts": c, "amount": _f(s)} for n, c, s in buyers],
        top_suppliers=[{"name": n, "contracts": c, "amount": _f(s)} for n, c, s in suppliers],
        amount_histogram=hist,
    )


def _f(v: Any) -> float | None:
    return round(float(v), 2) if v is not None else None


def describe_scope(unspsc: str | None, region: str | None) -> str:
    return f"code UNSPSC {unspsc or 'tous'}, région {REGIONS.get(region or '', 'toutes')}"
