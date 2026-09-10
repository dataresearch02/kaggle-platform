"""Competition page resources, public data previews and scoped discussions."""

import csv
import io
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from .notebook_visibility import published_code, visible_notebooks
from .auth import current_user
from .db import get_db
from .models import (
    Competition,
    ChallengeDetails,
    CompetitionResource,
    CompetitionPost,
    Entry,
    Notebook,
    ModelCard,
    User,
)

router = APIRouter(prefix="/api/competitions", tags=["Competition pages"])


def require_competition(db, id):
    item = db.get(Competition, id)
    if not item:
        raise HTTPException(404, "Competition not found")
    return item


def serialize(item):
    return {
        column.name: getattr(item, column.name) for column in item.__table__.columns
    }


@router.get("/{id}/membership")
def membership(
    id: int, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    require_competition(db, id)
    return {
        "joined": db.scalar(
            select(Entry.id).where(Entry.competition_id == id, Entry.user_id == user.id)
        )
        is not None
    }


@router.get("/{id}/data")
def data_preview(
    id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    require_competition(db, id)
    from .competition_metadata import require_data_access

    require_data_access(db, id, user)
    details = db.get(ChallengeDetails, id)
    content = (
        details.test_csv
        if details
        else "id,temperature,working_day\n7,20,1\n8,10,1\n9,23,0\n"
    )
    reader = csv.DictReader(io.StringIO(content))
    rows = []
    count = 0
    for row in reader:
        count += 1
        if len(rows) < 10:
            rows.append(row)
    return {
        "columns": reader.fieldnames or [],
        "preview": rows,
        "rows": count,
        "bytes": len(content.encode("utf-8")),
    }


@router.get("/{id}/resources/{kind}")
def resources(
    id: int, kind: Literal["notebooks", "models"], db: Session = Depends(get_db)
):
    require_competition(db, id)
    model = Notebook if kind == "notebooks" else ModelCard
    rows = db.scalars(
        select(model)
        .join(CompetitionResource, CompetitionResource.resource_id == model.id)
        .where(
            CompetitionResource.competition_id == id,
            CompetitionResource.kind == kind,
            visible_notebooks(None) if kind == "notebooks" else True,
        )
        .order_by(model.id.desc())
        .limit(100)
    )
    return [
        {
            **serialize(row),
            **({"code": published_code(db, row)} if kind == "notebooks" else {}),
            "owner": db.get(User, row.owner_id).username,
        }
        for row in rows
    ]


@router.post("/{id}/resources/{kind}/{resource_id}", status_code=201)
def link_resource(
    id: int,
    kind: Literal["notebooks", "models"],
    resource_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if kind == "notebooks":
        raise HTTPException(
            409,
            "Use Save & Commit in the notebook editor; competition code is linked only after evaluation",
        )
    # Lock the parent to serialize linking with competition deletion.
    parent = db.scalar(
        select(Competition).where(Competition.id == id).with_for_update()
    )
    if not parent:
        raise HTTPException(404, "Competition not found")
    model = Notebook if kind == "notebooks" else ModelCard
    row = db.scalar(select(model).where(model.id == resource_id).with_for_update())
    if not row or row.owner_id != user.id:
        raise HTTPException(404, "Your resource was not found")
    existing = db.scalar(
        select(CompetitionResource).where(
            CompetitionResource.competition_id == id,
            CompetitionResource.kind == kind,
            CompetitionResource.resource_id == resource_id,
        )
    )
    if not existing:
        db.add(
            CompetitionResource(competition_id=id, kind=kind, resource_id=resource_id)
        )
        db.commit()
    return {"linked": True}


class PostInput(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    body: str = Field(min_length=3, max_length=20000)


@router.get("/{id}/discussion")
def posts(id: int, db: Session = Depends(get_db)):
    require_competition(db, id)
    return [
        {**serialize(row), "owner": db.get(User, row.owner_id).username}
        for row in db.scalars(
            select(CompetitionPost)
            .where(CompetitionPost.competition_id == id)
            .order_by(CompetitionPost.id.desc())
            .limit(100)
        )
    ]


@router.post("/{id}/discussion", status_code=201)
def add_post(
    id: int,
    data: PostInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_competition(db, id)
    if len(data.title.strip()) < 3 or len(data.body.strip()) < 3:
        raise HTTPException(
            422, "Enter a title and a message of at least three characters"
        )
    row = CompetitionPost(competition_id=id, owner_id=user.id, **data.model_dump())
    db.add(row)
    db.commit()
    return {**serialize(row), "owner": user.username}
