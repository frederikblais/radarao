"""Schémas d'entrée et de sortie de l'API REST (OpenAPI -> clients TypeScript et Swift)."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

Category = Literal["works", "services", "goods"]


class MagicLinkIn(BaseModel):
    email: EmailStr


class VerifyIn(BaseModel):
    token: str


class SessionOut(BaseModel):
    token: str
    user_id: str
    has_company: bool


class MeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    display_name: str | None
    company_id: str | None
    role: str
    alert_threshold: int
    weekly_digest: bool
    instant_alerts: bool
    density: str


class MeUpdate(BaseModel):
    display_name: str | None = None
    alert_threshold: int | None = Field(default=None, ge=0, le=100)
    weekly_digest: bool | None = None
    instant_alerts: bool | None = None
    density: Literal["comfortable", "compact"] | None = None


class RbqQualification(BaseModel):
    held: bool = False
    subcategories: list[str] = []


class Qualifications(BaseModel):
    rbq: RbqQualification = RbqQualification()
    amp: bool = False
    revenu_quebec: bool = False
    iso: list[str] = []
    insurance_amount: float | None = None
    bonding_capacity: float | None = None


class UnspscChoice(BaseModel):
    code: str = Field(pattern=r"^\d{8}$")
    label: str | None = None
    source: Literal["user", "suggested"] = "user"
    accepted: bool = True


class BuyerPreferences(BaseModel):
    favorites: list[str] = []
    excluded: list[str] = []


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    neq: str | None = Field(default=None, pattern=r"^\d{10}$")
    size: int | None = Field(default=None, ge=1, le=100000)
    description: str = Field(default="", max_length=4000)
    categories: list[Category] = []
    unspsc: list[UnspscChoice] = []
    regions: list[str] = []
    postal_code: str | None = None
    radius_km: int | None = Field(default=None, ge=0, le=1000)
    value_min: float | None = Field(default=None, ge=0)
    value_max: float | None = Field(default=None, ge=0)
    qualifications: Qualifications = Qualifications()
    buyer_preferences: BuyerPreferences = BuyerPreferences()
    onboarding_completed: bool = True


class ProfileOut(ProfileIn):
    id: str


class SuggestIn(BaseModel):
    description: str = Field(min_length=10, max_length=4000)


class UnspscOut(BaseModel):
    code: str
    label: str
    reason: str | None = None
    source: str | None = None


class TenderCard(BaseModel):
    ocid: str
    tender_id: str | None
    title: str
    buyer_name: str | None
    buyer_party_id: str | None
    main_category: str | None
    region_code: str | None
    region_name: str | None
    end_date: datetime | None
    seao_url: str | None
    source: str
    score: int | None
    reasons: list[str] = []
    blockers: list[str] = []
    feedback: str | None = None
    tracked: bool = False
    dossier_id: str | None = None


class FeedOut(BaseModel):
    items: list[TenderCard]
    next_cursor: str | None
    freshness: date | None
    total: int


class TenderDetail(TenderCard):
    status: str
    procurement_method: str | None
    procurement_method_details: str | None
    start_date: datetime | None
    value_amount: float | None
    number_of_tenderers: int | None
    summary_fr: str | None
    items_unspsc: list[dict[str, Any]]
    history: list[dict[str, Any]]
    value_in_range: str | None = None


class ManualTenderIn(BaseModel):
    tender_id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=3, max_length=500)
    buyer_name: str | None = None
    end_date: datetime | None = None
    main_category: Category | None = None
    region_code: str | None = None
    seao_url: str | None = Field(default=None, pattern=r"^https://")


class FeedbackIn(BaseModel):
    feedback: Literal["relevant", "not_relevant"] | None


class TrackIn(BaseModel):
    tracked: bool


class DossierIn(BaseModel):
    ocid: str | None = None
    title: str | None = Field(default=None, max_length=500)


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    filename: str
    kind: str
    addendum_number: int | None
    pages: int
    size_bytes: int
    status: str
    scanned_pages: list[int]
    uploaded_at: datetime


class DocumentUpdate(BaseModel):
    kind: Literal["main", "devis", "form", "addendum", "other"] | None = None
    addendum_number: int | None = Field(default=None, ge=1, le=99)


class DossierOut(BaseModel):
    id: str
    title: str
    ocid: str | None
    status: str
    created_at: datetime
    delete_after: datetime | None
    documents: list[DocumentOut] = []
    end_date: datetime | None = None
    last_job: dict[str, Any] | None = None
    fields_to_verify: int = 0


class JobOut(BaseModel):
    id: str
    type: str
    status: str
    step: str | None
    step_label: str | None
    progress: int
    completed_steps: list[str]
    error: str | None
    failure_kind: str | None = None
    problems: list[str] = []
    failed_sections: list[str] = []
    started_at: datetime | None
    finished_at: datetime | None


class FieldOut(BaseModel):
    id: str
    section: str
    key: str
    label: str | None
    value: Any
    citation: str | None
    document_id: str | None
    document_name: str | None
    page: int | None
    confidence: str
    verified_status: str
    note: str | None
    critical: bool
    superseded_by_field_id: str | None
    to_verify: bool


class FicheSection(BaseModel):
    key: str
    label: str
    fields: list[FieldOut]


class AddendumChange(BaseModel):
    document_id: str
    document_name: str
    addendum_number: int | None
    changes: list[dict[str, Any]]


class FicheOut(BaseModel):
    dossier_id: str
    status: str
    sections: list[FicheSection]
    addenda: list[AddendumChange]
    to_verify: int
    missing_sections: list[str] = []


class FieldPatch(BaseModel):
    action: Literal["verify", "correct"]
    value: Any = None
    page: int | None = Field(default=None, ge=1)


class ChecklistItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    label: str
    category: str
    source_field_id: str | None
    source_document_id: str | None = None
    source_page: int | None = None
    blocking: bool
    blocking_reason: str | None
    done: bool
    assignee: str | None
    due_date: date | None
    position: int
    user_created: bool


class ChecklistItemIn(BaseModel):
    label: str = Field(min_length=1, max_length=500)
    assignee: str | None = Field(default=None, max_length=200)
    due_date: date | None = None
    blocking: bool = False


class ChecklistItemPatch(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=500)
    done: bool | None = None
    assignee: str | None = Field(default=None, max_length=200)
    due_date: date | None = None
    blocking: bool | None = None


class GoNoGoOutApi(BaseModel):
    recommendation: str
    effort: str
    summary: str
    strengths: list[dict[str, Any]]
    risks: list[dict[str, Any]]
    blockers: list[dict[str, Any]]
    warning: str | None
    created_at: datetime
    benchmarks: dict[str, Any] | None = None


class ChatIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)


class ChatMessageOut(BaseModel):
    id: str
    role: str
    text: str
    citations: list[dict[str, Any]]
    created_at: datetime


class DeviceIn(BaseModel):
    platform: Literal["ios", "macos"]
    token: str = Field(min_length=10, max_length=512)
