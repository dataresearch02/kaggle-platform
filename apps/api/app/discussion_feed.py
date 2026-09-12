"""Shared competition topics, with separate comments and persistent list controls."""

import secrets
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select, or_, func
from .db import get_db, DATA_DIR
from .auth import current_user
from .code_pages import optional_user
from .models import (
    CompetitionPost,
    User,
    Competition,
    ChallengeDetails,
    ContentReply,
    ContentReaction,
    CompetitionTopicSettings,
    CompetitionTopicBookmark,
    DiscussionImage,
)

router = APIRouter(prefix="/api/competition-discussions", tags=["Discussions"])


def topic(db, id):
    row = db.get(CompetitionPost, id)
    if not row:
        raise HTTPException(404, "Discussion not found")
    return row


def can_pin(db, competition_id, user):
    row = db.get(ChallengeDetails, competition_id)
    return bool(user and row and row.owner_id == user.id)


def describe(post, owner):
    return {
        "id": post.id,
        "competition_id": post.competition_id,
        "owner_id": post.owner_id,
        "title": post.title,
        "body": post.body,
        "owner": owner,
        "created_at": post.created_at,
    }


@router.get("")
def feed(
    q: str = Query("", max_length=160),
    before: int = Query(2147483647, ge=1),
    competition_id: Optional[int] = None,
    filter: Literal["all", "owned", "bookmarks"] = "all",
    sort: Literal["recent", "newest", "votes", "comments"] = "recent",
    unanswered: bool = False,
    offset: int = Query(0, ge=0, le=100000),
    user=Depends(optional_user),
    db=Depends(get_db),
):
    uid = user.id if user else -1
    comments = (
        select(
            ContentReply.target_id.label("post_id"),
            func.count().label("count"),
            func.max(ContentReply.created_at).label("latest"),
        )
        .where(ContentReply.target_kind == "competition-post")
        .group_by(ContentReply.target_id)
        .subquery()
    )
    votes = (
        select(ContentReaction.target_id.label("post_id"), func.count().label("count"))
        .where(
            ContentReaction.target_kind == "competition-post",
            ContentReaction.reaction == "like",
        )
        .group_by(ContentReaction.target_id)
        .subquery()
    )
    count = func.coalesce(comments.c.count, 0)
    score = func.coalesce(votes.c.count, 0)
    pinned = func.coalesce(CompetitionTopicSettings.pinned, 0)
    latest = func.coalesce(comments.c.latest, CompetitionPost.created_at)
    bookmark = (
        select(CompetitionTopicBookmark.post_id)
        .where(
            CompetitionTopicBookmark.post_id == CompetitionPost.id,
            CompetitionTopicBookmark.user_id == uid,
        )
        .exists()
    )
    voted = (
        select(ContentReaction.id)
        .where(
            ContentReaction.target_kind == "competition-post",
            ContentReaction.target_id == CompetitionPost.id,
            ContentReaction.user_id == uid,
            ContentReaction.reaction == "like",
        )
        .exists()
    )
    query = (
        select(
            CompetitionPost,
            User.username,
            count,
            score,
            pinned,
            latest,
            bookmark,
            voted,
        )
        .join(User, User.id == CompetitionPost.owner_id)
        .outerjoin(comments, comments.c.post_id == CompetitionPost.id)
        .outerjoin(votes, votes.c.post_id == CompetitionPost.id)
        .outerjoin(
            CompetitionTopicSettings,
            CompetitionTopicSettings.post_id == CompetitionPost.id,
        )
        .where(CompetitionPost.id < before)
    )
    if competition_id is not None:
        if not db.get(Competition, competition_id):
            raise HTTPException(404, "Competition not found")
        query = query.where(CompetitionPost.competition_id == competition_id)
    if q.strip():
        query = query.where(
            or_(
                CompetitionPost.title.icontains(q.strip(), autoescape=True),
                CompetitionPost.body.icontains(q.strip(), autoescape=True),
            )
        )
    if filter == "owned":
        query = query.where(CompetitionPost.owner_id == uid)
    if filter == "bookmarks":
        query = query.where(bookmark)
    if unanswered:
        query = query.where(count == 0)
    ordering = {
        "recent": latest,
        "newest": CompetitionPost.id,
        "votes": score,
        "comments": count,
    }[sort]
    rows = db.execute(
        query.order_by(pinned.desc(), ordering.desc(), CompetitionPost.id.desc())
        .offset(offset)
        .limit(31)
    ).all()
    return {
        "items": [
            {
                **describe(post, owner),
                "body": body_excerpt(post.body),
                "comment_count": n,
                "votes": v,
                "pinned": bool(pin),
                "last_activity": activity,
                "bookmarked": bool(mark),
                "voted": bool(vote),
            }
            for post, owner, n, v, pin, activity, mark, vote in rows[:30]
        ],
        "next_offset": offset + 30 if len(rows) > 30 else None,
        "next_cursor": rows[29][0].id if len(rows) > 30 else None,
        "can_pin": can_pin(db, competition_id, user) if competition_id else False,
    }


