"""Calcul équivalent à la couche or, sur PostgreSQL (`contract_awards`). Utilisé quand Databricks
n'est pas configuré, et comme référence pour tester la logique (mêmes règles que 30_gold.sql)."""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.app.models import ContractAward, TenderItem
from worker.lakehouse.pipeline import store_benchmarks, store_forecasts

MIN_GAP_DAYS, MIN_MED, MAX_MED = 90, 180, 2200
PAST_DAYS, FUTURE_DAYS = 60, 540


def confidence(n: int, med: float, sd: float | None) -> str:
    cv = (sd / med) if sd is not None and med else 1.0
    if n >= 4 and cv < 0.25:
        return "high"
    if n >= 3 and cv < 0.40:
        return "medium"
    return "low"


def forecasts_from_events(events: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """events : une ligne par (organisme, classe UNSPSC, ocid) avec la date d'adjudication `d`."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for e in events:
        groups[(e["buyer_party_id"], e["cls"])].append(e)
    out = []
    for (buyer, cls), evs in groups.items():
        evs.sort(key=lambda e: e["d"])
        gaps = [(b["d"] - a["d"]).days for a, b in zip(evs, evs[1:], strict=False)]
        gaps = [g for g in gaps if g > MIN_GAP_DAYS]
        if not gaps:
            continue
        med = statistics.median(gaps)
        sd = statistics.stdev(gaps) if len(gaps) > 1 else None
        if not (MIN_MED <= med <= MAX_MED):
            continue
        last = evs[-1]
        predicted = last["d"] + timedelta(days=int(med))
        if not (now - timedelta(days=PAST_DAYS) <= predicted <= now + timedelta(days=FUTURE_DAYS)):
            continue
        n = len(gaps) + 1
        out.append(
            {
                "buyer_party_id": buyer,
                "buyer_name": last.get("buyer_name"),
                "unspsc_prefix": cls,
                "unspsc_label": last.get("unspsc_label"),
                "region_code": last.get("region_code"),
                "main_category": last.get("main_category"),
                "occurrences": n,
                "median_interval_days": int(med),
                "last_award_date": last["d"],
                "predicted_date": predicted,
                "window_days": int(max(30, min(120, sd if sd is not None else med * 0.15))),
                "last_supplier": last.get("supplier"),
                "last_amount": last.get("amount"),
                "confidence": confidence(n, med, sd),
            }
        )
    return out


def compute_local(db: Session, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(UTC)
    a = ContractAward
    rows = db.execute(
        select(
            a.buyer_party_id,
            a.buyer_name,
            a.unspsc_main,
            a.ocid,
            a.date,
            a.region_code,
            a.main_category,
            a.supplier_name,
            a.amount,
            a.number_of_tenderers,
        ).where(a.date.is_not(None), a.buyer_party_id.is_not(None), a.unspsc_main.is_not(None))
    ).all()
    labels = dict(db.execute(select(TenderItem.unspsc_code, TenderItem.description)).all())
    by_ocid: dict[tuple[str, str, str], dict[str, Any]] = {}
    scoped: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for r in rows:
        cls = r.unspsc_main[:6]
        k = (r.buyer_party_id, cls, r.ocid)
        e = by_ocid.get(k)
        if e is None:
            by_ocid[k] = {
                "buyer_party_id": r.buyer_party_id,
                "cls": cls,
                "d": r.date,
                "buyer_name": r.buyer_name,
                "unspsc_label": labels.get(r.unspsc_main),
                "region_code": r.region_code,
                "main_category": r.main_category,
                "supplier": r.supplier_name,
                "amount": r.amount or 0.0,
            }
        else:
            if r.date >= e["d"]:
                e["supplier"] = r.supplier_name
            e["d"] = min(e["d"], r.date)
            e["amount"] = (e["amount"] or 0) + (r.amount or 0)
        for rg in (r.region_code or "00", "**"):
            scoped[(cls, rg)].append(r)
    forecasts = forecasts_from_events(list(by_ocid.values()), now)
    store_forecasts(db, forecasts, "postgres")

    bench = []
    for (cls, rg), rs in scoped.items():
        ocids = {r.ocid for r in rs}
        if len(ocids) < 3:
            continue
        amounts = sorted(r.amount for r in rs if r.amount is not None)
        q = statistics.quantiles(amounts, n=4) if len(amounts) >= 2 else [None, amounts[0] if amounts else None, None]
        tend = [r.number_of_tenderers for r in rs if r.number_of_tenderers is not None]
        sup: dict[str, list[float]] = defaultdict(list)
        buy: dict[str, set[str]] = defaultdict(set)
        for r in rs:
            sup[r.supplier_name].append(r.amount or 0)
            if r.buyer_name:
                buy[r.buyer_name].add(r.ocid)
        bench.append(
            {
                "unspsc_prefix": cls,
                "region_code": rg,
                "contracts": len(ocids),
                "avg_tenderers": statistics.mean(tend) if tend else None,
                "amount_p25": q[0],
                "amount_median": statistics.median(amounts) if amounts else None,
                "amount_p75": q[2],
                "period_start": min(r.date for r in rs),
                "period_end": max(r.date for r in rs),
                "top_suppliers": [
                    {"name": n, "contracts": len(v), "amount": round(sum(v), 2)}
                    for n, v in sorted(sup.items(), key=lambda x: -len(x[1]))[:5]
                ],
                "top_buyers": [
                    {"name": n, "contracts": len(v)} for n, v in sorted(buy.items(), key=lambda x: -len(x[1]))[:5]
                ],
            }
        )
    store_benchmarks(db, bench, "postgres")
    return {"forecasts": len(forecasts), "benchmarks": len(bench)}
