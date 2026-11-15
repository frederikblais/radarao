from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.app.db import Base
from api.app.models.base import EMBED_DIM, new_id, utcnow


class Dossier(Base):
    __tablename__ = "dossiers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    ocid: Mapped[str | None] = mapped_column(ForeignKey("tenders.ocid", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|analyzing|ready|partial|failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    delete_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    dossier_id: Mapped[str] = mapped_column(ForeignKey("dossiers.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(16), default="other")  # main|devis|form|addendum|other
    addendum_number: Mapped[int | None] = mapped_column(Integer)
    s3_key: Mapped[str] = mapped_column(String(500))
    pages: Mapped[int] = mapped_column(Integer, default=0)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    claude_file_id: Mapped[str | None] = mapped_column(String(120))  # jamais exposé au client
    scanned_pages: Mapped[list[int]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(20), default="uploaded")  # uploaded|ready|unreadable|encrypted
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DocumentPage(Base):
    __tablename__ = "document_pages"

    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    page_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text, default="")
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM))


class FicheField(Base):
    __tablename__ = "fiche_fields"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    dossier_id: Mapped[str] = mapped_column(ForeignKey("dossiers.id", ondelete="CASCADE"), index=True)
    section: Mapped[str] = mapped_column(String(30))
    key: Mapped[str] = mapped_column(String(80))
    label: Mapped[str | None] = mapped_column(String(200))
    value: Mapped[Any] = mapped_column(JSONB)
    citation: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    page: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[str] = mapped_column(String(10), default="medium")  # high|medium|low
    verified_status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending|auto_ok|quote_not_found|user_verified|user_corrected|not_found
    note: Mapped[str | None] = mapped_column(Text)
    critical: Mapped[bool] = mapped_column(Boolean, default=False)
    superseded_by_field_id: Mapped[str | None] = mapped_column(String(32))
    created_by_step: Mapped[str] = mapped_column(String(30))
    match_ratio: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChecklistItem(Base):
    __tablename__ = "checklist_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    dossier_id: Mapped[str] = mapped_column(ForeignKey("dossiers.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(30), default="document")
    source_field_id: Mapped[str | None] = mapped_column(String(32))
    blocking: Mapped[bool] = mapped_column(Boolean, default=False)
    blocking_reason: Mapped[str | None] = mapped_column(Text)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    assignee: Mapped[str | None] = mapped_column(String(200))
    due_date: Mapped[Any] = mapped_column(Date, nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    user_created: Mapped[bool] = mapped_column(Boolean, default=False)


class GoNoGo(Base):
    __tablename__ = "go_no_go"

    dossier_id: Mapped[str] = mapped_column(ForeignKey("dossiers.id", ondelete="CASCADE"), primary_key=True)
    recommendation: Mapped[str] = mapped_column(String(20))  # go | go_with_caution | no_go
    effort: Mapped[str] = mapped_column(String(10))
    summary: Mapped[str] = mapped_column(Text, default="")
    strengths: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    risks: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    blockers: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    warning: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    dossier_id: Mapped[str] = mapped_column(ForeignKey("dossiers.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(12))
    content: Mapped[Any] = mapped_column(JSONB)
    citations: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    type: Mapped[str] = mapped_column(String(30))
    company_id: Mapped[str | None] = mapped_column(String(32), index=True)
    dossier_id: Mapped[str | None] = mapped_column(ForeignKey("dossiers.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|succeeded|partial|failed
    step: Mapped[str | None] = mapped_column(String(30))
    progress: Mapped[int] = mapped_column(Integer, default=0)
    completed_steps: Mapped[list[str]] = mapped_column(JSONB, default=list)
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LlmCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    job_id: Mapped[str | None] = mapped_column(String(32), index=True)
    company_id: Mapped[str | None] = mapped_column(String(32), index=True)
    dossier_id: Mapped[str | None] = mapped_column(String(32), index=True)
    step: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(60))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_creation_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    stop_reason: Mapped[str | None] = mapped_column(String(30))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
