"""Tableau de bord interne d'observabilité (section 11.4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from api.app.db import get_db
from api.app.models import FicheField, IngestionRun, LlmCall, User
from api.app.security import require_admin

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/metrics")
def metrics(
    days: int = Query(30, ge=1, le=365), _: User = Depends(require_admin), db: Session = Depends(get_db)
) -> dict[str, object]:
    since = datetime.now(UTC) - timedelta(days=days)
    c = LlmCall
    per_dossier = db.execute(
        select(c.dossier_id, func.sum(c.cost_usd), func.count())
        .where(c.created_at >= since, c.dossier_id.is_not(None))
        .group_by(c.dossier_id)
    ).all()
    costs = [float(x[1]) for x in per_dossier]
    by_step = db.execute(
        select(
            c.step,
            c.model,
            func.count(),
            func.avg(c.latency_ms),
            func.sum(c.cost_usd),
            func.sum(c.input_tokens),
            func.sum(c.cache_read_tokens),
            func.sum(case((c.error.is_not(None), 1), else_=0)),
        )
        .where(c.created_at >= since)
        .group_by(c.step, c.model)
        .order_by(c.step)
    ).all()
    f = FicheField
    by_key = db.execute(
        select(
            f.key,
            func.count(),
            func.sum(case((f.verified_status == "quote_not_found", 1), else_=0)),
            func.sum(case((f.verified_status == "user_corrected", 1), else_=0)),
        )
        .where(f.created_at >= since, f.value.is_not(None))
        .group_by(f.key)
    ).all()
    total = sum(r[1] for r in by_key) or 1
    runs = db.scalars(select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(10)).all()
    return {
        "period_days": days,
        "cost_per_dossier": {
            "dossiers": len(costs),
            "avg_usd": round(sum(costs) / len(costs), 4) if costs else None,
            "max_usd": round(max(costs), 4) if costs else None,
        },
        "steps": [
            {
                "step": s,
                "model": m,
                "calls": n,
                "avg_latency_ms": int(lat or 0),
                "cost_usd": round(float(cost or 0), 4),
                "cache_hit_ratio": round(float(cr or 0) / float((inp or 0) + (cr or 0)), 3) if (inp or cr) else None,
                "errors": int(err or 0),
            }
            for s, m, n, lat, cost, inp, cr, err in by_step
        ],
        "quote_not_found_rate": round(sum(r[2] or 0 for r in by_key) / total, 4),
        "fields": [
            {
                "key": k,
                "count": n,
                "quote_not_found": int(q or 0),
                "user_corrected": int(u or 0),
                "correction_rate": round((u or 0) / n, 3),
            }
            for k, n, q, u in by_key
        ],
        "ingestion_runs": [
            {
                "file": r.file_name,
                "inserted": r.inserted,
                "updated": r.updated,
                "errors": r.errors,
                "duration_s": r.duration_s,
                "finished_at": r.finished_at,
            }
            for r in runs
        ],
    }
