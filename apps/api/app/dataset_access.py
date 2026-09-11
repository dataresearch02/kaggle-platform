"""Dataset privacy with legacy public data preserved."""

from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, or_
from sqlalchemy.orm import Session
from .auth import current_user
from .db import get_db
from .models import Dataset, DatasetAccess, DatasetShare, User

router = APIRouter(prefix="/api/datasets", tags=["Dataset access"])


def visibility(db, id):
    access = db.get(DatasetAccess, id)
    return access.visibility if access else "public"


def visible_datasets(user):
    private = select(DatasetAccess.dataset_id).where(
        DatasetAccess.visibility == "private"
    )
    uid = user.id if user else -1
    return or_(
        Dataset.id.not_in(private),
        Dataset.owner_id == uid,
        Dataset.id.in_(
            select(DatasetShare.dataset_id).where(DatasetShare.user_id == uid)
        ),
    )


def readable(db, id, user):
    row = db.scalar(select(Dataset).where(Dataset.id == id, visible_datasets(user)))
    if not row:
        raise HTTPException(404, "Dataset not found")
    return row


def owner(db, id, user):
    row = db.scalar(select(Dataset).where(Dataset.id == id).with_for_update())
    if not row or row.owner_id != user.id:
        raise HTTPException(404, "Your dataset was not found")
    return row


class AccessInput(BaseModel):
    visibility: Literal["private", "public"]


@router.get("/{id}/access")
def access(id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    owner(db, id, user)
    return {
        "visibility": visibility(db, id),
        "shares": [
            {"id": row.id, "username": row.username}
            for row in db.scalars(
                select(User)
                .join(DatasetShare, User.id == DatasetShare.user_id)
                .where(DatasetShare.dataset_id == id)
            )
        ],
    }


@router.put("/{id}/access")
def change_access(
    id: int,
    data: AccessInput,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    owner(db, id, user)
    row = db.get(DatasetAccess, id)
    if not row:
        row = DatasetAccess(dataset_id=id)
        db.add(row)
    row.visibility = data.visibility
    db.commit()
    return {"visibility": row.visibility}


class ShareInput(BaseModel):
    username: str


@router.post("/{id}/shares", status_code=201)
def share(
    id: int, data: ShareInput, user=Depends(current_user), db: Session = Depends(get_db)
):
    owner(db, id, user)
    recipient = db.scalar(
        select(User).where(User.username == data.username.strip().lower())
    )
    if not recipient or recipient.id == user.id:
        raise HTTPException(422, "Choose another registered user")
    if not db.get(DatasetShare, (id, recipient.id)):
        db.add(DatasetShare(dataset_id=id, user_id=recipient.id))
    db.commit()
    return {"shared": True}


@router.delete("/{id}/shares/{user_id}", status_code=204)
def revoke(
    id: int, user_id: int, user=Depends(current_user), db: Session = Depends(get_db)
):
    owner(db, id, user)
    row = db.get(DatasetShare, (id, user_id))
    if row:
        db.delete(row)
        db.commit()
