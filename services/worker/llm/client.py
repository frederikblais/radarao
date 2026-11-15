"""Client Claude UNIQUE de RadarAO (CLAUDE.md : aucun appel direct ailleurs).

Responsabilités :
- reprises avec délai exponentiel sur 429 / 5xx / erreurs réseau;
- journalisation de chaque appel dans `llm_calls` (jetons, cache, coût, latence, stop_reason);
- refus de l'appel si le budget du dossier ou le budget mensuel de l'entreprise est dépassé;
- sorties structurées validées par Pydantic (jamais combinées avec les citations);
- repli serveur en cas de refus du classificateur (bêta `server-side-fallback`).
"""

from __future__ import annotations

import json
import logging
import random
import time
from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select

from api.app.config import get_settings
from api.app.db import get_sessionmaker
from api.app.models import LlmCall
from worker.llm import config
from worker.llm.schema import strict_schema

log = logging.getLogger("radarao.llm")
T = TypeVar("T", bound=BaseModel)


class LlmError(Exception):
    """Erreur générique du client LLM."""


class LlmUnavailable(LlmError):
    """Aucune clé API ou mode hors ligne."""


class BudgetExceeded(LlmError):
    """Budget du dossier ou budget mensuel de l'entreprise atteint (section 7.5)."""


class LlmRefusal(LlmError):
    """Le modèle (et ses replis) a refusé la requête."""


class LlmOutputError(LlmError):
    """Sortie tronquée ou non conforme au schéma."""


class Backend(Protocol):
    def create(self, params: dict[str, Any]) -> Any: ...

    def stream(self, params: dict[str, Any]) -> AbstractContextManager[Any]: ...

    def create_batch(self, requests: list[dict[str, Any]]) -> str: ...

    def batch_status(self, batch_id: str) -> str: ...

    def batch_results(self, batch_id: str) -> Iterator[Any]: ...


class AnthropicBackend:
    def __init__(self) -> None:
        s = get_settings()
        if not s.anthropic_api_key:
            raise LlmUnavailable("ANTHROPIC_API_KEY absente : l'analyse IA est désactivée.")
        # Reprises gérées par LlmClient (pour journaliser chaque tentative).
        self._client = anthropic.Anthropic(api_key=s.anthropic_api_key, max_retries=0, timeout=600)

    def _uses_fallback(self, params: dict[str, Any]) -> bool:
        return config.ENABLE_REFUSAL_FALLBACKS and params["model"] in config.FALLBACK_CAPABLE

    def create(self, params: dict[str, Any]) -> Any:
        if self._uses_fallback(params):
            return self._client.beta.messages.create(
                **params, betas=[config.REFUSAL_FALLBACK_BETA], fallbacks="default")
        return self._client.messages.create(**params)

    def stream(self, params: dict[str, Any]) -> AbstractContextManager[Any]:
        if self._uses_fallback(params):
            return self._client.beta.messages.stream(  # type: ignore[no-any-return]
                **params, betas=[config.REFUSAL_FALLBACK_BETA], fallbacks="default")
        return self._client.messages.stream(**params)  # type: ignore[no-any-return]

    def create_batch(self, requests: list[dict[str, Any]]) -> str:
        batch = self._client.messages.batches.create(requests=requests)  # type: ignore[arg-type]
        return str(batch.id)

    def batch_status(self, batch_id: str) -> str:
        return str(self._client.messages.batches.retrieve(batch_id).processing_status)

    def batch_results(self, batch_id: str) -> Iterator[Any]:
        yield from self._client.messages.batches.results(batch_id)

    def upload_file(self, filename: str, data: bytes, expires_in_seconds: int) -> str:
        meta = self._client.files.upload(file=(filename, data, "application/pdf"),
                                         expires_in_seconds=expires_in_seconds)
        return str(meta.id)

    def delete_file(self, file_id: str) -> None:
        self._client.files.delete(file_id)


_backend: Backend | None = None


def default_backend() -> Backend:
    global _backend
    if get_settings().ai_mode == "offline":
        raise LlmUnavailable("Mode hors ligne (AI_MODE=offline) : aucun appel à Claude.")
    if _backend is None:
        _backend = AnthropicBackend()
    return _backend


def set_backend(backend: Backend | None) -> None:
    """Injection d'un faux backend (tests et évaluations hors ligne)."""
    global _backend
    _backend = backend


@dataclass
class LlmContext:
    job_id: str | None = None
    company_id: str | None = None
    dossier_id: str | None = None


@dataclass
class LlmResult:
    response: Any
    text: str
    parsed: Any = None
    cost_usd: float = 0.0
    usage: dict[str, int] = field(default_factory=dict)


