import json
import os
import time
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.app.models import ContractAward, Tender, TenderItem, TenderRelease
from worker.ingestion.ocds import parse_seao_date
from worker.ingestion.regions import region_from_postal_code
from worker.ingestion.seao import file_period_end, freshness, ingest_file, ingest_payload

FIXTURE = Path(__file__).parent / "fixtures" / "hebdo_20261102_20261108_extrait.json"


def _payload() -> dict:
    return json.loads(FIXTURE.read_text())


def test_regions_from_postal_code() -> None:
    assert region_from_postal_code("J1H 4A9") == "05"  # Sherbrooke
    assert region_from_postal_code("H2X3J8") == "06"  # Montréal
    assert region_from_postal_code("H7N 1A1") == "13"  # Laval
    assert region_from_postal_code("G1R4Y9") == "03"  # Québec
    assert region_from_postal_code("J8Y 3R6") == "07"  # Gatineau
    assert region_from_postal_code("J2S 1A1") == "16"  # Saint-Hyacinthe
    assert region_from_postal_code("G9A 5H7") == "04"  # Trois-Rivières
    assert region_from_postal_code("06510") is None  # hors Québec
    assert region_from_postal_code(None) is None


def test_parse_dates() -> None:
    assert parse_seao_date("2026-11-30T11:00:00-05:00").isoformat() == "2026-11-30T11:00:00-05:00"  # type: ignore[union-attr]
    assert parse_seao_date("2026-11-30 11:00").utcoffset() is not None  # type: ignore[union-attr]
    assert parse_seao_date("") is None
    assert file_period_end("hebdo_20261102_20261108.json").day == 8  # type: ignore[union-attr]


def test_ingestion_is_idempotent(db: Session) -> None:
    payload = _payload()
    run1 = ingest_payload(db, payload, FIXTURE.name)
    n_tenders = db.scalar(select(func.count()).select_from(Tender))
    n_releases = db.scalar(select(func.count()).select_from(TenderRelease))
    n_items = db.scalar(select(func.count()).select_from(TenderItem))
    assert run1.inserted > 0 and run1.errors == 0

    run2 = ingest_payload(db, payload, FIXTURE.name)
    assert run2.inserted == 0 and run2.updated == 0
    assert run2.skipped == run1.releases_count
    assert db.scalar(select(func.count()).select_from(Tender)) == n_tenders
    assert db.scalar(select(func.count()).select_from(TenderRelease)) == n_releases
    assert db.scalar(select(func.count()).select_from(TenderItem)) == n_items


def test_update_and_cancellation_keep_history(db: Session) -> None:
    payload = _payload()
    base = next(r for r in payload["releases"] if r["tag"] == ["tender"])
    ingest_payload(db, payload, FIXTURE.name)
    t = db.get(Tender, base["ocid"])
    assert t is not None
    assert t.status == "cancelled"
    assert t.title.endswith("(modifié)")
    tags = db.scalars(select(TenderRelease.tag).where(TenderRelease.ocid == base["ocid"])).all()
    assert len(tags) == 3


def test_older_release_does_not_overwrite_newer(db: Session) -> None:
    payload = _payload()
    base = next(r for r in payload["releases"] if r["tag"] == ["tender"])
    newer = json.loads(json.dumps(base))
    newer["id"] = str(int(base["id"]) + 999)
    newer["tag"] = ["tenderUpdate"]
    newer["tender"]["title"] = "Titre le plus récent"
    ingest_payload(db, {"releases": [newer]}, "hebdo_20261109_20261115.json")
    ingest_payload(db, {"releases": [base]}, "hebdo_20261102_20261108.json")
    t = db.get(Tender, base["ocid"])
    assert t is not None and t.title == "Titre le plus récent"
    assert db.scalar(select(func.count()).select_from(TenderRelease)) == 2


def test_items_and_awards(db: Session) -> None:
    ingest_payload(db, _payload(), FIXTURE.name)
    mains = db.scalars(select(TenderItem).where(TenderItem.is_main.is_(True))).all()
    assert mains and all(len(i.unspsc_code) == 8 for i in mains)
    assert db.scalar(select(func.count()).select_from(ContractAward)) > 0
    t = db.scalars(select(Tender).where(Tender.status == "active")).first()
    assert t is not None and t.seao_url and t.seao_url.startswith("https://seao.gouv.qc.ca/")
    assert freshness(db) is not None


def test_invalid_release_is_counted_not_fatal(db: Session) -> None:
    run = ingest_payload(db, {"releases": [{"ocid": "x"}]}, "hebdo_20261102_20261108.json")
    assert run.errors == 1


@pytest.mark.skipif(not os.environ.get("SEAO_FULL_FILE"), reason="SEAO_FULL_FILE non défini")
def test_full_weekly_file_under_two_minutes(db: Session) -> None:
    path = Path(os.environ["SEAO_FULL_FILE"])
    start = time.monotonic()
    run = ingest_file(db, path)
    assert time.monotonic() - start < 120
    assert run.errors == 0
    run2 = ingest_file(db, path)
    assert run2.inserted == 0 and run2.updated == 0
