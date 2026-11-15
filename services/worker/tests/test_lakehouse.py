import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.app.models import Company, CompanyUnspsc, ContractAward, MarketBenchmark, RenewalForecast
from api.app.services.benchmarks import renewals_for_company
from worker.lakehouse.client import Lakehouse, LakehouseConfig, split_sql
from worker.lakehouse.local import compute_local, forecasts_from_events
from worker.lakehouse.pipeline import SQL_DIR, sync_to_postgres, to_ndjson

NOW = datetime(2026, 11, 15, tzinfo=UTC)


def ev(buyer: str, cls: str, days_ago: int) -> dict:
    return {
        "buyer_party_id": buyer,
        "cls": cls,
        "d": NOW - timedelta(days=days_ago),
        "buyer_name": "Ville de Magog",
        "supplier": "Nettoyage ABC",
        "amount": 100000.0,
    }


def test_forecast_regular_three_year_cycle() -> None:
    events = [ev("OP-1", "761115", d) for d in (365 * 3 * 3 - 30, 365 * 3 * 2 - 30, 365 * 3 - 30)]
    out = forecasts_from_events(events, NOW)
    assert len(out) == 1
    f = out[0]
    assert f["median_interval_days"] == 365 * 3 and f["occurrences"] == 3
    assert f["confidence"] == "medium"
    assert NOW < f["predicted_date"] < NOW + timedelta(days=60)


def test_forecast_ignores_irregular_or_single_events() -> None:
    assert forecasts_from_events([ev("OP-1", "761115", 400)], NOW) == []
    # intervalles trop courts (lots publiés ensemble) : ignorés
    assert forecasts_from_events([ev("OP-2", "721033", 400), ev("OP-2", "721033", 380)], NOW) == []


def test_compute_local_and_company_renewals(db: Session) -> None:
    for i, days in enumerate((365 * 2 * 3 - 20, 365 * 2 * 2 - 20, 365 * 2 - 20)):
        db.add(
            ContractAward(
                ocid=f"o{i}",
                award_id=f"a{i}",
                supplier_party_id="FO-1",
                supplier_name="Nettoyage ABC",
                buyer_party_id="OP-9",
                buyer_name="CSS des Sommets",
                amount=90000 + i * 10000,
                date=NOW - timedelta(days=days),
                unspsc_main="76111501",
                region_code="05",
                main_category="services",
                number_of_tenderers=4,
            )
        )
    db.commit()
    res = compute_local(db, NOW)
    assert res["forecasts"] == 1 and res["benchmarks"] >= 2
    b = db.scalar(
        select(MarketBenchmark).where(MarketBenchmark.unspsc_prefix == "761115", MarketBenchmark.region_code == "05")
    )
    assert b is not None and b.contracts == 3 and b.amount_median == 100000
    c = Company(name="X", description="", categories=["services"], regions=["05"])
    db.add(c)
    db.flush()
    db.add(CompanyUnspsc(company_id=c.id, unspsc_code="76111500"))
    db.commit()
    db.refresh(c)
    items = renewals_for_company(db, c)["items"]
    assert len(items) == 1 and items[0]["buyer_name"] == "CSS des Sommets"


def test_sql_files_split_and_render() -> None:
    for name in ("00_setup.sql", "10_bronze_load.sql", "20_silver.sql", "30_gold.sql"):
        stmts = split_sql((SQL_DIR / name).read_text())
        assert stmts and all(s.strip() for s in stmts)
    assert len(split_sql((SQL_DIR / "30_gold.sql").read_text())) == 2


def test_ndjson_one_release_per_line() -> None:
    payload = {"releases": [{"ocid": "a", "id": "1"}, {"ocid": "b", "id": "2"}]}
    lines = to_ndjson(payload).decode().splitlines()
    assert [json.loads(x)["ocid"] for x in lines] == ["a", "b"]


def test_statement_api_polling_and_sync(db: Session) -> None:
    """Simule l'API Statement Execution de Databricks (état PENDING puis SUCCEEDED)."""
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(f"{req.method} {req.url.path}")
        body = json.loads(req.content) if req.content else {}
        if req.method == "POST" and req.url.path == "/api/2.0/sql/statements":
            assert req.headers["authorization"] == "Bearer tok"
            stmt = body["statement"]
            sid = "bench" if "gold_market_benchmarks" in stmt else "fc"
            return httpx.Response(200, json={"statement_id": sid, "status": {"state": "PENDING"}})
        sid = req.url.path.rsplit("/", 1)[-1]
        if sid == "bench":
            cols = [
                "unspsc_prefix",
                "region_code",
                "contracts",
                "avg_tenderers",
                "amount_p25",
                "amount_median",
                "amount_p75",
                "period_start",
                "period_end",
                "top_suppliers",
                "top_buyers",
            ]
            row = [
                "761115",
                "05",
                "12",
                "3.5",
                "50000",
                "90000",
                "150000",
                "2021-03-01T00:00:00Z",
                "2026-10-31T00:00:00Z",
                '[{"name":"ABC","contracts":4,"amount":1}]',
                "[]",
            ]
        else:
            cols = [
                "buyer_party_id",
                "buyer_name",
                "unspsc_prefix",
                "unspsc_label",
                "region_code",
                "main_category",
                "occurrences",
                "median_interval_days",
                "last_award_date",
                "predicted_date",
                "window_days",
                "last_supplier",
                "last_amount",
                "confidence",
            ]
            row = [
                "OP-9",
                "CSS",
                "761115",
                "Nettoyage",
                "05",
                "services",
                "4",
                "1095",
                "2024-01-10T00:00:00Z",
                "2027-01-09T00:00:00Z",
                "45",
                "ABC",
                "100000",
                "high",
            ]
        return httpx.Response(
            200,
            json={
                "statement_id": sid,
                "status": {"state": "SUCCEEDED"},
                "manifest": {"schema": {"columns": [{"name": c} for c in cols]}},
                "result": {"data_array": [row]},
            },
        )

    cfg = LakehouseConfig("dbc-test.cloud.databricks.com", "tok", "wh1", "workspace", "radarao", "seao_raw")
    http = httpx.Client(
        base_url="https://dbc-test.cloud.databricks.com",
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer tok"},
    )
    import worker.lakehouse.client as client_mod

    monkey = client_mod.time.sleep
    client_mod.time.sleep = lambda s: None
    try:
        res = sync_to_postgres(Lakehouse(cfg, http), db)
    finally:
        client_mod.time.sleep = monkey
    assert res == {"benchmarks": 1, "forecasts": 1}
    assert any(c.startswith("GET /api/2.0/sql/statements/") for c in calls)
    f = db.scalar(select(RenewalForecast))
    assert f is not None and f.source == "databricks" and f.confidence == "high"
    assert db.scalar(select(MarketBenchmark)).top_suppliers[0]["name"] == "ABC"  # type: ignore[union-attr]
    _ = Path
