"""Upvotes: one per user on notebooks, datasets, models, topics, comments and replies."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from .auth import current_user
from .code_pages import optional_user
from .community import target_row
from .db import get_db
from .models import Vote, now

router = APIRouter(prefix="/api/votes", tags=["Votes"])

# The same kind names as reports: "reply" is any topic comment or nested reply.
VoteKind = Literal[
    "code", "dataset", "model", "competition-post", "reply", "notebook-comment"
]


def vote_count(kind, id_column):
    """Correlated count of votes for a list query."""
    return (
        select(func.count(Vote.id))
        .where(Vote.target_kind == kind, Vote.target_id == id_column)
        .scalar_subquery()
    )


def vote_states(db, kind, ids, user):
    """{id: {"votes": n, "voted": bool}} for a page of items."""
    ids = list(ids)
    states = {id: {"votes": 0, "voted": False} for id in ids}
    if not ids:
        return states
    for target_id, total in db.execute(
        select(Vote.target_id, func.count(Vote.id))
        .where(Vote.target_kind == kind, Vote.target_id.in_(ids))
        .group_by(Vote.target_id)
    ):
        states[target_id]["votes"] = total
    if user:
        for target_id in db.scalars(
            select(Vote.target_id).where(
                Vote.target_kind == kind,
                Vote.target_id.in_(ids),
                Vote.user_id == user.id,
            )
        ):
            states[target_id]["voted"] = True
    return states


def summary(db, kind, id, user):
    return vote_states(db, kind, [id], user)[id]


def remove_votes(db, kind, ids):
    """Delete votes on removed items (ids may be a list or a select)."""
    db.execute(delete(Vote).where(Vote.target_kind == kind, Vote.target_id.in_(ids)))


def require_votable(db, kind, id, user):
    row = target_row(db, kind, id, user)
    if row is None:
        raise HTTPException(404, "Content not found")
    if getattr(row, "deleted_at", None):
        raise HTTPException(409, "Deleted content cannot be voted on")
    return row


@router.get("/{kind}/{id}")
def read_votes(
    kind: VoteKind, id: int, user=Depends(optional_user), db=Depends(get_db)
):
    if target_row(db, kind, id, user) is None:
        raise HTTPException(404, "Content not found")
    return summary(db, kind, id, user)


@router.put("/{kind}/{id}")
def upvote(kind: VoteKind, id: int, user=Depends(current_user), db=Depends(get_db)):
    row = require_votable(db, kind, id, user)
    if row.owner_id == user.id:
        raise HTTPException(422, "You cannot vote on your own content")
    # Lock the voter so repeated requests stay idempotent on PostgreSQL.
    db.refresh(user, with_for_update=True)
    existing = db.scalar(
        select(Vote.id).where(
            Vote.target_kind == kind, Vote.target_id == id, Vote.user_id == user.id
        )
    )
    if not existing:
        db.add(Vote(target_kind=kind, target_id=id, user_id=user.id, created_at=now()))
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return summary(db, kind, id, user)
        from .notifications import notify
        from .progression import mark_dirty

        notify(
            db,
            row.owner_id,
            "vote",
            actor=user,
            target_kind=kind,
            target_id=id,
            # One notification per item per day, counting the voters.
            group_key=f"vote:{kind}:{id}:{now()[:10]}",
        )
        mark_dirty(db, row.owner_id)
    db.commit()
    return summary(db, kind, id, user)


@router.delete("/{kind}/{id}")
def remove_upvote(
    kind: VoteKind, id: int, user=Depends(current_user), db=Depends(get_db)
):
    row = target_row(db, kind, id, user)
    if row is None:
        raise HTTPException(404, "Content not found")
    removed = db.execute(
        delete(Vote).where(
            Vote.target_kind == kind, Vote.target_id == id, Vote.user_id == user.id
        )
    ).rowcount
    if removed:
        from .progression import mark_dirty

        mark_dirty(db, row.owner_id)
    db.commit()
    return summary(db, kind, id, user)
