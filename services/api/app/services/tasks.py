"""Mise en file des tâches asynchrones, sans dépendance de l'API envers le code du worker."""

from __future__ import annotations

import logging
import threading
from typing import Any

from api.app.config import get_settings

log = logging.getLogger("radarao.api.tasks")
QUEUES = {"worker.tasks.analyze_dossier": "analysis"}
sent: list[tuple[str, tuple[Any, ...]]] = []  # trace (tests)


def enqueue(name: str, *args: Any, **kwargs: Any) -> None:
    mode = get_settings().task_mode
    sent.append((name, args))
    if mode == "none":
        return
    if mode == "inline":
        from worker import tasks

        fn = getattr(tasks, name.rsplit(".", 1)[-1])
        threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True).start()
        return
    from worker.celery_app import app

    app.send_task(name, args=args, kwargs=kwargs, queue=QUEUES.get(name, "default"))
