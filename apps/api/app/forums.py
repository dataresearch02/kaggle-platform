"""Site forums managed by administrators, and the legacy /api/discussions aliases.

Forum topics are ordinary discussion topics (scope "forum"); see discussion_feed.py.
The legacy Discussion/Comment endpoints are thin aliases for the General forum.
"""

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from .auth import current_user
from .code_pages import optional_user
from .community import can_moderate_topic, require_topic, visible_topics
from .db import get_db
from .migrations import ensure_default_forums
from .models import CompetitionPost, ContentReply, Forum, User
from .pagination import Page, count, page, set_total, window
from .permissions import is_admin, not_hidden, require_admin
from .schemas import CommentInput, DiscussionInput

router = APIRouter(prefix="/api", tags=["Forums"])


def forum_json(db, row, user):
    topics = select(CompetitionPost).where(
        CompetitionPost.scope == "forum",
        CompetitionPost.scope_id == row.id,
        visible_topics(user),
        CompetitionPost.deleted_at.is_(None),
    )
    latest = db.scalar(
        select(func.max(CompetitionPost.created_at)).where(
            CompetitionPost.id.in_(topics.with_only_columns(CompetitionPost.id))
        )
    )
    return {
        "id": row.id,
        "slug": row.slug,
        "title": row.title,
        "description": row.description,
        "position": row.position,
        "archived": bool(row.archived),
        "topic_count": count(db, topics),
        "latest_topic_at": latest,
        "can_post": not row.archived,
        "can_moderate": can_moderate_topic(db, "forum", user, row.id),
    }


def find_forum(db, key):
    row = (
        db.get(Forum, int(key))
        if key.isdigit()
        else db.scalar(select(Forum).where(Forum.slug == key.lower()))
    )
    if not row:
        raise HTTPException(404, "Forum not found")
    return row


@router.get("/forums")
def forums(
    include_archived: bool = False, user=Depends(optional_user), db=Depends(get_db)
):
    """Forums in their administrator-defined order; archived ones on request."""
    query = select(Forum).order_by(Forum.position, Forum.id)
    if not include_archived:
        query = query.where(Forum.archived == 0)
    return [forum_json(db, row, user) for row in db.scalars(query)]


@router.get("/forums/{key}")
def forum(key: str, user=Depends(optional_user), db=Depends(get_db)):
    return forum_json(db, find_forum(db, key), user)


class TopicBody(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    body: str = Field(min_length=3, max_length=20000)


@router.post("/forums/{key}/topics", status_code=201)
def add_forum_topic(
    key: str, data: TopicBody, user=Depends(current_user), db=Depends(get_db)
):
    from .discussion_feed import create_topic, describe

    row = create_topic(db, user, "forum", find_forum(db, key).id, data.title, data.body)
    return {**describe(row, user.username), "url": f"#discussions/{row.id}"}


def slugify(db, title, exclude=None):
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "forum"
    slug, suffix = base, 2
    while True:
        existing = db.scalar(select(Forum.id).where(Forum.slug == slug))
        if existing is None or existing == exclude:
            return slug
        slug, suffix = f"{base}-{suffix}", suffix + 1


class ForumInput(BaseModel):
    title: str = Field(min_length=3, max_length=80)
    description: str = Field(default="", max_length=1000)


class ForumUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=3, max_length=80)
    description: Optional[str] = Field(default=None, max_length=1000)
    archived: Optional[bool] = None


class ForumOrder(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)


@router.post("/admin/forums", status_code=201)
def create_forum(data: ForumInput, admin=Depends(require_admin), db=Depends(get_db)):
    from .moderation import record

    if len(data.title.strip()) < 3:
        raise HTTPException(422, "Give the forum a title of at least three characters")
    row = Forum(
        slug=slugify(db, data.title),
        title=data.title.strip(),
        description=data.description.strip(),
        position=(db.scalar(select(func.max(Forum.position))) or 0) + 1,
        archived=0,
    )
    db.add(row)
    db.flush()
    record(db, admin, "forum.create", "forum", row.id, {"title": row.title})
    db.commit()
    return forum_json(db, row, admin)


