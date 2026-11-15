from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from api.app.config import get_settings
from api.app.db import get_db, get_sessionmaker
from api.app.models import (
    ChatMessage,
    ChecklistItem,
    Company,
    Document,
    Dossier,
    FicheField,
    GoNoGo,
    Job,
    Tender,
)
from api.app.schemas.api import (
    ChatIn,
    ChatMessageOut,
    ChecklistItemIn,
    ChecklistItemOut,
    ChecklistItemPatch,
    DocumentOut,
    DocumentUpdate,
    DossierIn,
    DossierOut,
    FicheOut,
    FieldOut,
    FieldPatch,
    GoNoGoOutApi,
    JobOut,
)
from api.app.security import current_company, own_dossier, rate_limit
from api.app.services.documents import UploadError, add_document
from api.app.services.tasks import enqueue

router = APIRouter(tags=["dossiers"])
RUNNING = ("queued", "running")


def _job_out(job: Job) -> JobOut:
    from worker.analysis.pipeline import STEP_LABEL

    state = job.state or {}
    return JobOut(
        id=job.id,
        type=job.type,
        status=job.status,
        step=job.step,
        step_label=STEP_LABEL.get(job.step or ""),
        progress=job.progress,
        completed_steps=job.completed_steps or [],
        error=job.error,
        failure_kind=state.get("failure_kind"),
        problems=state.get("problems", []),
        failed_sections=list((state.get("worker_errors") or {}).keys()),
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def _last_job(db: Session, dossier_id: str) -> Job | None:
    return db.scalar(
        select(Job).where(Job.dossier_id == dossier_id, Job.type == "analysis").order_by(Job.created_at.desc()).limit(1)
    )


def _to_verify(f: FicheField) -> bool:
    if f.superseded_by_field_id or f.verified_status in ("user_verified", "user_corrected"):
        return False
    if f.value is None:
        return f.critical
    return f.confidence == "low" or f.verified_status != "auto_ok"


def _dossier_out(db: Session, d: Dossier) -> DossierOut:
    docs = list(db.scalars(select(Document).where(Document.dossier_id == d.id).order_by(Document.uploaded_at)))
    job = _last_job(db, d.id)
    end = db.scalar(select(Tender.end_date).where(Tender.ocid == d.ocid)) if d.ocid else None
    fields = db.scalars(select(FicheField).where(FicheField.dossier_id == d.id)).all()
    return DossierOut(
        id=d.id,
        title=d.title,
        ocid=d.ocid,
        status=d.status,
        created_at=d.created_at,
        delete_after=d.delete_after,
        documents=[DocumentOut.model_validate(x) for x in docs],
        end_date=end,
        last_job=_job_out(job).model_dump(mode="json") if job else None,
        fields_to_verify=sum(1 for f in fields if _to_verify(f)),
    )


@router.post("/dossiers", response_model=DossierOut, status_code=status.HTTP_201_CREATED)
def create_dossier(
    body: DossierIn, company: Company = Depends(current_company), db: Session = Depends(get_db)
) -> DossierOut:
    title = body.title
    if body.ocid:
        t = db.get(Tender, body.ocid)
        if t is None or (t.source == "manual" and t.created_by_company_id != company.id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Avis introuvable.")
        existing = db.scalar(select(Dossier).where(Dossier.company_id == company.id, Dossier.ocid == body.ocid))
        if existing:
            return _dossier_out(db, existing)
        title = title or t.title
    d = Dossier(
        company_id=company.id,
        ocid=body.ocid,
        title=title or "Dossier sans titre",
        delete_after=datetime.now(UTC) + timedelta(days=get_settings().retention_days),
    )
    db.add(d)
    db.commit()
    return _dossier_out(db, d)


@router.get("/dossiers", response_model=list[DossierOut])
def list_dossiers(company: Company = Depends(current_company), db: Session = Depends(get_db)) -> list[DossierOut]:
    ds = db.scalars(select(Dossier).where(Dossier.company_id == company.id).order_by(Dossier.created_at.desc()))
    return [_dossier_out(db, d) for d in ds]


@router.get("/dossiers/{dossier_id}", response_model=DossierOut)
def get_dossier(d: Dossier = Depends(own_dossier), db: Session = Depends(get_db)) -> DossierOut:
    return _dossier_out(db, d)


@router.delete("/dossiers/{dossier_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_dossier(d: Dossier = Depends(own_dossier), db: Session = Depends(get_db)) -> None:
    from api.app.services.dossiers import delete_dossier

    delete_dossier(db, d)


# ---------- documents ----------
@router.post("/dossiers/{dossier_id}/documents", response_model=list[DocumentOut], status_code=status.HTTP_201_CREATED)
async def upload(
    files: list[UploadFile] = File(...),
    consent: bool = Form(False),
    kind: str | None = Form(None),
    d: Dossier = Depends(own_dossier),
    db: Session = Depends(get_db),
) -> list[DocumentOut]:
    if not consent and d.consent_at is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Consentement requis : confirmez que vous avez obtenu ces documents légitimement et "
            "acceptez leur conservation temporaire pour l'analyse.",
        )
    d.consent_at = d.consent_at or datetime.now(UTC)
    out = []
    limit = get_settings().max_upload_mb * 1024 * 1024
    for f in files:
        data = await f.read(limit + 1)
        try:
            out.append(DocumentOut.model_validate(add_document(db, d, f.filename or "document.pdf", data, kind)))
        except UploadError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{f.filename} : {exc}") from exc
    return out


def _own_document(db: Session, d: Dossier, document_id: str) -> Document:
    doc = db.get(Document, document_id)
    if doc is None or doc.dossier_id != d.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document introuvable.")
    return doc


@router.patch("/dossiers/{dossier_id}/documents/{document_id}", response_model=DocumentOut)
def update_document(
    document_id: str, body: DocumentUpdate, d: Dossier = Depends(own_dossier), db: Session = Depends(get_db)
) -> Document:
    doc = _own_document(db, d, document_id)
    if body.kind:
        doc.kind = body.kind
    if body.addendum_number is not None:
        doc.addendum_number = body.addendum_number
    db.commit()
    return doc


@router.delete("/dossiers/{dossier_id}/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str, d: Dossier = Depends(own_dossier), db: Session = Depends(get_db)) -> None:
    from api.app.services.storage import get_storage
    from worker.analysis.context import stamped_key
    from worker.llm.client import files_backend

    doc = _own_document(db, d, document_id)
    fb = files_backend()
    if doc.claude_file_id and fb is not None:
        fb.delete_file(doc.claude_file_id)
    storage = get_storage()
    for key in (doc.s3_key, stamped_key(doc)):
        storage.delete(key)
    db.delete(doc)
    db.commit()


@router.get("/dossiers/{dossier_id}/documents/{document_id}/file")
def document_file(document_id: str, d: Dossier = Depends(own_dossier), db: Session = Depends(get_db)) -> Response:
    from api.app.services.storage import get_storage

    doc = _own_document(db, d, document_id)
    return Response(
        get_storage().get(doc.s3_key),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{doc.filename}"', "Cache-Control": "private, max-age=3600"},
    )


# ---------- analyse ----------
@router.post(
    "/dossiers/{dossier_id}/analyze",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit("analyze", "rate_limit_analyze_per_hour"))],
)
def analyze(retry_failed: bool = False, d: Dossier = Depends(own_dossier), db: Session = Depends(get_db)) -> JobOut:
    from worker.llm.client import BudgetExceeded, LlmClient, LlmContext

    if not db.scalar(select(Document.id).where(Document.dossier_id == d.id).limit(1)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Téléversez au moins un PDF avant de lancer l'analyse.")
    try:
        LlmClient(LlmContext(company_id=d.company_id, dossier_id=d.id)).check_budget()
    except BudgetExceeded as exc:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, str(exc)) from exc
    last = _last_job(db, d.id)
    if last and last.status in RUNNING:
        return _job_out(last)
    if retry_failed and last and last.status in ("partial", "failed"):
        last.status = "queued"
        db.commit()
        enqueue("worker.tasks.analyze_dossier", last.id, True)
        return _job_out(last)
    if last and last.status == "failed" and (last.state or {}).get("failure_kind") != "budget":
        job = last  # reprise : les étapes terminées ne sont pas refaites
        job.status = "queued"
    else:
        job = Job(type="analysis", dossier_id=d.id, company_id=d.company_id)
        db.add(job)
    d.status = "analyzing"
    db.commit()
    enqueue("worker.tasks.analyze_dossier", job.id)
    return _job_out(job)


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, company: Company = Depends(current_company), db: Session = Depends(get_db)) -> JobOut:
    job = db.get(Job, job_id)
    if job is None or job.company_id != company.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tâche introuvable.")
    return _job_out(job)


