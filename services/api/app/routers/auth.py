from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.app.config import get_settings
from api.app.db import get_db
from api.app.models import AuthSession, MagicLinkToken, User
from api.app.schemas.api import MagicLinkIn, SessionOut, VerifyIn
from api.app.security import COOKIE, MAGIC_MINUTES, SESSION_DAYS, create_session, hash_token, new_token

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        COOKIE,
        token,
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=s.env != "dev" and s.env != "test",
        path="/",
    )


@router.post("/magic-link", status_code=status.HTTP_202_ACCEPTED)
def magic_link(body: MagicLinkIn, db: Session = Depends(get_db)) -> dict[str, str]:
    from worker.notifications import email

    token = new_token()
    db.add(
        MagicLinkToken(
            token_hash=hash_token(token),
            email=body.email.lower(),
            expires_at=datetime.now(UTC) + timedelta(minutes=MAGIC_MINUTES),
        )
    )
    db.commit()
    link = f"{get_settings().web_base_url}/connexion/verifier?token={token}"
    email.magic_link(body.email, link)
    # Réponse identique que le compte existe ou non (pas d'énumération des courriels).
    return {"message": "Si l'adresse est valide, un lien de connexion vient d'être envoyé."}


@router.post("/verify", response_model=SessionOut)
def verify(body: VerifyIn, response: Response, db: Session = Depends(get_db)) -> SessionOut:
    t = db.get(MagicLinkToken, hash_token(body.token))
    if t is None or t.used_at is not None or t.expires_at < datetime.now(UTC):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Lien invalide ou expiré.")
    t.used_at = datetime.now(UTC)
    user = _get_or_create(db, t.email)
    token = create_session(db, user)
    _set_cookie(response, token)
    return SessionOut(token=token, user_id=user.id, has_company=user.company_id is not None)


def _get_or_create(db: Session, email: str) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email)
        db.add(user)
        db.commit()
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> None:
    token = request.cookies.get(COOKIE)
    if token:
        sess = db.get(AuthSession, hash_token(token))
        if sess:
            db.delete(sess)
            db.commit()
    response.delete_cookie(COOKIE, path="/")


# ---------- Google (OAuth 2.0, flux « code ») ----------
_GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"


@router.get("/google/start")
def google_start() -> RedirectResponse:
    s = get_settings()
    if not s.google_client_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connexion Google non configurée.")
    state = secrets.token_urlsafe(16)
    params = {
        "client_id": s.google_client_id,
        "redirect_uri": f"{s.api_base_url}/auth/google/callback",
        "response_type": "code",
        "scope": "openid email",
        "state": state,
        "prompt": "select_account",
    }
    resp = RedirectResponse(f"{_GOOGLE_AUTH}?{urlencode(params)}")
    resp.set_cookie("oauth_state", state, max_age=600, httponly=True, samesite="lax")
    return resp


@router.get("/google/callback")
def google_callback(code: str, state: str, request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    s = get_settings()
    if not s.google_client_id or state != request.cookies.get("oauth_state"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "État OAuth invalide.")
    tok = httpx.post(
        _GOOGLE_TOKEN,
        data={
            "code": code,
            "client_id": s.google_client_id,
            "client_secret": s.google_client_secret,
            "redirect_uri": f"{s.api_base_url}/auth/google/callback",
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    tok.raise_for_status()
    info = httpx.get(_GOOGLE_USERINFO, headers={"Authorization": f"Bearer {tok.json()['access_token']}"}, timeout=15)
    info.raise_for_status()
    data = info.json()
    if not data.get("email_verified"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Courriel Google non vérifié.")
    user = _get_or_create(db, str(data["email"]).lower())
    resp = RedirectResponse(f"{s.web_base_url}/opportunites" if user.company_id else f"{s.web_base_url}/accueil")
    _set_cookie(resp, create_session(db, user))
    return resp