@router.put("/admin/forums/order")
def reorder_forums(data: ForumOrder, admin=Depends(require_admin), db=Depends(get_db)):
    from .moderation import record

    rows = {row.id: row for row in db.scalars(select(Forum).with_for_update())}
    if set(data.ids) != set(rows) or len(data.ids) != len(rows):
        raise HTTPException(422, "List every forum exactly once")
    for position, id in enumerate(data.ids):
        rows[id].position = position
    record(db, admin, "forum.reorder", "forum", "", {"ids": data.ids})
    db.commit()
    return forums(True, admin, db)


@router.put("/admin/forums/{id}")
def update_forum(
    id: int, data: ForumUpdate, admin=Depends(require_admin), db=Depends(get_db)
):
    from .moderation import record

    row = db.scalar(select(Forum).where(Forum.id == id).with_for_update())
    if not row:
        raise HTTPException(404, "Forum not found")
    changes = {}
    if data.title is not None and data.title.strip() != row.title:
        if len(data.title.strip()) < 3:
            raise HTTPException(
                422, "Give the forum a title of at least three characters"
            )
        changes["title"] = [row.title, data.title.strip()]
        row.title = data.title.strip()
    if data.description is not None and data.description.strip() != row.description:
        changes["description"] = True
        row.description = data.description.strip()
    if data.archived is not None and data.archived != bool(row.archived):
        changes["archived"] = data.archived
        row.archived = int(data.archived)
    if changes:
        record(db, admin, "forum.update", "forum", id, changes)
    db.commit()
    return forum_json(db, row, admin)


def general_forum(db):
    ensure_default_forums(db.connection())
    row = db.scalar(select(Forum).where(Forum.slug == "general")) or db.scalar(
        select(Forum).order_by(Forum.position, Forum.id).limit(1)
    )
    if not row:
        raise HTTPException(404, "No forum is available")
    return row


def legacy_topic(db, post):
    owner = db.get(User, post.owner_id)
    return {
        "id": post.id,
        "owner_id": post.owner_id,
        "title": post.title,
        "body": post.body,
        "created_at": post.created_at,
        "owner": owner.username if owner else "Deleted user",
    }


def legacy_comment(db, row):
    owner = db.get(User, row.owner_id)
    return {
        "id": row.id,
        "discussion_id": row.target_id,
        "owner_id": row.owner_id,
        "body": row.body,
        "created_at": row.created_at,
        "owner": owner.username if owner else "Deleted user",
    }


@router.get("/discussions", deprecated=True)
def legacy_discussions(
    response: Response,
    q: str = Query("", max_length=160),
    pagination: Page = Depends(page),
    user=Depends(optional_user),
    db=Depends(get_db),
):
    """Deprecated alias: topics in the General forum."""
    query = select(CompetitionPost).where(
        CompetitionPost.scope == "forum",
        CompetitionPost.scope_id == general_forum(db).id,
        visible_topics(user),
        CompetitionPost.deleted_at.is_(None),
    )
    if q.strip():
        query = query.where(
            CompetitionPost.title.icontains(q.strip()[:100], autoescape=True)
        )
    set_total(response, count(db, query))
    return [
        legacy_topic(db, row)
        for row in db.scalars(
            window(query.order_by(CompetitionPost.id.desc()), pagination)
        )
    ]


@router.post("/discussions", status_code=201, deprecated=True)
def legacy_create(
    data: DiscussionInput, user=Depends(current_user), db=Depends(get_db)
):
    """Deprecated alias: creates a topic in the General forum."""
    from .discussion_feed import create_topic

    row = create_topic(db, user, "forum", general_forum(db).id, data.title, data.body)
    return legacy_topic(db, row)


@router.get("/discussions/{id}/comments", deprecated=True)
def legacy_comments(id: int, user=Depends(optional_user), db=Depends(get_db)):
    """Deprecated alias: the first 100 comments of a topic."""
    require_topic(db, id, user)
    return [
        legacy_comment(db, row)
        for row in db.scalars(
            select(ContentReply)
            .where(
                ContentReply.target_kind == "competition-post",
                ContentReply.target_id == id,
                not_hidden(ContentReply, user),
            )
            .order_by(ContentReply.id)
            .limit(100)
        )
    ]


@router.post("/discussions/{id}/comments", status_code=201, deprecated=True)
def legacy_add_comment(
    id: int, data: CommentInput, user=Depends(current_user), db=Depends(get_db)
):
    from .engagement import ReplyInput, reply

    created = reply("competition-post", id, ReplyInput(body=data.body), user, db)
    return legacy_comment(db, db.get(ContentReply, created["id"]))