# ---------- fiche ----------
def _field_out(f: FicheField, names: dict[str, str]) -> FieldOut:
    return FieldOut(
        id=f.id,
        section=f.section,
        key=f.key,
        label=f.label,
        value=f.value,
        citation=f.citation,
        document_id=f.document_id,
        document_name=names.get(f.document_id or ""),
        page=f.page,
        confidence=f.confidence,
        verified_status=f.verified_status,
        note=f.note,
        critical=f.critical,
        superseded_by_field_id=f.superseded_by_field_id,
        to_verify=_to_verify(f),
    )


@router.get("/dossiers/{dossier_id}/fiche", response_model=FicheOut)
def fiche(d: Dossier = Depends(own_dossier), db: Session = Depends(get_db)) -> FicheOut:
    from worker.analysis.catalog import SECTION_ORDER, SECTIONS, SPECS

    docs = {x.id: x for x in db.scalars(select(Document).where(Document.dossier_id == d.id))}
    names = {i: x.filename for i, x in docs.items()}
    fields = list(db.scalars(select(FicheField).where(FicheField.dossier_id == d.id)))
    by_id = {f.id: f for f in fields}
    order = {k: i for i, k in enumerate(SPECS)}
    sections = []
    for s in SECTION_ORDER:
        fs = sorted([f for f in fields if f.section == s], key=lambda f: (order.get(f.key, 999), f.created_at))
        sections.append({"key": s, "label": SECTIONS[s][0], "fields": [_field_out(f, names) for f in fs]})
    addenda = []
    for doc in sorted((x for x in docs.values() if x.kind == "addendum"), key=lambda x: x.addendum_number or 0):
        changes = []
        for f in fields:
            if f.document_id != doc.id:
                continue
            olds = [o for o in fields if o.superseded_by_field_id == f.id]
            changes.append(
                {
                    "field_id": f.id,
                    "key": f.key,
                    "label": f.label,
                    "new_value": f.value,
                    "page": f.page,
                    "old": [
                        {
                            "field_id": o.id,
                            "value": o.value,
                            "document_name": names.get(o.document_id or ""),
                            "document_id": o.document_id,
                            "page": o.page,
                        }
                        for o in olds
                    ],
                }
            )
        addenda.append(
            {
                "document_id": doc.id,
                "document_name": doc.filename,
                "addendum_number": doc.addendum_number,
                "changes": changes,
            }
        )
    job = _last_job(db, d.id)
    missing = list(((job.state or {}).get("worker_errors") or {}).keys()) if job else []
    _ = by_id
    return FicheOut(
        dossier_id=d.id,
        status=d.status,
        sections=sections,
        addenda=addenda,
        to_verify=sum(1 for f in fields if _to_verify(f)),
        missing_sections=missing,
    )


