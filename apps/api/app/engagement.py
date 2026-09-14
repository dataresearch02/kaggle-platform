"""Persistent replies and per-user reactions for community conversations."""

from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from .auth import current_user
from .code_pages import optional_user
from .community import add_mentions, require_open_topic, save_revision, scope_visible
from .db import get_db
from .permissions import can_manage, can_view, not_hidden
from .models import (
    NotebookComment,
    CompetitionPost,
    ContentReply,
    ContentReaction,
    now,
)

router = APIRouter(prefix="/api/engagement", tags=["Replies and reactions"])
Kind = Literal[
    "notebook-comment",
    "discussion-comment",
    "discussion",
    "competition-post",
    "competition-comment",
]
# Legacy discussions became General forum topics (migration 0009), so their
# kinds are aliases for topic and topic-comment conversations.
ALIASES = {
    "discussion": "competition-post",
    "discussion-comment": "competition-comment",
}
Reaction = Literal["like", "helpful", "celebrate"]
TARGETS = {
    "notebook-comment": NotebookComment,
    "competition-post": CompetitionPost,
    "competition-comment": ContentReply,
}


def canonical(kind):
    return ALIASES.get(kind, kind)


def require_target(db, kind, id, user=None):
    kind = canonical(kind)
    if kind == "competition-comment":
        parent = db.get(ContentReply, id)
        if not parent or parent.target_kind != "competition-post":
            raise HTTPException(404, "Comment not found")
        require_target(db, "competition-post", parent.target_id, user)
    # Serialize writes on the parent to keep reaction toggles idempotent.
    row = db.scalar(
        select(TARGETS[kind]).where(TARGETS[kind].id == id).with_for_update()
    )
    if row is None or (hasattr(row, "hidden") and not can_view(row, user)):
        raise HTTPException(404, "Conversation not found")
    if kind == "notebook-comment":
        from .notebook_visibility import require_visible

        require_visible(db, row.notebook_id, user)
    if kind == "competition-post" and not scope_visible(
        db, row.scope, row.scope_id, user
    ):
        raise HTTPException(404, "Conversation not found")
    return row


def require_writable(db, kind, row):
    """New replies and reactions need a live target in an open topic."""
    if row.deleted_at:
        raise HTTPException(409, "This conversation was deleted")
    if kind == "competition-post":
        require_open_topic(db, row)
    elif kind == "competition-comment":
        require_open_topic(db, db.get(CompetitionPost, row.target_id))


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
        "edited_at": row.edited_at,
        "deleted": bool(row.deleted_at),
        "hidden": bool(row.hidden),
        "hidden_reason": row.hidden_reason,
    }


def enrich(db, items, user, vote_kind="reply"):
    """Add votes, the viewer's vote, author tier badges and existing @mentions."""
    from .progression import tier_name, tiers_for
    from .votes import vote_states

    states = vote_states(db, vote_kind, [item["id"] for item in items], user)
    tiers = tiers_for(db, [item["owner_id"] for item in items], user)
    for item in items:
        item.update(states[item["id"]], owner_tier=tier_name(tiers, item["owner_id"]))
    return add_mentions(db, items)


