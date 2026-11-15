"""Exécute une tâche planifiée directement (CronJobs Kubernetes) : python -m worker.run_task NOM.

Les CronJobs remplacent Celery beat en production : un échec est visible dans Kubernetes
(statut du Job, reprises, historique) au lieu d'être noyé dans les journaux d'un worker.
"""

from __future__ import annotations

import json
import logging
import sys

from api.app.main import configure_logging
from worker import tasks

ALLOWED = {"ingest_latest", "weekly_digest", "purge_expired", "lakehouse_refresh", "match_all", "enrich_tenders"}


def main(argv: list[str]) -> int:
    configure_logging()
    if not argv or argv[0] not in ALLOWED:
        print(f"usage : python -m worker.run_task [{'|'.join(sorted(ALLOWED))}]", file=sys.stderr)
        return 2
    result = getattr(tasks, argv[0])()  # appel direct (synchrone), pas de mise en file
    logging.getLogger("radarao.cron").info("tâche terminée", extra={"task": argv[0], "result": result})
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
