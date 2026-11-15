"""Orchestrateur P-ANALYSE (section 10.4) : E0 → E1 → E2 → E3 → E4 → E5 (≤ 2 boucles) → E6.

Chaque étape enregistre son résultat dans `jobs.state` et s'ajoute à `jobs.completed_steps` :
une reprise saute les étapes terminées (si E5 échoue, on relance à partir de E5 sans refaire E2).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from api.app.models import ChecklistItem, Company, Document, DocumentPage, Dossier, FicheField, GoNoGo, Job
from api.app.schemas.ai import AnalysisPlan, ExtractedField, SectionExtraction, WorkerPlan
from worker.analysis import evaluator, synthesis
from worker.analysis.catalog import SECTION_ORDER, SPECS
from worker.analysis.merge import MergedField, merge_fields
from worker.analysis.planner import plan_analysis
from worker.analysis.preprocess import preprocess
from worker.analysis.verifier import validate_value, verify_quote
from worker.analysis.workers.extract import run_worker
from worker.llm.client import BudgetExceeded, LlmClient, LlmContext, LlmError

log = logging.getLogger("radarao.analysis")

WORKER_TIMEOUT_S = 300
STEPS = [  # (clé, libellé affiché, progression à la fin de l'étape)
    ("E0", "Lecture", 15),
    ("E1", "Planification", 22),
    ("E2", "Extraction", 62),
    ("E3", "Fusion des addenda", 66),
    ("E4", "Vérification", 72),
    ("E5", "Évaluation", 86),
    ("E6", "Synthèse", 100),
]
STEP_LABEL = {k: label for k, label, _ in STEPS}
STEP_PROGRESS = {k: p for k, _, p in STEPS}


class Analysis:
    def __init__(self, db: Session, job: Job, llm: LlmClient | None = None) -> None:
        self.db = db
        self.job = job
        self.dossier = db.get(Dossier, job.dossier_id)
        assert self.dossier is not None
        self.company = db.get(Company, self.dossier.company_id)
        self.llm = llm or LlmClient(LlmContext(job.id, self.dossier.company_id, self.dossier.id))
        self.state: dict[str, Any] = dict(job.state or {})

    # ---------- utilitaires ----------
    def _save(self, step: str | None = None, progress: int | None = None) -> None:
        self.job.state = dict(self.state)
        if step:
            done = list(self.job.completed_steps or [])
            if step not in done:
                done.append(step)
            self.job.completed_steps = done
        if progress is not None:
            self.job.progress = progress
        self.db.commit()

    def _start(self, step: str) -> None:
        self.job.step = step
        self.db.commit()

    def _done(self, step: str) -> bool:
        return step in (self.job.completed_steps or [])

    def _docs(self) -> dict[str, Document]:
        ids = self.state["aliases"]
        docs = {d.id: d for d in self.db.scalars(select(Document).where(Document.id.in_(list(ids.values()))))}
        return {a: docs[i] for a, i in ids.items() if i in docs}

    def _pages(self) -> dict[str, dict[int, str]]:
        out: dict[str, dict[int, str]] = {}
        for alias, doc in self._docs().items():
            rows = self.db.execute(
                select(DocumentPage.page_number, DocumentPage.text).where(DocumentPage.document_id == doc.id)
            ).all()
            out[alias] = {n: t for n, t in rows}
        return out

    # ---------- étapes ----------
    def e0(self) -> None:
        self._start("E0")
        self.dossier.status = "analyzing"  # type: ignore[union-attr]
        try:
            backend = self.llm.backend
        except LlmError:
            backend = None
        fb = backend if hasattr(backend, "upload_file") else None
        res = preprocess(self.db, self.dossier, fb)  # type: ignore[arg-type]
        if not res["aliases"]:
            raise LlmError("Aucun document lisible dans ce dossier (PDF protégé par mot de passe ou illisible).")
        self.state.update(res)
        self._save("E0", STEP_PROGRESS["E0"])

    def e1(self) -> None:
        self._start("E1")
        plan = plan_analysis(self.db, self.llm, self._docs(), int(self.state["total_pages"]))
        self.state["plan"] = plan.model_dump()
        self._save("E1", STEP_PROGRESS["E1"])

    def _run_workers(
        self, sections: list[str], consignes: dict[str, str] | None = None, plan_override: dict[str, Any] | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        plan = AnalysisPlan.model_validate(self.state["plan"])
        by_section: dict[str, WorkerPlan] = {w.travailleur: w for w in plan.travailleurs}
        if plan_override:
            for s, w in plan_override.items():
                by_section[s] = w
        docs = self._docs()
        total = int(self.state["total_pages"])
        results: dict[str, list[dict[str, Any]]] = {}
        errors: dict[str, str] = dict(self.state.get("worker_errors", {}))
        # Travailleurs lancés en rafale : ils partagent le même préfixe document (cache de 5 min).
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {
                s: pool.submit(
                    run_worker,
                    self.llm,
                    s,
                    by_section[s],
                    docs,
                    total,
                    (consignes or {}).get(s),
                )
                for s in sections
            }
            for s, fut in futures.items():
                try:
                    out: SectionExtraction = fut.result(timeout=WORKER_TIMEOUT_S)
                    results[s] = [f.model_dump() for f in out.champs]
                    errors.pop(s, None)
                except BudgetExceeded:
                    raise
                except (LlmError, FutureTimeout, Exception) as exc:  # noqa: BLE001 — échec partiel
                    log.warning(
                        "travailleur en échec", extra={"section": s, "error": str(exc)[:300], "job_id": self.job.id}
                    )
                    errors[s] = f"{type(exc).__name__}: {exc}"[:300]
        self.state["worker_errors"] = errors
        return results

    def e2(self) -> None:
        self._start("E2")
        extractions = dict(self.state.get("extractions", {}))
        todo = [s for s in SECTION_ORDER if s not in extractions]
        extractions.update(self._run_workers(todo))
        self.state["extractions"] = extractions
        if not extractions:
            raise LlmError("Aucune section n'a pu être extraite.")
        self._save("E2", STEP_PROGRESS["E2"])

    def _merge(self) -> list[MergedField]:
        docs = self._docs()
        ranks = {a: (d.addendum_number or 1) if d.kind == "addendum" else 0 for a, d in docs.items()}
        order = AnalysisPlan.model_validate(self.state["plan"]).addenda
        for o in order:  # ordre confirmé par le planificateur
            if o.document_id in ranks and ranks[o.document_id] > 0:
                ranks[o.document_id] = o.numero
        extractions = [
            (s, f"E2_{s}", [ExtractedField.model_validate(x) for x in fields])
            for s, fields in self.state["extractions"].items()
        ]
        return merge_fields(extractions, ranks)

    def _verify(self, merged: list[MergedField]) -> tuple[dict[str, str], dict[str, float], list[str]]:
        pages = self._pages()
        statuses: dict[str, str] = {}
        ratios: dict[str, float] = {}
        flagged: list[str] = []
        for f in merged:
            if f.value is None:
                statuses[f.id] = "not_found"
                continue
            alias = f.document_id
            v = verify_quote(f.citation, f.page, pages.get(alias or "", {}))
            f.page = v.page
            ratios[f.id] = round(v.ratio, 3)
            err = validate_value(f.key, f.value)
            if err:
                f.notes.append(err)
            if v.status != "auto_ok" or err:
                statuses[f.id] = "quote_not_found" if v.status != "auto_ok" else "auto_ok"
                f.confidence = "low"
                flagged.append(f"{f.key} ({'citation introuvable' if v.status != 'auto_ok' else err})")
            else:
                statuses[f.id] = "auto_ok"
        return statuses, ratios, flagged

    def e3_e4(self) -> tuple[list[MergedField], dict[str, str], dict[str, float], list[str]]:
        self._start("E3")
        merged = self._merge()
        self._save(None, STEP_PROGRESS["E3"])
        self._start("E4")
        statuses, ratios, flagged = self._verify(merged)
        return merged, statuses, ratios, flagged

    def e5(self) -> tuple[list[MergedField], dict[str, str], dict[str, float]]:
        merged, statuses, ratios, flagged = self.e3_e4()
        self._save("E4", STEP_PROGRESS["E4"])
        self._start("E5")
        loops = int(self.state.get("eval_loops", 0))
        id_to_alias = {a: a for a in self.state["aliases"]}
        report = None
        while loops < evaluator.MAX_LOOPS:
            issues = evaluator.deterministic_issues(merged, statuses)
            if not issues and not flagged:
                break
            report = evaluator.evaluate(self.llm, merged, statuses, id_to_alias, flagged)
            if not report.a_reextraire:
                break
            loops += 1
            consignes: dict[str, str] = {r.travailleur: r.consigne for r in report.a_reextraire}
            override = {
                r.travailleur: {
                    "travailleur": r.travailleur,
                    "plages": [p.model_dump() for p in r.plages],
                    "remarque": r.consigne,
                }
                for r in report.a_reextraire
                if r.plages
            }
            from api.app.schemas.ai import WorkerPlan

            new = self._run_workers(
                list(consignes), consignes, {s: WorkerPlan.model_validate(w) for s, w in override.items()}
            )
            for s, fields in new.items():  # remplacement clé par clé
                new_keys = {f["cle"] for f in fields if f.get("valeur") is not None}
                kept = [f for f in self.state["extractions"].get(s, []) if f["cle"] not in new_keys]
                self.state["extractions"][s] = kept + [
                    f for f in fields if f.get("valeur") is not None or f["cle"] not in {k["cle"] for k in kept}
                ]
            self.state["eval_loops"] = loops
            self._save()
            merged, statuses, ratios, flagged = self.e3_e4()
        self.state["evaluation"] = report.model_dump() if report else None
        self._persist(merged, statuses, ratios)
        self._save("E5", STEP_PROGRESS["E5"])
        return merged, statuses, ratios

    def _persist(self, merged: list[MergedField], statuses: dict[str, str], ratios: dict[str, float]) -> None:
        d = self.dossier
        assert d is not None
        aliases = self.state["aliases"]
        # Les corrections et vérifications humaines sont conservées d'une analyse à l'autre.
        human = list(
            self.db.scalars(
                select(FicheField).where(
                    FicheField.dossier_id == d.id, FicheField.verified_status.in_(["user_verified", "user_corrected"])
                )
            )
        )
        human_keys = {f.key for f in human if not SPECS.get(f.key) or not SPECS[f.key].multi}
        self.db.execute(
            delete(FicheField).where(
                FicheField.dossier_id == d.id, FicheField.verified_status.not_in(["user_verified", "user_corrected"])
            )
        )
        contradictions = {
            c["cle"]: c["description"] for c in ((self.state.get("evaluation") or {}).get("contradictions") or [])
        }
        for f in merged:
            if f.key in human_keys and f.superseded_by is None:
                continue
            notes = [n for n in [f.note, *f.notes, contradictions.get(f.key)] if n]
            self.db.add(
                FicheField(
                    id=f.id,
                    dossier_id=d.id,
                    section=f.section,
                    key=f.key,
                    label=SPECS[f.key].label,
                    value=f.value,
                    citation=f.citation,
                    document_id=aliases.get(f.document_id or ""),
                    page=f.page,
                    confidence=f.confidence,
                    verified_status=statuses.get(f.id, "pending"),
                    note=" · ".join(notes) or None,
                    critical=SPECS[f.key].critical,
                    superseded_by_field_id=f.superseded_by,
                    created_by_step=f.step,
                    match_ratio=ratios.get(f.id),
                )
            )
        self.db.flush()

    def e6(self) -> None:
        self._start("E6")
        d = self.dossier
        assert d is not None and self.company is not None
        fields = list(self.db.scalars(select(FicheField).where(FicheField.dossier_id == d.id)))
        blockers = synthesis.find_blockers(fields, self.company)
        blocking = {b.field_id: b.reason for b in blockers}
        candidates = synthesis.checklist_candidates(fields)
        llm: LlmClient | None = self.llm
        labels = synthesis.rewrite_labels(llm, candidates)
        # Les éléments ajoutés ou modifiés par l'utilisateur sont conservés.
        self.db.execute(
            delete(ChecklistItem).where(ChecklistItem.dossier_id == d.id, ChecklistItem.user_created.is_(False))
        )
        for pos, f in enumerate(sorted(candidates, key=lambda f: (f.key != "document_a_remettre", f.key))):
            self.db.add(
                ChecklistItem(
                    dossier_id=d.id,
                    label=labels[f.id],
                    source_field_id=f.id,
                    position=pos,
                    category="document" if f.key == "document_a_remettre" else "admissibilite",
                    blocking=f.id in blocking,
                    blocking_reason=blocking.get(f.id),
                )
            )
        id_to_alias = {v: k for k, v in self.state["aliases"].items()}
        out, warning = synthesis.go_no_go(llm, fields, self.company, blockers, id_to_alias)
        self.db.execute(delete(GoNoGo).where(GoNoGo.dossier_id == d.id))
        self.db.add(
            GoNoGo(
                dossier_id=d.id,
                recommendation=out.recommandation,
                effort=out.effort,
                summary=out.resume,
                strengths=[p.model_dump() for p in out.forces],
                risks=[p.model_dump() for p in out.risques],
                blockers=[p.model_dump() for p in out.bloquants],
                warning=warning,
            )
        )
        self._save("E6", STEP_PROGRESS["E6"])

    # ---------- exécution ----------
    def run(self) -> Job:
        self.job.status = "running"
        self.job.started_at = self.job.started_at or datetime.now(UTC)
        self.job.error = None
        self.db.commit()
        steps: list[tuple[str, Callable[[], Any]]] = [
            ("E0", self.e0),
            ("E1", self.e1),
            ("E2", self.e2),
            ("E5", self.e5),
            ("E6", self.e6),
        ]
        try:
            for key, fn in steps:
                if not self._done(key):
                    fn()
            partial = bool(self.state.get("worker_errors"))
            self.job.status = "partial" if partial else "succeeded"
            self.dossier.status = "partial" if partial else "ready"  # type: ignore[union-attr]
            if partial:
                self.job.error = "Sections non extraites : " + ", ".join(self.state["worker_errors"])
        except BudgetExceeded as exc:
            self._fail(str(exc), "budget")
        except Exception as exc:  # noqa: BLE001 — tout échec est affiché proprement (section 7.5)
            log.exception("analyse en échec", extra={"job_id": self.job.id, "dossier_id": self.job.dossier_id})
            self.db.rollback()
            self._fail(f"{STEP_LABEL.get(self.job.step or '', self.job.step)} : {exc}"[:800], "failed")
        self.job.finished_at = datetime.now(UTC)
        self.db.commit()
        return self.job

    def _fail(self, message: str, kind: str) -> None:
        self.job.status = "failed"
        self.job.error = message
        self.state["failure_kind"] = kind
        self.job.state = dict(self.state)
        has_fiche = self.db.scalar(select(FicheField.id).where(FicheField.dossier_id == self.job.dossier_id).limit(1))
        self.dossier.status = "partial" if has_fiche else "failed"  # type: ignore[union-attr]


def run_analysis(db: Session, job_id: str, llm: LlmClient | None = None, retry_failed: bool = False) -> Job:
    """retry_failed : relance seulement les sections en échec, puis fusion, vérification et synthèse."""
    job = db.get(Job, job_id)
    assert job is not None
    if retry_failed:
        job.completed_steps = [s for s in (job.completed_steps or []) if s in ("E0", "E1")]
        state = dict(job.state or {})
        state["eval_loops"] = 0
        job.state = state
        db.commit()
    return Analysis(db, job, llm).run()
