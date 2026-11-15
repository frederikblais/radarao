"""Faux backend Claude pour les tests et les évaluations hors ligne."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pymupdf

Responder = Callable[[str, dict[str, Any]], Any]


def kind_of(params: dict[str, Any]) -> str:
    fmt = (params.get("output_config") or {}).get("format")
    if not fmt:
        return "text"
    props = set(fmt["schema"].get("properties", {}))
    for key, kind in [("champs", "extraction"), ("travailleurs", "plan"), ("champs_critiques_manquants", "evaluation"),
                      ("elements", "checklist"), ("recommandation", "go_no_go"), ("score", "judge"),
                      ("suggestions", "unspsc"), ("mots_cles", "enrichment"), ("resume", "summary")]:
        if key in props:
            return kind
    return "unknown"


def section_of(params: dict[str, Any]) -> str | None:
    text = json.dumps(params["messages"], ensure_ascii=False)
    m = re.search(r"Section à extraire : ([^.]+)\.", text)
    labels = {"Calendrier et logistique": "calendrier", "Admissibilité et conformité": "admissibilite",
              "Portée et exigences techniques": "portee", "Mode d'adjudication": "adjudication",
              "Clauses contractuelles et risques": "clauses", "Documents à remettre": "documents"}
    return labels.get(m.group(1)) if m else None


def message(text: str, model: str, stop: str = "end_turn", content: list[Any] | None = None) -> Any:
    return SimpleNamespace(
        content=content or [SimpleNamespace(type="text", text=text)], stop_reason=stop, model=model,
        usage=SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=800,
                              cache_creation_input_tokens=0))


class FakeBackend:
    def __init__(self, responder: Responder) -> None:
        self.responder = responder
        self.calls: list[dict[str, Any]] = []

    def create(self, params: dict[str, Any]) -> Any:
        self.calls.append(params)
        out = self.responder(kind_of(params), params)
        if isinstance(out, SimpleNamespace):
            return out
        return message(json.dumps(out, ensure_ascii=False), params["model"])

    @contextmanager
    def stream(self, params: dict[str, Any]) -> Iterator[Any]:
        msg = self.create(params)

        class _S:
            def __iter__(self) -> Iterator[Any]:
                for b in msg.content:
                    if getattr(b, "type", "") == "text":
                        yield SimpleNamespace(type="content_block_delta",
                                              delta=SimpleNamespace(type="text_delta", text=b.text))

            def get_final_message(self) -> Any:
                return msg

        yield _S()

    def create_batch(self, requests: list[dict[str, Any]]) -> str:
        self._batch = requests
        return "batch_fake"

    def batch_status(self, batch_id: str) -> str:
        return "ended"

    def batch_results(self, batch_id: str) -> Iterator[Any]:
        for r in self._batch:
            msg = self.create(r["params"])
            yield SimpleNamespace(custom_id=r["custom_id"], result=SimpleNamespace(type="succeeded", message=msg))

    def upload_file(self, filename: str, data: bytes, expires_in_seconds: int) -> str:
        return f"file_fake_{filename}"

    def delete_file(self, file_id: str) -> None:
        self.deleted = [*getattr(self, "deleted", []), file_id]


def make_pdf(pages: list[str], title: str = "") -> bytes:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 545, 800), text, fontsize=10, fontname="helv")
    if title:
        doc.set_metadata({"title": title})
    data: bytes = doc.tobytes()
    return data
