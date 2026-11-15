"""Authentification (lien magique, sessions côté API) et contrôle d'accès."""

from __future__ import annotations

import hashlib
import secrets
import time
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from api.app.config import get_settings
from api.app.db import get_db
from api.app.models import AuthSession, Company, Dossier, User

COOKIE = "radarao_session"
SESSION_DAYS = 30
MAGIC_MINUTES = 15


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def create_session(db: Session, user: User) -> str:
    token = new_token()
    db.add(
        AuthSession(
            token_hash=hash_token(token), user_id=user.id, expires_at=datetime.now(UTC) + timedelta(days=SESSION_DAYS)
        )
    )
    db.commit()
    return token


def _token_from(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()  # clients iOS / macOS (phase 2)
    return request.cookies.get(COOKIE)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = _token_from(request)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Connexion requise.")
    sess = db.get(AuthSession, hash_token(token))
    if sess is None or sess.expires_at < datetime.now(UTC):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expirée.")
    user = db.get(User, sess.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Utilisateur introuvable.")
    request.state.user_id = user.id
    return user


def current_company(user: User = Depends(current_user), db: Session = Depends(get_db)) -> Company:
    if not user.company_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Profil d'entreprise à créer (accueil).")
    company = db.get(Company, user.company_id)
    if company is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Profil d'entreprise introuvable.")
    return company


def own_company(company_id: str, company: Company = Depends(current_company)) -> Company:
    """Un company_id venant du client n'est jamais utilisé sans vérification d'appartenance."""
    if company_id != company.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entreprise introuvable.")
    return company


def own_dossier(dossier_id: str, company: Company = Depends(current_company), db: Session = Depends(get_db)) -> Dossier:
    d = db.get(Dossier, dossier_id)
    if d is None or d.company_id != company.id:  # 404 plutôt que 403 : on ne révèle pas l'existence
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dossier introuvable.")
    return d


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Réservé à l'administration.")
    return user


# ---------- limites de débit ----------
_memory: dict[str, list[float]] = {}


def rate_limit(bucket: str, limit_per_hour_attr: str):  # type: ignore[no-untyped-def]
    def dep(user: User = Depends(current_user)) -> None:
        limit = int(getattr(get_settings(), limit_per_hour_attr))
        key = f"rl:{bucket}:{user.id}:{int(time.time() // 3600)}"
        try:
            import redis

            r = redis.Redis.from_url(get_settings().redis_url, socket_timeout=0.5)
            n = r.incr(key)
            if n == 1:
                r.expire(key, 3700)
        except Exception:  # noqa: BLE001 — repli en mémoire si Redis est indisponible
            hits = [t for t in _memory.get(key, []) if t > time.time() - 3600] + [time.time()]
            _memory[key] = hits
            n = len(hits)
        if int(n) > limit:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS, "Limite atteinte pour cette heure. Réessayez plus tard."
            )

    return dep