def _usage(resp: Any) -> dict[str, int]:
    u = getattr(resp, "usage", None)
    return {
        "input_tokens": int(getattr(u, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(u, "output_tokens", 0) or 0),
        "cache_read_tokens": int(getattr(u, "cache_read_input_tokens", 0) or 0),
        "cache_creation_tokens": int(getattr(u, "cache_creation_input_tokens", 0) or 0),
    }


def text_of(resp: Any) -> str:
    return "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, anthropic.APIConnectionError | anthropic.RateLimitError | anthropic.InternalServerError):
        return True
    return isinstance(exc, anthropic.APIStatusError) and exc.status_code in (408, 409, 429, 500, 502, 503, 504, 529)


def _retry_after(exc: Exception) -> float | None:
    resp = getattr(exc, "response", None)
    try:
        return float(resp.headers.get("retry-after")) if resp is not None else None
    except (TypeError, ValueError):
        return None


class LlmClient:
    def __init__(self, ctx: LlmContext | None = None, backend: Backend | None = None) -> None:
        self.ctx = ctx or LlmContext()
        self._backend = backend

    @property
    def backend(self) -> Backend:
        if self._backend is None:
            self._backend = default_backend()
        return self._backend

    # ---------- budgets ----------
    def spent(self) -> tuple[float, float]:
        with get_sessionmaker()() as db:
            dossier = 0.0
            if self.ctx.dossier_id:
                dossier = float(db.scalar(select(func.coalesce(func.sum(LlmCall.cost_usd), 0.0))
                                          .where(LlmCall.dossier_id == self.ctx.dossier_id)) or 0.0)
            month = 0.0
            if self.ctx.company_id:
                start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                month = float(db.scalar(select(func.coalesce(func.sum(LlmCall.cost_usd), 0.0)).where(
                    LlmCall.company_id == self.ctx.company_id, LlmCall.created_at >= start)) or 0.0)
        return dossier, month

    def check_budget(self) -> None:
        s = get_settings()
        dossier, month = self.spent()
        if self.ctx.dossier_id and dossier >= s.budget_per_dossier_usd:
            raise BudgetExceeded(f"Budget du dossier atteint ({dossier:.2f} $ US).")
        if self.ctx.company_id and month >= s.budget_monthly_company_usd:
            raise BudgetExceeded(f"Budget mensuel d'analyse atteint ({month:.2f} $ US).")

    def _log(self, step: str, model: str, usage: dict[str, int], latency_ms: int, stop_reason: str | None,
             error: str | None = None, batch: bool = False) -> float:
        cost = config.cost_usd(model, usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                               usage.get("cache_read_tokens", 0), usage.get("cache_creation_tokens", 0), batch)
        with get_sessionmaker()() as db:
            db.add(LlmCall(job_id=self.ctx.job_id, company_id=self.ctx.company_id, dossier_id=self.ctx.dossier_id,
                           step=step, model=model, cost_usd=cost, latency_ms=latency_ms,
                           stop_reason=stop_reason, error=error, **usage))
            db.commit()
        log.info("llm_call", extra={"step": step, "model": model, "cost_usd": cost, "latency_ms": latency_ms,
                                    "stop_reason": stop_reason, "job_id": self.ctx.job_id,
                                    "dossier_id": self.ctx.dossier_id, **usage})
        return cost

    # ---------- appels ----------
    def build_params(self, role: str, system: str | list[dict[str, Any]], messages: list[dict[str, Any]],
                     tools: list[dict[str, Any]] | None = None, output: type[BaseModel] | None = None,
                     max_tokens: int | None = None) -> dict[str, Any]:
        r = config.ROLES[role]
        output_config: dict[str, Any] = {"effort": r.effort}
        if output is not None:
            if any(_has_citations(m) for m in messages):
                raise LlmError("Citations et sorties structurées sont incompatibles dans une même requête.")
            output_config["format"] = {"type": "json_schema", "schema": strict_schema(output)}
        params: dict[str, Any] = {
            "model": r.model, "max_tokens": max_tokens or r.max_tokens, "system": system,
            "messages": messages, "output_config": output_config,
        }
        if tools:
            params["tools"] = tools
        return params

    def call(self, step: str, role: str, system: str | list[dict[str, Any]], messages: list[dict[str, Any]],
             tools: list[dict[str, Any]] | None = None, output: type[T] | None = None,
             max_tokens: int | None = None) -> LlmResult:
        self.check_budget()
        params = self.build_params(role, system, messages, tools, output, max_tokens)
        resp = self._with_retries(step, params)
        return self._finish(step, params, resp, output)

    def structured(self, step: str, role: str, system: str | list[dict[str, Any]],
                   messages: list[dict[str, Any]], output: type[T], max_tokens: int | None = None) -> T:
        result = self.call(step, role, system, messages, output=output, max_tokens=max_tokens)
        parsed: T = result.parsed
        return parsed

    def _with_retries(self, step: str, params: dict[str, Any]) -> Any:
        delay = config.BACKOFF_BASE_S
        for attempt in range(1, config.MAX_ATTEMPTS + 1):
            started = time.monotonic()
            try:
                resp = self.backend.create(params)
                resp._radarao_latency_ms = int((time.monotonic() - started) * 1000)
                return resp
            except Exception as exc:  # noqa: BLE001 — filtré par _is_retryable
                latency = int((time.monotonic() - started) * 1000)
                self._log(step, params["model"], {}, latency, None, error=f"{type(exc).__name__}: {exc}"[:500])
                if not _is_retryable(exc) or attempt == config.MAX_ATTEMPTS:
                    raise
                wait = _retry_after(exc) or delay * (1 + random.random() * 0.25)
                log.warning("nouvelle tentative LLM", extra={"step": step, "attempt": attempt, "wait_s": wait})
                time.sleep(wait)
                delay *= 2
        raise LlmError("inaccessible")  # pragma: no cover

    def _finish(self, step: str, params: dict[str, Any], resp: Any, output: type[T] | None) -> LlmResult:
        usage = _usage(resp)
        stop = getattr(resp, "stop_reason", None)
        model = str(getattr(resp, "model", params["model"]) or params["model"])
        cost = self._log(step, model, usage, getattr(resp, "_radarao_latency_ms", 0), stop)
        if stop == "refusal":
            raise LlmRefusal("Le modèle a refusé la requête.")
        text = text_of(resp)
        parsed = None
        if output is not None:
            if stop == "max_tokens":
                raise LlmOutputError("Sortie structurée tronquée (max_tokens).")
            try:
                parsed = output.model_validate(json.loads(text))
            except (json.JSONDecodeError, ValidationError) as exc:
                raise LlmOutputError(f"Sortie non conforme au schéma : {exc}"[:800]) from exc
        return LlmResult(response=resp, text=text, parsed=parsed, cost_usd=cost, usage=usage)

    def stream(self, step: str, role: str, system: str | list[dict[str, Any]], messages: list[dict[str, Any]],
               tools: list[dict[str, Any]] | None = None) -> Iterator[tuple[str, Any]]:
        """Diffuse ('text', delta) puis ('final', message). Utilisé par l'assistant (SSE)."""
        self.check_budget()
        params = self.build_params(role, system, messages, tools)
        started = time.monotonic()
        try:
            with self.backend.stream(params) as s:
                for event in s:
                    if getattr(event, "type", "") == "content_block_delta" and getattr(
                            event.delta, "type", "") == "text_delta":
                        yield ("text", event.delta.text)
                final = s.get_final_message()
        except Exception as exc:
            self._log(step, params["model"], {}, int((time.monotonic() - started) * 1000), None,
                      error=f"{type(exc).__name__}: {exc}"[:500])
            raise
        final._radarao_latency_ms = int((time.monotonic() - started) * 1000)
        self._finish(step, params, final, None)
        yield ("final", final)

    # ---------- lots (API Message Batches, -50 %) ----------
    def submit_batch(self, role: str, items: list[tuple[str, str, list[dict[str, Any]]]],
                     output: type[BaseModel]) -> str:
        self.check_budget()
        requests = [{"custom_id": cid, "params": self.build_params(role, system, msgs, output=output)}
                    for cid, system, msgs in items]
        return self.backend.create_batch(requests)

    def batch_done(self, batch_id: str) -> bool:
        return self.backend.batch_status(batch_id) == "ended"

    def collect_batch(self, step: str, batch_id: str, output: type[T]) -> dict[str, T | None]:
        results: dict[str, T | None] = {}
        for item in self.backend.batch_results(batch_id):
            res = item.result
            if res.type != "succeeded":
                results[item.custom_id] = None
                continue
            msg = res.message
            self._log(step, str(msg.model), _usage(msg), 0, msg.stop_reason, batch=True)
            try:
                results[item.custom_id] = output.model_validate(json.loads(text_of(msg)))
            except (json.JSONDecodeError, ValidationError):
                results[item.custom_id] = None
        return results


def _has_citations(message: dict[str, Any]) -> bool:
    content = message.get("content")
    if not isinstance(content, list):
        return False
    for block in content:
        if isinstance(block, dict):
            if block.get("citations", {}).get("enabled"):
                return True
            if block.get("type") == "tool_result" and isinstance(block.get("content"), list) and any(
                    isinstance(b, dict) and b.get("citations", {}).get("enabled") for b in block["content"]):
                return True
    return False


def files_backend() -> Any:
    """Backend offrant upload_file / delete_file (Files API), ou None s'il n'y en a pas."""
    try:
        b = default_backend()
    except LlmUnavailable:
        return None
    return b if hasattr(b, "upload_file") else None
