"""Lecture des repères de marché et des prévisions de renouvellement (cache PostgreSQL de la
couche or du lakehouse Databricks; repli sur un calcul SQL en direct)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from api.app.models import Company, MarketBenchmark, RenewalForecast, Tender, TenderItem

SOURCE_LABEL = {
    "databricks": "Lakehouse Databricks (historique complet du SEAO)",
    "postgres": "Base opérationnelle RadarAO (fichiers récents du SEAO)",
}


def _benchmark(db: Session, prefix: str, region: str) -> MarketBenchmark | None:
    rows = db.scalars(
        select(MarketBenchmark).where(MarketBenchmark.unspsc_prefix == prefix, MarketBenchmark.region_code == region)
    ).all()
    by_src = {r.source: r for r in rows}
    return by_src.get("databricks") or by_src.get("postgres")


def _bench_dict(b: MarketBenchmark) -> dict[str, Any]:
    return {
        "unspsc_prefix": b.unspsc_prefix,
        "region_code": b.region_code,
        "contracts": b.contracts,
        "avg_tenderers": round(b.avg_tenderers, 2) if b.avg_tenderers is not None else None,
        "amount_p25": b.amount_p25,
        "amount_median": b.amount_median,
        "amount_p75": b.amount_p75,
        "period_start": b.period_start.date().isoformat() if b.period_start else None,
        "period_end": b.period_end.date().isoformat() if b.period_end else None,
        "top_suppliers": b.top_suppliers,
        "top_buyers": b.top_buyers,
        "backend": b.source,
        "source": "Données ouvertes du SEAO (CC-BY 4.0) · " + SOURCE_LABEL.get(b.source, b.source),
    }


def price_benchmarks(db: Session, ocid: str | None) -> dict[str, Any] | None:
    """Pour le go / no-go : distribution des montants adjugés pour des contrats semblables."""
    if not ocid:
        return None
    t = db.get(Tender, ocid)
    code = db.scalar(select(TenderItem.unspsc_code).where(TenderItem.ocid == ocid, TenderItem.is_main.is_(True)))
    if t is None or not code:
        return None
    for region in ([t.region_code] if t.region_code else []) + ["**"]:
        b = _benchmark(db, code[:6], region)
        if b is not None:
            return _bench_dict(b)
    return None


def market_insights(
    db: Session, unspsc: str | None, region: str | None, company_id: str | None = None, summarize: bool = False
) -> dict[str, Any]:
    from worker.market import describe_scope, insights_postgres

    out: dict[str, Any]
    b = _benchmark(db, unspsc[:6], region or "**") if unspsc and len(unspsc) >= 6 else None
    if b is not None and b.source == "databricks":
        out = _bench_dict(b)
        out.update({"unspsc": unspsc, "region": region, "period_start": out["period_start"], "amount_histogram": []})
    else:
        out = insights_postgres(db, unspsc, region).as_dict()
        out["source"] = out["source"] + " · " + SOURCE_LABEL["postgres"]
    out["scope"] = describe_scope(unspsc, region)
    if summarize:
        out["summary"] = _summary(out, company_id)
    return out


def _summary(stats: dict[str, Any], company_id: str | None) -> str | None:
    """F9 : le LLM rédige seulement un résumé de chiffres DÉJÀ calculés en SQL."""
    import json

    from api.app.schemas.ai import MarketSummary
    from worker.llm.client import LlmClient, LlmContext, LlmError
    from worker.llm.prompts import load_prompt

    numbers = {
        k: stats.get(k)
        for k in (
            "scope",
            "contracts",
            "avg_tenderers",
            "amount_p25",
            "amount_median",
            "amount_p75",
            "period_start",
            "period_end",
            "top_buyers",
            "top_suppliers",
        )
    }
    try:
        res = LlmClient(LlmContext(company_id=company_id)).structured(
            "F9_summary",
            "market_summary",
            load_prompt("market_summary"),
            [{"role": "user", "content": json.dumps(numbers, ensure_ascii=False, default=str)}],
            MarketSummary,
        )
        return res.resume
    except LlmError:
        return None


def renewals_for_company(db: Session, company: Company, limit: int = 20) -> dict[str, Any]:
    prefixes = sorted({u.unspsc_code[:6] for u in company.unspsc if u.accepted})
    if not prefixes:
        return {"items": [], "note": "Ajoutez des codes UNSPSC à votre profil pour voir les renouvellements prévus."}
    now = datetime.now(UTC)
    q = select(RenewalForecast).where(
        RenewalForecast.unspsc_prefix.in_(prefixes), RenewalForecast.predicted_date >= now - timedelta(days=60)
    )
    if company.regions:
        q = q.where(or_(RenewalForecast.region_code.in_(company.regions), RenewalForecast.region_code.is_(None)))
    excluded = (company.buyer_preferences or {}).get("excluded") or []
    if excluded:
        q = q.where(RenewalForecast.buyer_party_id.not_in(excluded))
    rows = db.scalars(q.order_by(RenewalForecast.predicted_date).limit(limit * 2)).all()
    seen: dict[tuple[str, str], RenewalForecast] = {}
    for r in rows:  # databricks prioritaire sur le repli postgres
        k = (r.buyer_party_id, r.unspsc_prefix)
        if k not in seen or r.source == "databricks":
            seen[k] = r
    items = sorted(seen.values(), key=lambda r: r.predicted_date)[:limit]
    from worker.ingestion.regions import REGIONS

    return {
        "items": [
            {
                "buyer_party_id": r.buyer_party_id,
                "buyer_name": r.buyer_name,
                "unspsc_prefix": r.unspsc_prefix,
                "unspsc_label": r.unspsc_label,
                "region_code": r.region_code,
                "region_name": REGIONS.get(r.region_code or ""),
                "occurrences": r.occurrences,
                "median_interval_days": r.median_interval_days,
                "last_award_date": r.last_award_date.date().isoformat(),
                "predicted_date": r.predicted_date.date().isoformat(),
                "window_days": r.window_days,
                "last_supplier": r.last_supplier,
                "last_amount": r.last_amount,
                "confidence": r.confidence,
                "backend": r.source,
            }
            for r in items
        ],
        "note": "Prévision statistique fondée sur les contrats passés de l'organisme : ce n'est pas une annonce.",
    }