@router.patch("/dossiers/{dossier_id}/fiche/fields/{field_id}", response_model=FieldOut)
def patch_field(
    field_id: str, body: FieldPatch, d: Dossier = Depends(own_dossier), db: Session = Depends(get_db)
) -> FieldOut:
    f = db.get(FicheField, field_id)
    if f is None or f.dossier_id != d.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Champ introuvable.")
    if body.action == "verify":
        f.verified_status = "user_verified"
    else:  # correction : la valeur d'origine reste traçable dans la note (données d'évaluation)
        f.note = (
            (f.note + " · ") if f.note else ""
        ) + f"Valeur extraite à l'origine : {json.dumps(f.value, ensure_ascii=False)}"
        f.value = body.value
        if body.page:
            f.page = body.page
        f.verified_status = "user_corrected"
    f.confidence = "high"
    db.commit()
    names = {x.id: x.filename for x in db.scalars(select(Document).where(Document.dossier_id == d.id))}
    return _field_out(f, names)


# ---------- liste de vérification ----------
def _item_out(i: ChecklistItem, fields: dict[str, FicheField]) -> ChecklistItemOut:
    out = ChecklistItemOut.model_validate(i)
    f = fields.get(i.source_field_id or "")
    if f:
        out.source_document_id, out.source_page = f.document_id, f.page
    return out


def _fields(db: Session, d: Dossier) -> dict[str, FicheField]:
    return {f.id: f for f in db.scalars(select(FicheField).where(FicheField.dossier_id == d.id))}


@router.get("/dossiers/{dossier_id}/checklist", response_model=list[ChecklistItemOut])
def checklist(d: Dossier = Depends(own_dossier), db: Session = Depends(get_db)) -> list[ChecklistItemOut]:
    fields = _fields(db, d)
    items = db.scalars(
        select(ChecklistItem)
        .where(ChecklistItem.dossier_id == d.id)
        .order_by(ChecklistItem.blocking.desc(), ChecklistItem.position)
    )
    return [_item_out(i, fields) for i in items]


