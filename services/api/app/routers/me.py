from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from api.app.db import get_db
from api.app.models import AuthSession, Company, Device, Dossier, User
from api.app.schemas.api import DeviceIn, MeOut, MeUpdate
from api.app.security import current_user

router = APIRouter(tags=["me"])


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(current_user)) -> User:
    return user


@router.patch("/me", response_model=MeOut)
def update_me(body: MeUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> User:
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(user, k, v)
    db.commit()
    return user


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    """Loi 25 : suppression du compte. Si l'utilisateur est seul dans l'entreprise, tout est supprimé."""
    from api.app.services.dossiers import delete_dossier

    company_id = user.company_id
    others = db.scalar(select(User.id).where(User.company_id == company_id, User.id != user.id).limit(1))
    if company_id and not others:
        for d in db.scalars(select(Dossier).where(Dossier.company_id == company_id)).all():
            delete_dossier(db, d)
        c = db.get(Company, company_id)
        if c:
            db.delete(c)
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    db.delete(user)
    db.commit()


@router.post("/devices", status_code=status.HTTP_201_CREATED)
def register_device(
    body: DeviceIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict[str, str]:
    existing = db.scalar(select(Device).where(Device.token == body.token))
    if existing:
        existing.user_id, existing.platform = user.id, body.platform
    else:
        db.add(Device(user_id=user.id, platform=body.platform, token=body.token))
    db.commit()
    return {"status": "ok"}
