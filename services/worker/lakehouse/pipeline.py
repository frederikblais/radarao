"""Orchestration du lakehouse : NDJSON -> Volume -> bronze -> argent -> or -> cache PostgreSQL."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dateutil import parser as dateparser
from sqlalchemy import delete
from sqlalchemy.orm import Session

from api.app.models import MarketBenchmark, RenewalForecast
from worker.ingestion.regions import _FSA2, _FSA3
from worker.lakehouse.client import Lakehouse, LakehouseConfig, render_sql

log = logging.getLogger("radarao.lakehouse")
SQL_DIR = Path(__file__).resolve().parents[3] / "databricks" / "sql"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


def lakehouse() -> Lakehouse | None:
    cfg = LakehouseConfig.from_settings()
    return Lakehouse(cfg) if cfg else None


def _sql(lh: Lakehouse, name: str, **extra: str) -> str:
    text = render_sql((SQL_DIR / name).read_text(encoding="utf-8"), lh.cfg)
    for k, v in extra.items():
        text = text.replace("${" + k + "}", v)
    return text


def setup(lh: Lakehouse) -> None:
    lh.script(_sql(lh, "00_setup.sql"))
    rows = [*_FSA3.items(), *_FSA2.items()]
    values = ", ".join(f"('{p}', '{r}')" for p, r in rows)
    lh.sql(f"DELETE FROM {lh.cfg.fq('ref_fsa_region')}")
    lh.sql(f"INSERT INTO {lh.cfg.fq('ref_fsa_region')} VALUES {values}")


def to_ndjson(payload: dict[str, Any]) -> bytes:
    return "\n".join(
        json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in payload.get("releases", [])
    ).encode("utf-8")


def load_file(lh: Lakehouse, file_name: str, payload: dict[str, Any]) -> str:
    if not _SAFE_NAME.match(file_name):
        raise ValueError("nom de fichier invalide")
    nd_name = file_name.removesuffix(".json") + ".ndjson"
    path = lh.upload(nd_name, to_ndjson(payload))
    lh.script(_sql(lh, "10_bronze_load.sql", file_path=path, source_file=file_name))
    return path


def refresh(lh: Lakehouse) -> None:
    lh.script(_sql(lh, "20_silver.sql"))
    lh.script(_sql(lh, "30_gold.sql"))


def _ts(v: Any) -> datetime | None:
    if v in (None, ""):
        return None
    dt = dateparser.isoparse(str(v).replace(" ", "T"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _num(v: Any) -> float | None:
    return float(v) if v not in (None, "") else None


def sync_to_postgres(lh: Lakehouse, db: Session) -> dict[str, int]:
    """Copie la couche or dans PostgreSQL : l'application lit vite, même si l'entrepôt est en veille."""
    bench = lh.sql(f"SELECT * FROM {lh.cfg.fq('gold_market_benchmarks')}")
    fc = lh.sql(f"SELECT * FROM {lh.cfg.fq('gold_renewal_forecasts')}")
    store_benchmarks(
        db,
        (
            dict(
                r,
                top_suppliers=json.loads(r.get("top_suppliers") or "[]"),
                top_buyers=json.loads(r.get("top_buyers") or "[]"),
            )
            for r in bench
        ),
        "databricks",
    )
    store_forecasts(db, fc, "databricks")
    return {"benchmarks": len(bench), "forecasts": len(fc)}


def store_benchmarks(db: Session, rows: Iterable[dict[str, Any]], source: str) -> None:
    db.execute(delete(MarketBenchmark).where(MarketBenchmark.source == source))
    for r in rows:
        db.add(
            MarketBenchmark(
                unspsc_prefix=r["unspsc_prefix"],
                region_code=r["region_code"],
                contracts=int(r["contracts"]),
                avg_tenderers=_num(r.get("avg_tenderers")),
                amount_p25=_num(r.get("amount_p25")),
                amount_median=_num(r.get("amount_median")),
                amount_p75=_num(r.get("amount_p75")),
                period_start=_ts(r.get("period_start")),
                period_end=_ts(r.get("period_end")),
                top_suppliers=r.get("top_suppliers") or [],
                top_buyers=r.get("top_buyers") or [],
                source=source,
            )
        )
    db.commit()


def store_forecasts(db: Session, rows: Iterable[dict[str, Any]], source: str) -> None:
    db.execute(delete(RenewalForecast).where(RenewalForecast.source == source))
    for r in rows:
        db.add(
            RenewalForecast(
                buyer_party_id=r["buyer_party_id"],
                buyer_name=r.get("buyer_name"),
                unspsc_prefix=r["unspsc_prefix"],
                unspsc_label=r.get("unspsc_label"),
                region_code=r.get("region_code"),
                main_category=r.get("main_category"),
                occurrences=int(r["occurrences"]),
                median_interval_days=int(r["median_interval_days"]),
                last_award_date=_ts(r["last_award_date"]),
                predicted_date=_ts(r["predicted_date"]),
                window_days=int(r["window_days"]),
                last_supplier=r.get("last_supplier"),
                last_amount=_num(r.get("last_amount")),
                confidence=r["confidence"],
                source=source,
            )
        )
    db.commit()
