"""P-ASSISTANT : agent avec outils (lecture seule) et citations natives (section 10.5)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.app.models import ChatMessage, Company, Dossier
from worker.assistant.tools import TOOLS, ToolContext, execute
from worker.embeddings import Embedder
from worker.llm.client import BudgetExceeded, LlmClient, LlmContext, LlmError
from worker.llm.prompts import render

MAX_TURNS = 8
HISTORY_MESSAGES = 12
LIMIT_MESSAGE = (
    "Je n'ai pas pu terminer la recherche dans la limite d'étapes prévue. "
    "Reformulez la question de façon plus précise, ou consultez la fiche."
)
_TITLE_RE = re.compile(r"^(D\d+) · p\. (\d+)")


def _citations(final: Any, alias_to_id: dict[str, str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for block in final.content:
        for c in getattr(block, "citations", None) or []:
            title = getattr(c, "document_title", "") or ""
            m = _TITLE_RE.match(title)
            if not m or m.group(1) not in alias_to_id:
                continue
            out.append(
                {
                    "document_id": alias_to_id[m.group(1)],
                    "alias": m.group(1),
                    "page": int(m.group(2)),
                    "cited_text": getattr(c, "cited_text", "")[:500],
                    "title": title,
                }
            )
    uniq = {(c["document_id"], c["page"], c["cited_text"]): c for c in out}
    return list(uniq.values())


def _serialize(content: Any) -> list[dict[str, Any]]:
    blocks = []
    for b in content:
        if hasattr(b, "model_dump"):
            d = b.model_dump(exclude_none=True)
        elif isinstance(b, dict):
            d = b
        else:
            d = {k: v for k, v in vars(b).items() if not k.startswith("_")}
        blocks.append(d)
    return blocks


def answer(
    db: Session, dossier_id: str, question: str, llm: LlmClient | None = None, embedder: Embedder | None = None
) -> Iterator[dict[str, Any]]:
    """Génère des événements : {"type": "text", "text"}, {"type": "tool", "name"}, {"type": "done", ...}."""
    dossier = db.get(Dossier, dossier_id)
    assert dossier is not None
    company = db.get(Company, dossier.company_id)
    assert company is not None
    ctx = ToolContext(db, dossier, company, embedder or Embedder())
    alias_to_id = {a: d.id for a, d in ctx.alias_map().items()}
    llm = llm or LlmClient(LlmContext(company_id=company.id, dossier_id=dossier.id))
    system = render("assistant", dossier_title=dossier.title)

    history = list(
        db.scalars(
            select(ChatMessage)
            .where(ChatMessage.dossier_id == dossier_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(HISTORY_MESSAGES)
        )
    )[::-1]
    messages: list[dict[str, Any]] = [
        {"role": m.role, "content": m.content["text"]}
        for m in history
        if isinstance(m.content, dict) and m.content.get("text")
    ]
    messages.append({"role": "user", "content": question})
    db.add(ChatMessage(dossier_id=dossier_id, role="user", content={"text": question}))
    db.commit()

    text_parts: list[str] = []
    final = None
    try:
        for _turn in range(MAX_TURNS):
            final = None
            turn_text: list[str] = []
            for kind, payload in llm.stream("P-ASSISTANT", "assistant", system, messages, tools=TOOLS):
                if kind == "text":
                    turn_text.append(payload)
                    yield {"type": "text", "text": payload}
                else:
                    final = payload
            assert final is not None
            text_parts.extend(turn_text)
            if final.stop_reason != "tool_use":
                break
            uses = [b for b in final.content if getattr(b, "type", "") == "tool_use"]
            for u in uses:
                yield {"type": "tool", "name": u.name}
            with ThreadPoolExecutor(max_workers=4) as ex:
                results = list(ex.map(lambda u: execute(ctx, u.name, dict(u.input or {})), uses))
            messages.append({"role": "assistant", "content": _serialize(final.content)})
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": u.id, "content": res, "is_error": err}
                        for u, (res, err) in zip(uses, results, strict=True)
                    ],
                }
            )
        else:
            text_parts = [LIMIT_MESSAGE]
            yield {"type": "text", "text": LIMIT_MESSAGE}
    except BudgetExceeded as exc:
        msg = f"Budget d'analyse atteint : {exc}"
        text_parts = [msg]
        yield {"type": "error", "text": msg}
    except LlmError as exc:
        msg = f"L'assistant est indisponible pour le moment ({exc})."
        text_parts = [msg]
        yield {"type": "error", "text": msg}

    citations = _citations(final, alias_to_id) if final is not None and final.stop_reason != "tool_use" else []
    text = "".join(text_parts).strip()
    db.add(ChatMessage(dossier_id=dossier_id, role="assistant", content={"text": text}, citations=citations))
    db.commit()
    yield {"type": "done", "text": text, "citations": citations}
