from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import ARRAY, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.app.db import Base
from api.app.models.base import EMBED_DIM, new_id, utcnow


class Party(Base):
    __tablename__ = "parties"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # identifiant SEAO (OP-…, FO-…)
    name: Mapped[str] = mapped_column(String(500))
    neq: Mapped[str | None] = mapped_column(String(20))
    locality: Mapped[str | None] = mapped_column(String(200))
    region: Mapped[str | None] = mapped_column(String(60))  # province (QC) telle que publiée
    region_code: Mapped[str | None] = mapped_column(String(2))  # région administrative déduite
    postal_code: Mapped[str | None] = mapped_column(String(40))
    roles: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)


class Tender(Base):
    __tablename__ = "tenders"

    ocid: Mapped[str] = mapped_column(String(80), primary_key=True)
    tender_id: Mapped[str | None] = mapped_column(String(120), index=True)
    title: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), index=True)
    buyer_party_id: Mapped[str | None] = mapped_column(ForeignKey("parties.id"))
    buyer_name: Mapped[str | None] = mapped_column(String(500))
    procurement_method: Mapped[str | None] = mapped_column(String(20))
    procurement_method_details: Mapped[str | None] = mapped_column(String(300))
    main_category: Mapped[str | None] = mapped_column(String(20), index=True)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    value_amount: Mapped[float | None] = mapped_column(Float)
    number_of_tenderers: Mapped[int | None] = mapped_column(Integer)
    seao_url: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    summary_fr: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    region_code: Mapped[str | None] = mapped_column(String(2), index=True)
    last_release_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_release_id: Mapped[str | None] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(16), default="open_data")  # open_data | manual
    created_by_company_id: Mapped[str | None] = mapped_column(String(32))  # avis manuels
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TenderItem(Base):
    __tablename__ = "tender_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ocid: Mapped[str] = mapped_column(ForeignKey("tenders.ocid", ondelete="CASCADE"), index=True)
    unspsc_code: Mapped[str] = mapped_column(String(8), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_main: Mapped[bool] = mapped_column(Boolean, default=False)


class TenderRelease(Base):
    """Historique complet : une ligne par publication (release) du SEAO."""

    __tablename__ = "tender_releases"
    __table_args__ = (UniqueConstraint("ocid", "release_id", name="uq_tender_release"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ocid: Mapped[str] = mapped_column(String(80), index=True)
    release_id: Mapped[str] = mapped_column(String(40))
    tag: Mapped[list[str]] = mapped_column(ARRAY(String))
    date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB)
    ingestion_run_id: Mapped[str | None] = mapped_column(String(32))


class TenderEmbedding(Base):
    __tablename__ = "tender_embeddings"

    ocid: Mapped[str] = mapped_column(ForeignKey("tenders.ocid", ondelete="CASCADE"), primary_key=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM))


class ContractAward(Base):
    """Adjudications et contrats conclus, aplatis pour les statistiques SQL (F9). Voir ADR-004."""

    __tablename__ = "contract_awards"
    __table_args__ = (UniqueConstraint("ocid", "award_id", "supplier_party_id", name="uq_award"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ocid: Mapped[str] = mapped_column(String(80), index=True)
    award_id: Mapped[str] = mapped_column(String(80))
    supplier_party_id: Mapped[str] = mapped_column(String(64))
    supplier_name: Mapped[str] = mapped_column(String(500))
    buyer_party_id: Mapped[str | None] = mapped_column(String(64))
    buyer_name: Mapped[str | None] = mapped_column(String(500))
    amount: Mapped[float | None] = mapped_column(Float)
    date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unspsc_main: Mapped[str | None] = mapped_column(String(8), index=True)
    region_code: Mapped[str | None] = mapped_column(String(2), index=True)
    main_category: Mapped[str | None] = mapped_column(String(20))
    procurement_method: Mapped[str | None] = mapped_column(String(20))
    number_of_tenderers: Mapped[int | None] = mapped_column(Integer)


class Match(Base):
    __tablename__ = "matches"

    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True)
    ocid: Mapped[str] = mapped_column(ForeignKey("tenders.ocid", ondelete="CASCADE"), primary_key=True)
    score: Mapped[int] = mapped_column(Integer)
    similarity: Mapped[float | None] = mapped_column(Float)
    judge_score: Mapped[int | None] = mapped_column(Integer)
    reasons: Mapped[list[str]] = mapped_column(JSONB, default=list)
    blockers: Mapped[list[str]] = mapped_column(JSONB, default=list)
    value_in_range: Mapped[str | None] = mapped_column(String(10))
    model: Mapped[str | None] = mapped_column(String(60))
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user_feedback: Mapped[str | None] = mapped_column(String(20))  # relevant | not_relevant
    tracked: Mapped[bool] = mapped_column(Boolean, default=False)
    alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    file_name: Mapped[str] = mapped_column(String(200))
    file_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # fin de période couverte
    published_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    releases_count: Mapped[int] = mapped_column(Integer, default=0)
    inserted: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    duration_s: Mapped[float | None] = mapped_column(Float)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)


class MarketBenchmark(Base):
    """Repères de marché calculés dans le lakehouse (couche or), copiés ici pour la lecture rapide."""

    __tablename__ = "market_benchmarks"
    __table_args__ = (UniqueConstraint("unspsc_prefix", "region_code", name="uq_benchmark"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    unspsc_prefix: Mapped[str] = mapped_column(String(8))  # classe (6 chiffres) ou « * »
    region_code: Mapped[str] = mapped_column(String(2))  # « ** » = toutes les régions
    contracts: Mapped[int] = mapped_column(Integer)
    avg_tenderers: Mapped[float | None] = mapped_column(Float)
    amount_p25: Mapped[float | None] = mapped_column(Float)
    amount_median: Mapped[float | None] = mapped_column(Float)
    amount_p75: Mapped[float | None] = mapped_column(Float)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    top_suppliers: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    top_buyers: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    source: Mapped[str] = mapped_column(String(20), default="databricks")
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RenewalForecast(Base):
    """Prévision de renouvellement : un organisme qui rachète périodiquement le même type de
    contrat va probablement republier un avis. Permet d'alerter AVANT la publication."""

    __tablename__ = "renewal_forecasts"
    __table_args__ = (UniqueConstraint("buyer_party_id", "unspsc_prefix", name="uq_renewal"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    buyer_party_id: Mapped[str] = mapped_column(String(64))
    buyer_name: Mapped[str | None] = mapped_column(String(500))
    unspsc_prefix: Mapped[str] = mapped_column(String(8), index=True)
    unspsc_label: Mapped[str | None] = mapped_column(String(300))
    region_code: Mapped[str | None] = mapped_column(String(2), index=True)
    main_category: Mapped[str | None] = mapped_column(String(20))
    occurrences: Mapped[int] = mapped_column(Integer)
    median_interval_days: Mapped[int] = mapped_column(Integer)
    last_award_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    predicted_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    window_days: Mapped[int] = mapped_column(Integer)
    last_supplier: Mapped[str | None] = mapped_column(String(500))
    last_amount: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[str] = mapped_column(String(10))  # high | medium | low
    source: Mapped[str] = mapped_column(String(20), default="databricks")
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
