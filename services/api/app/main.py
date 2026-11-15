"""Application FastAPI de RadarAO. La spécification OpenAPI (/openapi.json) génère les clients
TypeScript (web) et Swift (phase 2)."""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from api.app.config import get_settings
from api.app.db import get_engine
from api.app.routers import admin, auth, companies, dossiers, market, me, tenders


class JsonFormatter(logging.Formatter):
    _std = set(vars(logging.LogRecord("", 0, "", 0, "", (), None)))

    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        data.update({k: v for k, v in vars(record).items() if k not in self._std and not k.startswith("_")})
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)


def create_app() -> FastAPI:
    s = get_settings()
    if s.env != "test":
        configure_logging()
    app = FastAPI(
        title="RadarAO API",
        version="0.1.0",
        description="Analyseur d'appels d'offres publics pour les PME québécoises. "
        "Données SEAO : Secrétariat du Conseil du trésor, licence CC-BY 4.0.",
    )
    app.add_middleware(
        CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
    )
    log = logging.getLogger("radarao.api")

    @app.middleware("http")
    async def access_log(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        start = time.monotonic()
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["referrer-policy"] = "same-origin"
        if not request.url.path.startswith("/health"):
            log.info(
                "requête",
                extra={
                    "request_id": rid,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "ms": int((time.monotonic() - start) * 1000),
                    "user_id": getattr(request.state, "user_id", None),
                },
            )
        return response

    @app.get("/health/live", tags=["health"])
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    def ready() -> dict[str, object]:
        from worker.embeddings import Embedder

        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return {
            "status": "ok",
            "ai_mode": s.ai_mode,
            "llm": bool(s.anthropic_api_key) and s.ai_mode != "offline",
            "embeddings": Embedder().mode,
            "lakehouse": bool(s.databricks_host),
        }

    for r in (auth.router, me.router, companies.router, tenders.router, dossiers.router, market.router, admin.router):
        app.include_router(r)
    return app


app = create_app()
