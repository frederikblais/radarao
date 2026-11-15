"""Client Databricks minimal : Statement Execution API (SQL) et Files API (Volumes Unity Catalog).

Aucune donnée personnelle n'est envoyée au lakehouse : seulement les données ouvertes du SEAO.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from api.app.config import get_settings


class LakehouseError(RuntimeError):
    pass


@dataclass
class LakehouseConfig:
    host: str
    token: str
    warehouse_id: str
    catalog: str
    schema: str
    volume: str

    @classmethod
    def from_settings(cls) -> LakehouseConfig | None:
        s = get_settings()
        if not (s.databricks_host and s.databricks_token and s.databricks_warehouse_id):
            return None
        host = s.databricks_host.removeprefix("https://").rstrip("/")
        return cls(
            host,
            s.databricks_token,
            s.databricks_warehouse_id,
            s.databricks_catalog,
            s.databricks_schema,
            s.databricks_volume,
        )

    @property
    def volume_path(self) -> str:
        return f"/Volumes/{self.catalog}/{self.schema}/{self.volume}"

    def fq(self, table: str) -> str:
        return f"`{self.catalog}`.`{self.schema}`.`{table}`"


class Lakehouse:
    def __init__(self, cfg: LakehouseConfig, http: httpx.Client | None = None) -> None:
        self.cfg = cfg
        self.http = http or httpx.Client(
            base_url=f"https://{cfg.host}", timeout=120, headers={"Authorization": f"Bearer {cfg.token}"}
        )

    # ---------- SQL ----------
    def sql(self, statement: str, params: dict[str, Any] | None = None, timeout_s: int = 900) -> list[dict[str, Any]]:
        body: dict[str, Any] = {
            "warehouse_id": self.cfg.warehouse_id,
            "statement": statement,
            "wait_timeout": "30s",
            "on_wait_timeout": "CONTINUE",
            "catalog": self.cfg.catalog,
            "schema": self.cfg.schema,
            "format": "JSON_ARRAY",
            "disposition": "INLINE",
        }
        if params:
            body["parameters"] = [{"name": k, "value": None if v is None else str(v)} for k, v in params.items()]
        r = self.http.post("/api/2.0/sql/statements", json=body)
        self._raise(r)
        data = r.json()
        deadline = time.monotonic() + timeout_s
        # L'entrepôt serverless peut démarrer à froid : on attend sans bloquer le reste.
        while data["status"]["state"] in ("PENDING", "RUNNING"):
            if time.monotonic() > deadline:
                self.http.post(f"/api/2.0/sql/statements/{data['statement_id']}/cancel")
                raise LakehouseError("Délai dépassé pour la requête SQL Databricks.")
            time.sleep(2)
            r = self.http.get(f"/api/2.0/sql/statements/{data['statement_id']}")
            self._raise(r)
            data = r.json()
        if data["status"]["state"] != "SUCCEEDED":
            err = data["status"].get("error", {})
            raise LakehouseError(f"SQL Databricks : {err.get('error_code')} {err.get('message', '')}"[:800])
        cols = [c["name"] for c in (data.get("manifest", {}).get("schema", {}).get("columns") or [])]
        rows: list[dict[str, Any]] = []
        result = data.get("result") or {}
        while True:
            rows.extend(dict(zip(cols, row, strict=False)) for row in (result.get("data_array") or []))
            link = result.get("next_chunk_internal_link")
            if not link:
                break
            r = self.http.get(link)
            self._raise(r)
            result = r.json()
        return rows

    def script(self, sql_text: str) -> None:
        """Exécute un fichier SQL (instructions séparées par « ; » en fin de ligne)."""
        for stmt in split_sql(sql_text):
            self.sql(stmt)

    # ---------- Volumes ----------
    def upload(self, name: str, data: bytes) -> str:
        path = f"{self.cfg.volume_path}/{name}"
        r = self.http.put(
            f"/api/2.0/fs/files{path}",
            params={"overwrite": "true"},
            content=data,
            headers={"Content-Type": "application/octet-stream"},
            timeout=600,
        )
        self._raise(r)
        return path

    @staticmethod
    def _raise(r: httpx.Response) -> None:
        if r.status_code >= 400:
            raise LakehouseError(f"Databricks HTTP {r.status_code} : {r.text[:500]}")


def split_sql(text: str) -> list[str]:
    out, buf = [], []
    for line in text.splitlines():
        if line.strip().startswith("--"):
            continue
        buf.append(line)
        if line.rstrip().endswith(";"):
            stmt = "\n".join(buf).strip().rstrip(";").strip()
            if stmt:
                out.append(stmt)
            buf = []
    tail = "\n".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def render_sql(text: str, cfg: LakehouseConfig) -> str:
    return (
        text.replace("${catalog}", cfg.catalog)
        .replace("${schema}", cfg.schema)
        .replace("${volume_path}", cfg.volume_path)
    )
