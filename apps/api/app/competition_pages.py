"""Competition page resources, public data previews and scoped discussions."""

import csv
import io
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .notebook_visibility import published_code, visible_notebooks
from .auth import current_user
from .code_pages import optional_user
from .pagination import Page, count, page, set_total, window
from .permissions import not_hidden
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
    """The signed-in user's entry: rules, timeline, daily limit and final selection."""
    from .competition_policy import (
        can_host,
        entry_for,
        needs_rules,
        submissions_today,
        timeline,
    )
    from .competition_results import finalize_if_due
    from .models import Submission
    from .team_scoring import owner_filter

    competition = require_competition(db, id)
    finalize_if_due(db, competition)
    entry = entry_for(db, id, user)
    used, team_id = submissions_today(db, competition, user)
    return {
        "joined": entry is not None,
        "rules_revision": competition.rules_revision,
        "accepted_rules_revision": entry.rules_revision if entry else None,
        "rules_accepted_at": entry.rules_accepted_at if entry else None,
        "needs_rules_acceptance": needs_rules(competition, entry),
        "team_id": team_id,
        "submissions_today": used,
        "max_daily_submissions": competition.max_daily_submissions,
        "remaining_submissions_today": max(competition.max_daily_submissions - used, 0),
        "max_final_submissions": competition.max_final_submissions,
        "final_selected": db.scalar(
            select(func.count())
            .select_from(Submission)
            .where(
                Submission.competition_id == id,
                Submission.final_selected == 1,
                owner_filter(team_id, user.id),
            )
        ),
        "can_host": can_host(db, competition, user),
        "timeline": timeline(db, competition).json(),
    }


@router.get("/{id}/data")
def data_preview(
    id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    require_competition(db, id)
    from .competition_metadata import require_data_access

    require_data_access(db, id, user)
    from .competition_metadata import test_csv

    content = test_csv(db, id)
    if content is None:
        raise HTTPException(404, "Test data is not available for this competition")
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
            (
                visible_notebooks(None)
                if kind == "notebooks"
                else not_hidden(ModelCard, None)
            ),
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
def posts(
    id: int,
    response: Response,
    pagination: Page = Depends(page),
    user=Depends(optional_user),
    db: Session = Depends(get_db),
):
    require_competition(db, id)
    query = select(CompetitionPost).where(
        CompetitionPost.competition_id == id,
        not_hidden(CompetitionPost, user),
        CompetitionPost.deleted_at.is_(None),
    )
    set_total(response, count(db, query))
    return [
        {**serialize(row), "owner": db.get(User, row.owner_id).username}
        for row in db.scalars(
            window(query.order_by(CompetitionPost.id.desc()), pagination)
        )
    ]


@router.post("/{id}/discussion", status_code=201)
def add_post(
    id: int,
    data: PostInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    from .discussion_feed import create_topic

    require_competition(db, id)
    row = create_topic(db, user, "competition", id, data.title, data.body)
    return {**serialize(row), "owner": user.username}