def body_excerpt(body):
    return body[:240]


@router.post("/images", status_code=201)
async def upload_image(
    competition_id: int,
    file: UploadFile = File(...),
    user=Depends(current_user),
    db=Depends(get_db),
):
    if not db.get(Competition, competition_id):
        raise HTTPException(404, "Competition not found")
    content = await file.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(413, "Images must be 5 MB or smaller")
    mime = (
        "image/png"
        if content.startswith(b"\x89PNG\r\n\x1a\n")
        else (
            "image/jpeg"
            if content.startswith(b"\xff\xd8\xff")
            else (
                "image/gif"
                if content.startswith((b"GIF87a", b"GIF89a"))
                else (
                    "image/webp"
                    if content.startswith(b"RIFF") and content[8:12] == b"WEBP"
                    else None
                )
            )
        )
    )
    if not mime:
        raise HTTPException(422, "Upload a PNG, JPEG, GIF, or WebP image")
    key = secrets.token_hex(24)
    root = DATA_DIR / "discussion-images"
    root.mkdir(exist_ok=True)
    path = root / key
    try:
        path.write_bytes(content)
        db.add(
            DiscussionImage(
                id=key,
                competition_id=competition_id,
                owner_id=user.id,
                media_type=mime,
                size=len(content),
            )
        )
        db.commit()
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return {"url": f"/api/competition-discussions/images/{key}"}


@router.get("/images/{key}")
def image_file(key: str, db=Depends(get_db)):
    row = db.get(DiscussionImage, key)
    if not row or not (DATA_DIR / "discussion-images" / row.id).is_file():
        raise HTTPException(404, "Image not found")
    return FileResponse(
        DATA_DIR / "discussion-images" / row.id,
        media_type=row.media_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@router.get("/{id}")
def detail(id: int, user=Depends(optional_user), db=Depends(get_db)):
    row = topic(db, id)
    settings = db.get(CompetitionTopicSettings, id)
    return {
        **describe(row, db.get(User, row.owner_id).username),
        "pinned": bool(settings and settings.pinned),
        "can_pin": can_pin(db, row.competition_id, user),
        "bookmarked": bool(user and db.get(CompetitionTopicBookmark, (id, user.id))),
    }


class Toggle(BaseModel):
    enabled: bool


@router.put("/{id}/pin")
def pin(id: int, data: Toggle, user=Depends(current_user), db=Depends(get_db)):
    row = topic(db, id)
    if not can_pin(db, row.competition_id, user):
        raise HTTPException(403, "Only the competition organizer can pin topics")
    db.merge(CompetitionTopicSettings(post_id=id, pinned=int(data.enabled)))
    db.commit()
    return {"pinned": data.enabled}


@router.put("/{id}/bookmark")
def bookmark(id: int, data: Toggle, user=Depends(current_user), db=Depends(get_db)):
    topic(db, id)
    row = db.get(CompetitionTopicBookmark, (id, user.id))
    if data.enabled and not row:
        db.add(CompetitionTopicBookmark(post_id=id, user_id=user.id))
    elif not data.enabled and row:
        db.delete(row)
    db.commit()
    return {"bookmarked": data.enabled}


# Existing competition-post replies ARE topic comments. Keep their IDs and data.
@router.get("/{id}/comments")
def comments(
    id: int,
    after: int = Query(0, ge=0),
    user=Depends(optional_user),
    db=Depends(get_db),
):
    from .engagement import read

    result = read("competition-post", id, after, user, db)
    return {"items": result["replies"], "next_cursor": result["next_cursor"]}


from .engagement import ReplyInput


@router.post("/{id}/comments", status_code=201)
def add_comment(
    id: int, data: ReplyInput, user=Depends(current_user), db=Depends(get_db)
):
    from .engagement import reply

    return reply("competition-post", id, data, user, db)
