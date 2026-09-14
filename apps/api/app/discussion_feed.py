"""Discussion topics in competitions, site forums and dataset/model pages.

Every topic is a `CompetitionPost` with a scope; comments and replies are
`ContentReply` rows, so all scopes share one feed, one thread model and the same
pinning, locking, bookmarks, watches, votes and moderation.
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import case, select, or_, func
from .db import get_db, DATA_DIR
from .auth import current_user
from .code_pages import optional_user
from .community import (
    add_mentions,
    can_moderate_topic,
    require_open_topic,
    require_topic,
    save_revision,
    scope_row,
    scope_visible,
    target_url,
    visible_topics,
)
from .pagination import MAX_LIMIT, count as count_rows, set_total
from .permissions import can_manage, is_admin
from .models import (
    CompetitionPost,
    User,
    Competition,
    ContentReply,
    CompetitionTopicSettings,
    CompetitionTopicBookmark,
    DiscussionImage,
    Forum,
    TopicWatch,
    Vote,
    now,
)

router = APIRouter(prefix="/api/competition-discussions", tags=["Discussions"])

Scope = Literal["competition", "forum", "dataset", "model"]


def topic(db, id):
    row = db.get(CompetitionPost, id)
    if not row:
        raise HTTPException(404, "Discussion not found")
    return row


def can_pin(db, competition_id, user):
    return can_moderate_topic(db, "competition", user, competition_id)


def describe(post, owner):
    return {
        "id": post.id,
        "competition_id": post.competition_id,
        "scope": post.scope,
        "scope_id": post.scope_id,
        "owner_id": post.owner_id,
        "title": post.title,
        "body": post.body,
        "owner": owner,
        "created_at": post.created_at,
        "edited_at": post.edited_at,
        "deleted": bool(post.deleted_at),
        "hidden": bool(post.hidden),
        "hidden_reason": post.hidden_reason,
    }


def scope_titles(db, posts):
    titles = {}
    for post in posts:
        key = (post.scope, post.scope_id)
        if key not in titles:
            row = scope_row(db, *key)
            titles[key] = row.title if row else None
    return titles


def settings_row(db, id):
    row = db.get(CompetitionTopicSettings, id)
    if not row:
        row = CompetitionTopicSettings(post_id=id, pinned=0, locked=0)
        db.add(row)
    return row


def scope_accepts_topics(db, scope, scope_id):
    if scope == "forum":
        forum = db.get(Forum, scope_id)
        return bool(forum and not forum.archived)
    return True


@router.get("")
def feed(
    response: Response,
    q: str = Query("", max_length=160),
    before: int = Query(2147483647, ge=1),
    competition_id: Optional[int] = None,
    scope: Optional[Scope] = None,
    scope_id: Optional[int] = None,
    filter: Literal["all", "owned", "bookmarks", "watching"] = "all",
    sort: Literal["recent", "newest", "votes", "comments", "hot"] = "recent",
    unanswered: bool = False,
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(30, ge=1),
    user=Depends(optional_user),
    db=Depends(get_db),
):
    uid = user.id if user else -1
    limit = min(limit, MAX_LIMIT)
    if competition_id is not None:
        scope, scope_id = "competition", competition_id
    comments = (
        select(
            ContentReply.target_id.label("post_id"),
            func.count().label("count"),
            func.max(ContentReply.created_at).label("latest"),
        )
        .where(
            ContentReply.target_kind == "competition-post",
            ContentReply.hidden == 0,
            ContentReply.deleted_at.is_(None),
        )
        .group_by(ContentReply.target_id)
        .subquery()
    )
    votes = (
        select(Vote.target_id.label("post_id"), func.count().label("count"))
        .where(Vote.target_kind == "competition-post")
        .group_by(Vote.target_id)
        .subquery()
    )
    count = func.coalesce(comments.c.count, 0)
    score = func.coalesce(votes.c.count, 0)
    pinned = func.coalesce(CompetitionTopicSettings.pinned, 0)
    locked = func.coalesce(CompetitionTopicSettings.locked, 0)
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
        select(Vote.id)
        .where(
            Vote.target_kind == "competition-post",
            Vote.target_id == CompetitionPost.id,
            Vote.user_id == uid,
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
            locked,
        )
        .join(User, User.id == CompetitionPost.owner_id)
        .outerjoin(comments, comments.c.post_id == CompetitionPost.id)
        .outerjoin(votes, votes.c.post_id == CompetitionPost.id)
        .outerjoin(
            CompetitionTopicSettings,
            CompetitionTopicSettings.post_id == CompetitionPost.id,
        )
        .where(
            CompetitionPost.id < before,
            visible_topics(user),
            CompetitionPost.deleted_at.is_(None),
        )
    )
    if scope is not None:
        if scope_id is not None:
            if not scope_row(db, scope, scope_id) or not scope_visible(
                db, scope, scope_id, user
            ):
                raise HTTPException(
                    404,
                    (
                        "Competition not found"
                        if scope == "competition"
                        else "Discussion scope not found"
                    ),
                )
            query = query.where(CompetitionPost.scope_id == scope_id)
        query = query.where(CompetitionPost.scope == scope)
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
    if filter == "watching":
        query = query.where(
            select(TopicWatch.post_id)
            .where(TopicWatch.post_id == CompetitionPost.id, TopicWatch.user_id == uid)
            .exists()
        )
    if unanswered:
        query = query.where(count == 0)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    ordering = {
        "recent": [latest.desc()],
        "newest": [CompetitionPost.id.desc()],
        "votes": [score.desc()],
        "comments": [count.desc()],
        # Topics active in the last two weeks first, by comments plus votes.
        "hot": [
            case((latest >= cutoff, 1), else_=0).desc(),
            (count + score).desc(),
            latest.desc(),
        ],
    }[sort]
    set_total(response, count_rows(db, query))
    rows = db.execute(
        query.order_by(pinned.desc(), *ordering, CompetitionPost.id.desc())
        .offset(offset)
        .limit(limit + 1)
    ).all()
    page = rows[:limit]
    from .progression import tier_name, tiers_for

    tiers = tiers_for(db, [row[0].owner_id for row in page], user)
    titles = scope_titles(db, [row[0] for row in page])
    return {
        "items": [
            {
                **describe(post, owner),
                "body": body_excerpt(post.body),
                "comment_count": n,
                "votes": v,
                "pinned": bool(pin),
                "locked": bool(lock),
                "last_activity": activity,
                "bookmarked": bool(mark),
                "voted": bool(vote),
                "scope_title": titles[(post.scope, post.scope_id)],
                "url": target_url(db, "competition-post", post),
                "owner_tier": tier_name(tiers, post.owner_id),
            }
            for post, owner, n, v, pin, activity, mark, vote, lock in page
        ],
        "next_offset": offset + limit if len(rows) > limit else None,
        "next_cursor": rows[limit - 1][0].id if len(rows) > limit else None,
        "can_pin": (
            can_moderate_topic(db, scope, user, scope_id)
            if scope is not None and scope_id is not None
            else False
        ),
        "can_post": (
            scope_accepts_topics(db, scope, scope_id)
            if scope is not None and scope_id is not None
            else False
        ),
    }


def body_excerpt(body):
    return body[:240]


class TopicInput(BaseModel):
    scope: Scope
    scope_id: int
    title: str = Field(min_length=3, max_length=160)
    body: str = Field(min_length=3, max_length=20000)


def create_topic(db, user, scope, scope_id, title, body):
    """Create a topic in any scope the user can see; commits."""
    if scope == "competition" and not db.get(Competition, scope_id):
        raise HTTPException(404, "Competition not found")
    if not scope_visible(db, scope, scope_id, user):
        raise HTTPException(404, "Discussion scope not found")
    if not scope_accepts_topics(db, scope, scope_id):
        raise HTTPException(409, "This forum is archived and read-only")
    if len(title.strip()) < 3 or len(body.strip()) < 3:
        raise HTTPException(
            422, "Enter a title and a message of at least three characters"
        )
    row = CompetitionPost(
        competition_id=scope_id if scope == "competition" else None,
        scope=scope,
        scope_id=scope_id,
        owner_id=user.id,
        title=title,
        body=body,
    )
    db.add(row)
    db.flush()
    from .notifications import content_created
    from .progression import mark_dirty

    content_created(db, user, "competition-post", row)
    mark_dirty(db, user.id)
    db.commit()
    return row


@router.post("", status_code=201)
def add_topic(data: TopicInput, user=Depends(current_user), db=Depends(get_db)):
    row = create_topic(db, user, data.scope, data.scope_id, data.title, data.body)
    return {
        **describe(row, user.username),
        "url": target_url(db, "competition-post", row),
    }


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
    row = require_topic(db, id, user)
    settings = db.get(CompetitionTopicSettings, id)
    from .progression import tier_name, tiers_for
    from .votes import summary

    owner = db.get(User, row.owner_id)
    locked = bool(settings and settings.locked)
    return add_mentions(
        db,
        [
            {
                **describe(row, owner.username if owner else "Deleted user"),
                **summary(db, "competition-post", id, user),
                "pinned": bool(settings and settings.pinned),
                "locked": locked,
                "can_pin": can_moderate_topic(db, row, user),
                "can_edit": can_manage(user, row.owner_id) and not row.deleted_at,
                "can_comment": not row.deleted_at
                and not locked
                and scope_accepts_topics(db, row.scope, row.scope_id),
                "bookmarked": bool(
                    user and db.get(CompetitionTopicBookmark, (id, user.id))
                ),
                "watching": bool(user and db.get(TopicWatch, (id, user.id))),
                "scope_title": scope_titles(db, [row])[(row.scope, row.scope_id)],
                "url": target_url(db, "competition-post", row),
                "owner_tier": tier_name(
                    tiers_for(db, [row.owner_id], user), row.owner_id
                ),
            }
        ],
    )[0]


class TopicEdit(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    body: str = Field(min_length=3, max_length=20000)


@router.put("/{id}")
def edit_topic(
    id: int, data: TopicEdit, user=Depends(current_user), db=Depends(get_db)
):
    row = require_topic(db, id, user)
    if not can_manage(user, row.owner_id):
        raise HTTPException(403, "You can only edit your own topics")
    if row.deleted_at:
        raise HTTPException(409, "This topic was deleted")
    if len(data.title.strip()) < 3 or len(data.body.strip()) < 3:
        raise HTTPException(
            422, "Enter a title and a message of at least three characters"
        )
    if (data.title, data.body) != (row.title, row.body):
        save_revision(db, "competition-post", row, user)
        previous = row.body
        row.title, row.body, row.edited_at = data.title, data.body, now()
        if row.owner_id != user.id:
            from .moderation import record

            record(
                db,
                user,
                "content.update",
                "competition-post",
                id,
                {"owner_id": row.owner_id},
            )
        from .notifications import content_edited

        content_edited(db, user, "competition-post", row, previous)
        db.commit()
    return detail(id, user, db)


@router.delete("/{id}", status_code=204)
def delete_topic(id: int, user=Depends(current_user), db=Depends(get_db)):
    """Authors delete their topic; with comments it stays as a placeholder."""
    row = require_topic(db, id, user)
    if not can_manage(user, row.owner_id):
        raise HTTPException(403, "You can only delete your own topics")
    from .progression import mark_related
    from .votes import remove_votes

    mark_related(db, "competition-post", id)
    if row.owner_id != user.id:
        from .moderation import record

        record(
            db,
            user,
            "content.delete",
            "competition-post",
            id,
            {"title": row.title, "owner_id": row.owner_id},
        )
    if db.scalar(
        select(ContentReply.id).where(
            ContentReply.target_kind == "competition-post", ContentReply.target_id == id
        )
    ):
        if not row.deleted_at:
            save_revision(db, "competition-post", row, user)
            row.title, row.body, row.deleted_at = "Deleted topic", "", now()
            remove_votes(db, "competition-post", [id])
    else:
        from .engagement import remove_engagement

        remove_engagement(db, "competition-post", [id])
        db.delete(row)
    db.commit()
    return Response(status_code=204)


class Toggle(BaseModel):
    enabled: bool


@router.put("/{id}/pin")
def pin(id: int, data: Toggle, user=Depends(current_user), db=Depends(get_db)):
    row = require_topic(db, id, user)
    if not can_moderate_topic(db, row, user):
        raise HTTPException(403, "Only the competition organizer can pin topics")
    settings_row(db, id).pinned = int(data.enabled)
    db.commit()
    return {"pinned": data.enabled}


@router.put("/{id}/lock")
def lock(id: int, data: Toggle, user=Depends(current_user), db=Depends(get_db)):
    row = require_topic(db, id, user)
    if not can_moderate_topic(db, row, user):
        raise HTTPException(403, "Only hosts and administrators can lock topics")
    settings = settings_row(db, id)
    if bool(settings.locked) != data.enabled and is_admin(user):
        from .moderation import record

        record(
            db,
            user,
            "topic.lock" if data.enabled else "topic.unlock",
            "competition-post",
            id,
        )
    settings.locked = int(data.enabled)
    db.commit()
    return {"locked": data.enabled}


@router.put("/{id}/bookmark")
def bookmark(id: int, data: Toggle, user=Depends(current_user), db=Depends(get_db)):
    require_topic(db, id, user)
    row = db.get(CompetitionTopicBookmark, (id, user.id))
    if data.enabled and not row:
        db.add(CompetitionTopicBookmark(post_id=id, user_id=user.id))
    elif not data.enabled and row:
        db.delete(row)
    db.commit()
    return {"bookmarked": data.enabled}


@router.put("/{id}/watch")
def watch(id: int, data: Toggle, user=Depends(current_user), db=Depends(get_db)):
    """Watchers are notified about new comments and replies in the topic."""
    require_topic(db, id, user)
    row = db.get(TopicWatch, (id, user.id))
    if data.enabled and not row:
        db.add(TopicWatch(post_id=id, user_id=user.id))
    elif not data.enabled and row:
        db.delete(row)
    db.commit()
    return {"watching": data.enabled}


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
