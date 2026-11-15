"""Pipeline P-MATCH (section 10.3) : filtres SQL → vecteurs → rerank → LLM juge → score final."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from api.app.models import Company, CompanyEmbedding, Match, Tender, TenderEmbedding, TenderItem
from api.app.schemas.ai import MatchJudgement
from worker.embeddings import Embedder
from worker.ingestion.regions import REGIONS
from worker.llm import config as llm_config
from worker.llm.client import BudgetExceeded, LlmClient, LlmContext, LlmError
from worker.llm.prompts import load_prompt
from worker.matching.profile import accepted_codes, profile_for_llm, profile_text

log = logging.getLogger("radarao.matching")

TOP_VECTOR = 50
TOP_RERANK = 15
JUDGE_CONCURRENCY = 5
W_JUDGE, W_SIM = 0.6, 0.4
MIN_HOURS_LEFT = 48


@dataclass
class Candidate:
    tender: Tender
    codes: list[str]
    similarity: float
    bonus: float = 0.0
    rerank: float = 0.0

    @property
    def sim_total(self) -> float:
        return self.similarity + self.bonus


def tender_text(t: Tender, items: list[TenderItem]) -> str:
    labels = "; ".join(f"{i.unspsc_code} {i.description or ''}" for i in items)
    parts = [t.title, f"Organisme : {t.buyer_name or ''}", f"Catégorie : {t.main_category or ''}",
             f"Région : {REGIONS.get(t.region_code or '', 'inconnue')}", f"Classification : {labels}"]
    if t.summary_fr:
        parts.append(t.summary_fr)
    if t.keywords:
        parts.append("Mots-clés : " + ", ".join(t.keywords))
    return "\n".join(parts)


def embed_tenders(db: Session, embedder: Embedder, only_missing: bool = True) -> int:
    q = select(Tender).where(Tender.status == "active")
    if only_missing:
        q = q.where(~select(TenderEmbedding.ocid).where(TenderEmbedding.ocid == Tender.ocid).exists())
    tenders = list(db.scalars(q))
    if not tenders:
        return 0
    items: dict[str, list[TenderItem]] = {}
    for it in db.scalars(select(TenderItem).where(TenderItem.ocid.in_([t.ocid for t in tenders]))):
        items.setdefault(it.ocid, []).append(it)
    vecs = embedder.embed([tender_text(t, items.get(t.ocid, [])) for t in tenders], input_type="document")
    for t, v in zip(tenders, vecs, strict=True):
        db.merge(TenderEmbedding(ocid=t.ocid, embedding=v))
    db.commit()
    return len(tenders)


def embed_company(db: Session, company: Company, embedder: Embedder) -> list[float]:
    vec = embedder.embed([profile_text(company)], input_type="query")[0]
    db.merge(CompanyEmbedding(company_id=company.id, embedding=vec, updated_at=datetime.now(UTC)))
    db.commit()
    return vec


def unspsc_bonus(profile_codes: set[str], tender_codes: list[str]) -> tuple[float, str | None]:
    """Commodité (8 chiffres) +0,15; classe (6) +0,10; famille (4) +0,05."""
    best, reason = 0.0, None
    for tc in tender_codes:
        for pc in profile_codes:
            if tc == pc:
                return 0.15, f"Code UNSPSC {tc} correspondant"
            if tc[:6] == pc[:6] and best < 0.10:
                best, reason = 0.10, "Code UNSPSC de la même classe"
            elif tc[:4] == pc[:4] and best < 0.05:
                best, reason = 0.05, "Code UNSPSC de la même famille"
    return best, reason


def calibrate(sim: float, offline: bool) -> float:
    """Similarité cosinus (+ bonus) ramenée sur 0–100 (bornes empiriques par type d'embeddings)."""
    lo, hi = (0.0, 0.45) if offline else (0.20, 0.75)
    return max(0.0, min(100.0, (sim - lo) / (hi - lo) * 100))


def value_in_range(t: Tender, c: Company) -> str:
    if t.value_amount is None or (c.value_min is None and c.value_max is None):
        return "inconnu"
    if c.value_min is not None and t.value_amount < c.value_min:
        return "non"
    if c.value_max is not None and t.value_amount > c.value_max:
        return "non"
    return "oui"


def deterministic_reasons(cand: Candidate, company: Company, code_reason: str | None) -> tuple[list[str], list[str]]:
    t = cand.tender
    reasons: list[str] = []
    blockers: list[str] = []
    if code_reason:
        reasons.append(code_reason)
    if t.region_code and t.region_code in (company.regions or []):
        reasons.append("Région desservie")
    v = value_in_range(t, company)
    if v == "oui":
        reasons.append("Valeur probable dans votre fourchette")
    elif v == "non":
        blockers.append("Valeur possiblement hors de votre fourchette")
    q = company.qualifications or {}
    if t.main_category == "works" and not (q.get("rbq") or {}).get("held"):
        blockers.append("Exige probablement une licence RBQ que vous n'avez pas")
    return reasons, blockers


def heuristic_judgement(cand: Candidate, company: Company, reasons: list[str], blockers: list[str]) -> MatchJudgement:
    score = 40 + int(cand.bonus * 200) + (15 if "Région desservie" in reasons else 0) + int(cand.rerank * 20)
    score -= 15 * len(blockers)
    return MatchJudgement(score=max(0, min(100, score)), raisons=reasons or ["Similarité avec votre description"],
                          bloquants_potentiels=blockers, valeur_probable_dans_fourchette=value_in_range(cand.tender, company))  # type: ignore[arg-type]


def judge(llm: LlmClient, company: Company, cand: Candidate) -> MatchJudgement:
    t = cand.tender
    meta = (f"Titre : {t.title}\nOrganisme : {t.buyer_name}\nCatégorie : {t.main_category}\n"
            f"Mode : {t.procurement_method_details or t.procurement_method}\n"
            f"Région : {REGIONS.get(t.region_code or '', 'inconnue')}\nCodes UNSPSC : {', '.join(cand.codes)}\n"
            f"Valeur publiée : {t.value_amount if t.value_amount else 'non publiée'}\n"
            f"Date limite : {t.end_date.isoformat() if t.end_date else 'inconnue'}\n"
            + (f"Résumé : {t.summary_fr}\n" if t.summary_fr else ""))
    user = f"<profil>\n{profile_for_llm(company)}\n</profil>\n<avis>\n{meta}</avis>"
    return llm.structured("P-MATCH_judge", "match_judge", load_prompt("match_judge"),
                          [{"role": "user", "content": user}], MatchJudgement)


def hard_filter(db: Session, company: Company, now: datetime) -> list[Tender]:
    q = select(Tender).where(Tender.status == "active", Tender.end_date > now + timedelta(hours=MIN_HOURS_LEFT))
    if company.categories:
        q = q.where(or_(Tender.main_category.in_(company.categories), Tender.main_category.is_(None)))
    if company.regions:
        q = q.where(or_(Tender.region_code.in_(company.regions), Tender.region_code.is_(None)))
    excluded = (company.buyer_preferences or {}).get("excluded") or []
    if excluded:
        q = q.where(or_(Tender.buyer_party_id.is_(None), Tender.buyer_party_id.not_in(excluded)))
    # Avis manuels : visibles seulement par l'entreprise qui les a ajoutés.
    q = q.where(or_(Tender.source == "open_data", Tender.created_by_company_id == company.id))
    return list(db.scalars(q))


def run_match(db: Session, company_id: str, llm: LlmClient | None = None, embedder: Embedder | None = None,
              now: datetime | None = None) -> list[Match]:
    now = now or datetime.now(UTC)
    company = db.get(Company, company_id)
    assert company is not None
    embedder = embedder or Embedder()
    if llm is None:
        try:
            llm = LlmClient(LlmContext(company_id=company_id))
            _ = llm.backend
        except LlmError:
            llm = None

    # Étape 1 — filtres durs (SQL)
    pool = hard_filter(db, company, now)
    if not pool:
        db.execute(delete(Match).where(Match.company_id == company_id, Match.user_feedback.is_(None),
                                       Match.tracked.is_(False)))
        db.commit()
        return []
    embed_tenders(db, embedder)
    cvec = embed_company(db, company, embedder)

    # Étape 2 — similarité vectorielle (pgvector) + bonus UNSPSC
    ocids = [t.ocid for t in pool]
    dist = TenderEmbedding.embedding.cosine_distance(cvec)
    rows = db.execute(select(TenderEmbedding.ocid, (1 - dist).label("sim")).where(TenderEmbedding.ocid.in_(ocids))).all()
    sims = {o: float(s) for o, s in rows}
    codes: dict[str, list[str]] = {}
    items_by: dict[str, list[TenderItem]] = {}
    for it in db.scalars(select(TenderItem).where(TenderItem.ocid.in_(ocids))):
        codes.setdefault(it.ocid, []).append(it.unspsc_code)
        items_by.setdefault(it.ocid, []).append(it)
    profile_codes = {c for c, _ in accepted_codes(company)}
    cands: list[Candidate] = []
    code_reasons: dict[str, str | None] = {}
    for t in pool:
        bonus, reason = unspsc_bonus(profile_codes, codes.get(t.ocid, []))
        code_reasons[t.ocid] = reason
        cands.append(Candidate(t, codes.get(t.ocid, []), sims.get(t.ocid, 0.0), bonus))
    cands.sort(key=lambda c: -c.sim_total)
    top = cands[:TOP_VECTOR]

    # Étape 3 — reranking
    docs = [tender_text(c.tender, items_by.get(c.tender.ocid, [])) for c in top]
    hits = embedder.rerank(profile_text(company), docs, top_k=min(TOP_RERANK, len(top)))
    reranked = []
    for h in hits:
        top[h.index].rerank = h.score
        reranked.append(top[h.index])

    # Étape 4 — LLM juge (en parallèle, concurrence limitée)
    pre = {c.tender.ocid: deterministic_reasons(c, company, code_reasons[c.tender.ocid]) for c in reranked}
    judgements: dict[str, tuple[MatchJudgement, str]] = {}

    def _one(c: Candidate) -> tuple[str, MatchJudgement, str]:
        r, b = pre[c.tender.ocid]
        if llm is not None:
            try:
                return c.tender.ocid, judge(llm, company, c), llm_config.ROLES["match_judge"].model
            except BudgetExceeded:
                pass
            except LlmError as exc:
                log.warning("juge en échec", extra={"ocid": c.tender.ocid, "error": str(exc)[:200]})
        return c.tender.ocid, heuristic_judgement(c, company, r, b), "heuristic"

    with ThreadPoolExecutor(max_workers=JUDGE_CONCURRENCY) as ex:
        for ocid, j, model in ex.map(_one, reranked):
            judgements[ocid] = (j, model)

    # Étape 5 — score final et enregistrement
    existing = {m.ocid: m for m in db.scalars(select(Match).where(Match.company_id == company_id))}
    keep = {c.tender.ocid for c in reranked}
    for ocid, m in existing.items():  # retirer les anciens résultats non suivis et sans retour
        if ocid not in keep and m.user_feedback is None and not m.tracked:
            db.delete(m)
    out = []
    for c in reranked:
        j, model = judgements[c.tender.ocid]
        r, b = pre[c.tender.ocid]
        sim_norm = calibrate(c.sim_total, embedder.offline)
        score = round(W_JUDGE * j.score + W_SIM * sim_norm)
        reasons = list(dict.fromkeys([*r, *j.raisons]))[:3] or ["Similarité avec votre description"]
        blockers = list(dict.fromkeys([*b, *j.bloquants_potentiels]))[:3]
        m = existing.get(c.tender.ocid) or Match(company_id=company_id, ocid=c.tender.ocid)
        m.score, m.similarity, m.judge_score = score, round(c.sim_total, 4), j.score
        m.reasons, m.blockers, m.value_in_range = reasons, blockers, j.valeur_probable_dans_fourchette
        m.model, m.computed_at = model, now
        db.add(m)
        out.append(m)
    db.commit()
    return sorted(out, key=lambda m: -m.score)