@router.post("/dossiers/{dossier_id}/checklist", response_model=ChecklistItemOut, status_code=status.HTTP_201_CREATED)
def add_item(
    body: ChecklistItemIn, d: Dossier = Depends(own_dossier), db: Session = Depends(get_db)
) -> ChecklistItemOut:
    i = ChecklistItem(
        dossier_id=d.id,
        label=body.label,
        assignee=body.assignee,
        due_date=body.due_date,
        blocking=body.blocking,
        user_created=True,
        category="autre",
        position=1000,
    )
    db.add(i)
    db.commit()
    return _item_out(i, {})


def _own_item(db: Session, d: Dossier, item_id: str) -> ChecklistItem:
    i = db.get(ChecklistItem, item_id)
    if i is None or i.dossier_id != d.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Élément introuvable.")
    return i


@router.patch("/dossiers/{dossier_id}/checklist/{item_id}", response_model=ChecklistItemOut)
def patch_item(
    item_id: str, body: ChecklistItemPatch, d: Dossier = Depends(own_dossier), db: Session = Depends(get_db)
) -> ChecklistItemOut:
    i = _own_item(db, d, item_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(i, k, v)
    if body.label is not None:
        i.user_created = True  # une modification humaine est conservée lors d'une réanalyse
    db.commit()
    return _item_out(i, _fields(db, d))


@router.delete("/dossiers/{dossier_id}/checklist/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_id: str, d: Dossier = Depends(own_dossier), db: Session = Depends(get_db)) -> None:
    db.delete(_own_item(db, d, item_id))
    db.commit()


@router.get("/dossiers/{dossier_id}/checklist.pdf")
def checklist_pdf(d: Dossier = Depends(own_dossier), db: Session = Depends(get_db)) -> Response:
    from api.app.services.export import checklist_to_pdf

    items = checklist(d, db)
    names = {x.id: x.filename for x in db.scalars(select(Document).where(Document.dossier_id == d.id))}
    pdf = checklist_to_pdf(d.title, items, names)
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="liste-de-verification.pdf"'},
    )


# ---------- go / no-go ----------
@router.get("/dossiers/{dossier_id}/go-no-go", response_model=GoNoGoOutApi)
def go_no_go(d: Dossier = Depends(own_dossier), db: Session = Depends(get_db)) -> GoNoGoOutApi:
    g = db.get(GoNoGo, d.id)
    if g is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recommandation pas encore générée.")
    fields = _fields(db, d)
    names = {x.id: x.filename for x in db.scalars(select(Document).where(Document.dossier_id == d.id))}

    def enrich(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for p in points:
            f = fields.get(p.get("field_id", ""))
            out.append(
                {
                    **p,
                    "document_id": f.document_id if f else None,
                    "page": f.page if f else None,
                    "document_name": names.get(f.document_id or "") if f else None,
                }
            )
        return out

    from api.app.services.benchmarks import price_benchmarks

    return GoNoGoOutApi(
        recommendation=g.recommendation,
        effort=g.effort,
        summary=g.summary,
        strengths=enrich(g.strengths),
        risks=enrich(g.risks),
        blockers=enrich(g.blockers),
        warning=g.warning,
        created_at=g.created_at,
        benchmarks=price_benchmarks(db, d.ocid),
    )


# ---------- assistant ----------
@router.get("/dossiers/{dossier_id}/chat", response_model=list[ChatMessageOut])
def chat_history(d: Dossier = Depends(own_dossier), db: Session = Depends(get_db)) -> list[ChatMessageOut]:
    msgs = db.scalars(select(ChatMessage).where(ChatMessage.dossier_id == d.id).order_by(ChatMessage.created_at))
    return [
        ChatMessageOut(
            id=m.id,
            role=m.role,
            text=(m.content or {}).get("text", ""),
            citations=m.citations or [],
            created_at=m.created_at,
        )
        for m in msgs
    ]


@router.post("/dossiers/{dossier_id}/chat", dependencies=[Depends(rate_limit("chat", "rate_limit_chat_per_hour"))])
def chat(body: ChatIn, d: Dossier = Depends(own_dossier)) -> EventSourceResponse:
    dossier_id = d.id

    def events() -> Iterator[dict[str, str]]:
        from worker.assistant.agent import answer

        with get_sessionmaker()() as db:  # session propre au flux (la requête est déjà terminée)
            for ev in answer(db, dossier_id, body.question):
                yield {"event": ev["type"], "data": json.dumps(ev, ensure_ascii=False)}

    return EventSourceResponse(events())
