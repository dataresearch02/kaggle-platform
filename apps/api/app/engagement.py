"""Persistent replies and per-user reactions for community conversations."""

from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from .auth import current_user
from .code_pages import optional_user
from .db import get_db
from .models import (
    Comment,
    NotebookComment,
    Discussion,
    CompetitionPost,
    ContentReply,
    ContentReaction,
)

router = APIRouter(prefix="/api/engagement", tags=["Replies and reactions"])
Kind = Literal[
    "notebook-comment", "discussion-comment", "discussion", "competition-post"
]
Reaction = Literal["like", "helpful", "celebrate"]
TARGETS = {
    "notebook-comment": NotebookComment,
    "discussion-comment": Comment,
    "discussion": Discussion,
    "competition-post": CompetitionPost,
}


def require_target(db, kind, id, user=None):
    # Serialize writes on the parent to keep reaction toggles idempotent.
    row = db.scalar(
        select(TARGETS[kind]).where(TARGETS[kind].id == id).with_for_update()
    )
    if row is None:
        raise HTTPException(404, "Conversation not found")
    if kind == "notebook-comment":
        from .notebook_visibility import require_visible

        require_visible(db, row.notebook_id, user)
    return row


def reaction_summary(db, kind, id, user):
    rows = db.scalars(
        select(ContentReaction).where(
            ContentReaction.target_kind == kind, ContentReaction.target_id == id
        )
    ).all()
    return [
        {
            "reaction": name,
            "count": sum(row.reaction == name for row in rows),
            "reacted": bool(
                user
                and any(row.user_id == user.id and row.reaction == name for row in rows)
            ),
        }
        for name in ["like", "helpful", "celebrate"]
    ]


def reply_json(row, username):
    return {
        "id": row.id,
        "owner_id": row.owner_id,
        "username": username,
        "body": row.body,
        "created_at": row.created_at,
    }


@router.get("/{kind}/{id}")
def read(
    kind: Kind,
    id: int,
    after: int = Query(0, ge=0),
    user=Depends(optional_user),
    db: Session = Depends(get_db),
):
    from .models import User

    require_target(db, kind, id, user)
    rows = db.execute(
        select(ContentReply, User.username)
        .join(User, User.id == ContentReply.owner_id)
        .where(
            ContentReply.target_kind == kind,
            ContentReply.target_id == id,
            ContentReply.id > after,
        )
        .order_by(ContentReply.id)
        .limit(51)
    ).all()
    return {
        "reactions": reaction_summary(db, kind, id, user),
        "replies": [reply_json(row, username) for row, username in rows[:50]],
        "next_cursor": rows[49][0].id if len(rows) > 50 else None,
    }


class ReplyInput(BaseModel):
    body: str = Field(min_length=1, max_length=10000)


@router.post("/{kind}/{id}/replies", status_code=201)
def reply(
    kind: Kind,
    id: int,
    data: ReplyInput,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    require_target(db, kind, id, user)
    if not data.body.strip():
        raise HTTPException(422, "Write a reply first")
    row = ContentReply(
        target_kind=kind, target_id=id, owner_id=user.id, body=data.body.strip()
    )
    db.add(row)
    db.commit()
    return reply_json(row, user.username)


@router.delete("/{kind}/{id}/replies/{reply_id}", status_code=204)
def remove_reply(
    kind: Kind,
    id: int,
    reply_id: int,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    require_target(db, kind, id, user)
    row = db.get(ContentReply, reply_id)
    if not row or row.target_kind != kind or row.target_id != id:
        raise HTTPException(404, "Reply not found")
    if row.owner_id != user.id:
        raise HTTPException(403, "You can only delete your own replies")
    db.delete(row)
    db.commit()


@router.put("/{kind}/{id}/reactions/{reaction}")
def react(
    kind: Kind,
    id: int,
    reaction: Reaction,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    require_target(db, kind, id, user)
    row = db.scalar(
        select(ContentReaction).where(
            ContentReaction.target_kind == kind,
            ContentReaction.target_id == id,
            ContentReaction.user_id == user.id,
            ContentReaction.reaction == reaction,
        )
    )
    if not row:
        db.add(
            ContentReaction(
                target_kind=kind, target_id=id, user_id=user.id, reaction=reaction
            )
        )
    db.commit()
    return reaction_summary(db, kind, id, user)


@router.delete("/{kind}/{id}/reactions/{reaction}")
def unreact(
    kind: Kind,
    id: int,
    reaction: Reaction,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    require_target(db, kind, id, user)
    db.execute(
        delete(ContentReaction).where(
            ContentReaction.target_kind == kind,
            ContentReaction.target_id == id,
            ContentReaction.user_id == user.id,
            ContentReaction.reaction == reaction,
        )
    )
    db.commit()
    return reaction_summary(db, kind, id, user)


def remove_engagement(db, kind, ids):
    for model in (ContentReply, ContentReaction):
        db.execute(
            delete(model).where(model.target_kind == kind, model.target_id.in_(ids))
        )
