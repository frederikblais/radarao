"""CLI : python -m worker.lakehouse [setup|load FICHIER|refresh|sync|backfill AAAA-MM|local]."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import httpx

from api.app.config import get_settings
from api.app.db import get_sessionmaker
from worker.ingestion.seao import FILE_RE, download
from worker.lakehouse import local
from worker.lakehouse.pipeline import lakehouse, load_file, refresh, setup, sync_to_postgres


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "help"
    if cmd == "local":
        with get_sessionmaker()() as db:
            print(local.compute_local(db))
        return 0
    lh = lakehouse()
    if lh is None:
        print("Databricks non configuré (DATABRICKS_HOST, DATABRICKS_TOKEN, DATABRICKS_WAREHOUSE_ID).")
        return 1
    if cmd == "setup":
        setup(lh)
    elif cmd == "load":
        path = Path(argv[1])
        print(load_file(lh, path.name, json.loads(path.read_text(encoding="utf-8"))))
    elif cmd == "refresh":
        refresh(lh)
    elif cmd == "sync":
        with get_sessionmaker()() as db:
            print(sync_to_postgres(lh, db))
    elif cmd == "backfill":
        # Historique JSON (depuis mars 2021) : fichiers mensuels de Données Québec.
        since = argv[1] if len(argv) > 1 else "2021-03"
        s = get_settings()
        res = httpx.get(f"{s.ckan_api_url}/package_show", params={"id": s.seao_dataset_id}, timeout=30).json()
        monthly = sorted(
            (
                r
                for r in res["result"]["resources"]
                if r.get("name", "").startswith("mensuel_") and FILE_RE.search(r["name"])
            ),
            key=lambda r: r["name"],
        )
        for r in monthly:
            if FILE_RE.search(r["name"]).group(2)[:6] < since.replace("-", ""):  # type: ignore[union-attr]
                continue
            with tempfile.TemporaryDirectory() as tmp:
                p = download(r["url"], Path(tmp) / r["name"])
                print("chargé :", load_file(lh, r["name"], json.loads(p.read_text(encoding="utf-8"))))
        refresh(lh)
        with get_sessionmaker()() as db:
            print(sync_to_postgres(lh, db))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