@router.get("/{kind}/{id}")
def read(
    kind: Kind,
    id: int,
    after: int = Query(0, ge=0),
    user=Depends(optional_user),
    db: Session = Depends(get_db),
):
    from .models import User

    kind = canonical(kind)
    require_target(db, kind, id, user)
    rows = db.execute(
        select(ContentReply, User.username)
        .join(User, User.id == ContentReply.owner_id)
        .where(
            ContentReply.target_kind == kind,
            ContentReply.target_id == id,
            ContentReply.id > after,
            not_hidden(ContentReply, user),
        )
        .order_by(ContentReply.id)
        .limit(51)
    ).all()
    return {
        "reactions": reaction_summary(db, kind, id, user),
        "replies": enrich(
            db, [reply_json(row, username) for row, username in rows[:50]], user
        ),
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
    kind = canonical(kind)
    target = require_target(db, kind, id, user)
    require_writable(db, kind, target)
    if kind == "notebook-comment":
        from .models import NotebookSettings

        settings = db.get(NotebookSettings, target.notebook_id)
        if settings and not settings.allow_comments:
            raise HTTPException(403, "Comments are disabled for this notebook")
    if not data.body.strip():
        raise HTTPException(422, "Write a reply first")
    row = ContentReply(
        target_kind=kind, target_id=id, owner_id=user.id, body=data.body.strip()
    )
    db.add(row)
    db.flush()
    from .notifications import content_created
    from .progression import mark_dirty

    content_created(db, user, "reply", row)
    mark_dirty(db, user.id)
    db.commit()
    return enrich(db, [reply_json(row, user.username)], user)[0]


def owned_reply(db, kind, id, reply_id, user, action):
    require_target(db, kind, id, user)
    row = db.get(ContentReply, reply_id)
    if not row or row.target_kind != kind or row.target_id != id:
        raise HTTPException(404, "Reply not found")
    if not can_manage(user, row.owner_id):
        raise HTTPException(403, f"You can only {action} your own replies")
    return row


@router.put("/{kind}/{id}/replies/{reply_id}")
def edit_reply(
    kind: Kind,
    id: int,
    reply_id: int,
    data: ReplyInput,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    """Authors edit their comments and replies; the previous text is kept."""
    from .models import User

    kind = canonical(kind)
    row = owned_reply(db, kind, id, reply_id, user, "edit")
    if row.deleted_at:
        raise HTTPException(409, "This reply was deleted")
    body = data.body.strip()
    if not body:
        raise HTTPException(422, "Write a reply first")
    if body != row.body:
        save_revision(db, "reply", row, user)
        previous = row.body
        row.body, row.edited_at = body, now()
        if row.owner_id != user.id:
            from .moderation import record

            record(
                db, user, "content.update", "reply", row.id, {"owner_id": row.owner_id}
            )
        from .notifications import content_edited

        content_edited(db, user, "reply", row, previous)
        db.commit()
    owner = db.get(User, row.owner_id)
    return enrich(
        db, [reply_json(row, owner.username if owner else "Deleted user")], user
    )[0]


@router.delete("/{kind}/{id}/replies/{reply_id}", status_code=204)
def remove_reply(
    kind: Kind,
    id: int,
    reply_id: int,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    """A comment that has replies stays as a "deleted" placeholder."""
    from .progression import mark_related
    from .votes import remove_votes

    kind = canonical(kind)
    row = owned_reply(db, kind, id, reply_id, user, "delete")
    mark_related(db, "reply", row.id)
    has_replies = kind == "competition-post" and db.scalar(
        select(ContentReply.id).where(
            ContentReply.target_kind == "competition-comment",
            ContentReply.target_id == row.id,
        )
    )
    if has_replies:
        if not row.deleted_at:
            save_revision(db, "reply", row, user)
            row.body, row.deleted_at = "", now()
            remove_votes(db, "reply", [row.id])
    else:
        if kind == "competition-post":
            remove_engagement(db, "competition-comment", [row.id])
        remove_votes(db, "reply", [row.id])
        db.delete(row)
    db.commit()
    return Response(status_code=204)


@router.put("/{kind}/{id}/reactions/{reaction}")
def react(
    kind: Kind,
    id: int,
    reaction: Reaction,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    kind = canonical(kind)
    target = require_target(db, kind, id, user)
    if target.deleted_at:
        raise HTTPException(409, "This conversation was deleted")
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
    kind = canonical(kind)
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
    """Delete replies, reactions, votes and topic settings under removed items."""
    from .votes import remove_votes

    kind = canonical(kind)
    if not isinstance(ids, list):
        ids = list(db.scalars(ids))
    if kind == "competition-post":
        comment_ids = list(
            db.scalars(
                select(ContentReply.id).where(
                    ContentReply.target_kind == kind, ContentReply.target_id.in_(ids)
                )
            )
        )
        remove_engagement(db, "competition-comment", comment_ids)
        from .models import (
            CompetitionTopicSettings,
            CompetitionTopicBookmark,
            TopicWatch,
        )

        for model in (CompetitionTopicSettings, CompetitionTopicBookmark, TopicWatch):
            db.execute(delete(model).where(model.post_id.in_(ids)))
        remove_votes(db, "competition-post", ids)
    elif kind == "competition-comment":
        remove_votes(db, "reply", ids)
    elif kind == "notebook-comment":
        remove_votes(db, "notebook-comment", ids)
    remove_votes(
        db,
        "reply",
        select(ContentReply.id).where(
            ContentReply.target_kind == kind, ContentReply.target_id.in_(ids)
        ),
    )
    for model in (ContentReply, ContentReaction):
        db.execute(
            delete(model).where(model.target_kind == kind, model.target_id.in_(ids))
        )
