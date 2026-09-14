"""In-app notifications, per-kind preferences, and the merged list with service notices.

Notifications are created inside the caller's transaction. A recipient is only
notified about content they can see, and every listing re-checks visibility: a
notification whose item was since hidden, deleted or made private is shown
without its title or link.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, literal_column, or_, select, union_all, update

from .accounts import interactive_user
from .auth import current_user
from .community import (
    mentioned_names,
    mentioned_users,
    target_row,
    target_title,
    target_url,
)
from .db import get_db
from .models import (
    CompetitionPost,
    ContentReply,
    ModelCard,
    Dataset,
    Notebook,
    NotebookComment,
    NoticeRead,
    Notification,
    NotificationPreference,
    ServiceNotice,
    TopicWatch,
    User,
    now,
)
from .pagination import Page, page, set_total

router = APIRouter(prefix="/api", tags=["Notifications"])

KINDS = {
    "reply": "Replies to your topics and comments",
    "mention": "Mentions of your username",
    "watch": "New comments in topics you watch",
    "comment": "Comments and new topics on your notebooks, datasets and models",
    "vote": "Upvotes on your work, topics and comments",
    "fork": "Forks of your notebooks",
    "follow": "New followers",
    "result": "Your competition results and medals",
    "report": "Reports you made that were resolved",
    "run": "Failed scheduled notebook runs and disabled schedules",
}
# When one event concerns a recipient in several ways, the first kind wins.
PRIORITY = ("mention", "reply", "comment", "watch")


def enabled(db, user_id, kind):
    row = db.get(NotificationPreference, (user_id, kind))
    return row is None or bool(row.enabled)


def notify(
    db,
    recipient_id,
    kind,
    *,
    actor=None,
    target_kind="",
    target_id=None,
    detail=None,
    group_key=None,
    replace=False,
    check_visible=True,
):
    """Add a notification; returns whether one was created or updated.

    `group_key` coalesces repeated events into one row (counting them) or, with
    `replace`, keeps one row whose detail is refreshed.
    """
    if recipient_id is None or (actor and actor.id == recipient_id):
        return False
    recipient = db.get(User, recipient_id)
    if not recipient or not enabled(db, recipient_id, kind):
        return False
    url = ""
    if target_kind:
        row = target_row(db, target_kind, target_id, recipient)
        if row is None and check_visible:
            return False
        url = target_url(db, target_kind, row) or ""
    detail_json = json.dumps(detail or {}, sort_keys=True)
    if group_key:
        existing = db.scalar(
            select(Notification).where(
                Notification.recipient_id == recipient_id,
                Notification.group_key == group_key,
            )
        )
        if existing:
            if replace:
                if existing.detail != detail_json:
                    existing.detail, existing.read_at = detail_json, None
                    existing.created_at = now()
            else:
                existing.count += 1
                existing.actor_id = actor.id if actor else None
                existing.read_at, existing.created_at = None, now()
            return True
    db.add(
        Notification(
            recipient_id=recipient_id,
            kind=kind,
            actor_id=actor.id if actor else None,
            target_kind=target_kind,
            target_id=target_id,
            url=url[:255],
            detail=detail_json,
            group_key=group_key,
            created_at=now(),
        )
    )
    return True


def notify_candidates(db, candidates, actor, target_kind, target_id):
    """candidates: {user_id: set of kinds}; each user gets one notification."""
    for user_id, kinds in candidates.items():
        for kind in PRIORITY:
            if kind in kinds and enabled(db, user_id, kind):
                notify(
                    db,
                    user_id,
                    kind,
                    actor=actor,
                    target_kind=target_kind,
                    target_id=target_id,
                )
                break


def watchers(db, post_id):
    return set(
        db.scalars(select(TopicWatch.user_id).where(TopicWatch.post_id == post_id))
    )


def content_created(db, actor, kind, row):
    """Notify about a new topic ("competition-post"), topic comment or reply
    ("reply") or notebook comment. The row must be flushed."""
    candidates = {}

    def add(user_id, name):
        if user_id is not None:
            candidates.setdefault(user_id, set()).add(name)

    for mentioned in mentioned_users(db, row.body):
        add(mentioned.id, "mention")
    if kind == "competition-post":
        if not db.get(TopicWatch, (row.id, actor.id)):
            db.add(TopicWatch(post_id=row.id, user_id=actor.id))
        if row.scope in ("dataset", "model"):
            scope = db.get(
                Dataset if row.scope == "dataset" else ModelCard, row.scope_id
            )
            add(scope.owner_id if scope else None, "comment")
    elif kind == "notebook-comment":
        notebook = db.get(Notebook, row.notebook_id)
        add(notebook.owner_id if notebook else None, "comment")
    elif kind == "reply":
        if row.target_kind == "competition-post":
            topic = db.get(CompetitionPost, row.target_id)
            if topic:
                add(topic.owner_id, "reply")
                for user_id in watchers(db, topic.id):
                    add(user_id, "watch")
        elif row.target_kind == "competition-comment":
            parent = db.get(ContentReply, row.target_id)
            if parent:
                add(parent.owner_id, "reply")
                topic = db.get(CompetitionPost, parent.target_id)
                if topic:
                    for user_id in watchers(db, topic.id):
                        add(user_id, "watch")
        elif row.target_kind == "notebook-comment":
            parent = db.get(NotebookComment, row.target_id)
            add(parent.owner_id if parent else None, "reply")
    notify_candidates(db, candidates, actor, kind, row.id)


def content_edited(db, actor, kind, row, previous_text):
    """Only users newly mentioned by an edit are notified."""
    before = set(mentioned_names(previous_text))
    for mentioned in mentioned_users(db, row.body):
        if mentioned.username not in before:
            notify(
                db,
                mentioned.id,
                "mention",
                actor=actor,
                target_kind=kind,
                target_id=row.id,
            )


def message(kind, actor, count, title, detail):
    who = actor or "Someone"
    if kind == "vote":
        who = (
            f"{who} and {count - 1} other{'s' if count > 2 else ''}"
            if count > 1
            else who
        )
    text = {
        "reply": f"{who} replied",
        "mention": f"{who} mentioned you",
        "watch": f"{who} commented in a topic you watch",
        "comment": f"{who} commented",
        "vote": f"{who} upvoted",
        "fork": f"{who} forked",
        "follow": f"{who} started following you",
        "report": "A report you made was resolved",
    }.get(kind, "")
    if kind == "run":
        text = (
            "Your notebook schedule was disabled after repeated failures"
            if detail.get("event") == "disabled"
            else "A scheduled notebook run "
            + ("timed out" if detail.get("status") == "timed_out" else "failed")
        )
    if kind == "result":
        medal = detail.get("medal")
        text = f"You finished #{detail.get('rank')} of {detail.get('team_count')}" + (
            f" with a {medal} medal" if medal else ""
        )
    if title and kind not in ("follow",):
        text += f" · {title}"
    return text


def activity_json(db, row, user):
    actor = db.get(User, row.actor_id) if row.actor_id else None
    target = (
        target_row(db, row.target_kind, row.target_id, user)
        if row.target_kind
        else None
    )
    available = target is not None or not row.target_kind
    title = target_title(db, row.target_kind, target) if target is not None else None
    detail = json.loads(row.detail or "{}")
    return {
        "id": row.id,
        "source": "activity",
        "kind": row.kind,
        "actor": actor.username if actor else None,
        "title": title,
        "message": message(
            row.kind, actor.username if actor else None, row.count, title, detail
        ),
        "detail": detail,
        "count": row.count,
        # Links are recomputed so moved or hidden content is never exposed.
        "url": target_url(db, row.target_kind, target) if target is not None else None,
        "available": available,
        "read": row.read_at is not None,
        "created_at": row.created_at,
    }


def notice_filter(user):
    return or_(ServiceNotice.user_id.is_(None), ServiceNotice.user_id == user.id)


@router.get("/notifications")
def notifications(
    response: Response,
    pagination: Page = Depends(page),
    user=Depends(current_user),
    db=Depends(get_db),
):
    """Activity notifications and service notices, newest first."""
    merged = union_all(
        select(
            literal_column("'activity'").label("source"),
            Notification.id.label("id"),
            Notification.created_at.label("created_at"),
        ).where(Notification.recipient_id == user.id),
        select(
            literal_column("'service'").label("source"),
            ServiceNotice.id.label("id"),
            ServiceNotice.created_at.label("created_at"),
        ).where(notice_filter(user)),
    ).subquery()
    set_total(response, db.scalar(select(func.count()).select_from(merged)))
    rows = db.execute(
        select(merged.c.source, merged.c.id)
        .order_by(merged.c.created_at.desc(), merged.c.id.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).all()
    items = []
    for source, id in rows:
        if source == "activity":
            items.append(activity_json(db, db.get(Notification, id), user))
        else:
            notice = db.get(ServiceNotice, id)
            items.append(
                {
                    "id": notice.id,
                    "source": "service",
                    "kind": "service",
                    "actor": None,
                    "title": notice.title,
                    "message": notice.body,
                    "detail": {},
                    "count": 1,
                    "url": None,
                    "available": True,
                    "read": db.get(NoticeRead, (notice.id, user.id)) is not None,
                    "created_at": notice.created_at,
                }
            )
    return items


def unread_count(db, user):
    activity = db.scalar(
        select(func.count(Notification.id)).where(
            Notification.recipient_id == user.id, Notification.read_at.is_(None)
        )
    )
    notices = db.scalar(
        select(func.count(ServiceNotice.id)).where(
            notice_filter(user),
            ServiceNotice.id.not_in(
                select(NoticeRead.notice_id).where(NoticeRead.user_id == user.id)
            ),
        )
    )
    return activity + notices


@router.get("/notifications/unread-count")
def unread(user=Depends(current_user), db=Depends(get_db)):
    return {"count": unread_count(db, user)}


@router.post("/notifications/read-all")
def read_all(user=Depends(current_user), db=Depends(get_db)):
    db.refresh(user, with_for_update=True)
    db.execute(
        update(Notification)
        .where(Notification.recipient_id == user.id, Notification.read_at.is_(None))
        .values(read_at=now())
    )
    for notice_id in db.scalars(
        select(ServiceNotice.id).where(
            notice_filter(user),
            ServiceNotice.id.not_in(
                select(NoticeRead.notice_id).where(NoticeRead.user_id == user.id)
            ),
        )
    ).all():
        db.add(NoticeRead(notice_id=notice_id, user_id=user.id))
    db.commit()
    return {"count": 0}


@router.post("/notifications/{source}/{id}/read")
def read_one(source: str, id: int, user=Depends(current_user), db=Depends(get_db)):
    if source == "activity":
        row = db.get(Notification, id)
        if not row or row.recipient_id != user.id:
            raise HTTPException(404, "Notification not found")
        if row.read_at is None:
            row.read_at = now()
            db.commit()
    elif source == "service":
        from .accounts import read_notice

        read_notice(id, user, db)
    else:
        raise HTTPException(404, "Notification not found")
    return {"count": unread_count(db, user)}


def preferences_json(db, user):
    return {
        "preferences": [
            {"kind": kind, "label": label, "enabled": enabled(db, user.id, kind)}
            for kind, label in KINDS.items()
        ]
    }


@router.get("/account/notification-preferences")
def preferences(user=Depends(interactive_user), db=Depends(get_db)):
    return preferences_json(db, user)


@router.put("/account/notification-preferences")
def update_preferences(
    data: dict[str, bool], user=Depends(interactive_user), db=Depends(get_db)
):
    unknown = set(data) - set(KINDS)
    if unknown:
        raise HTTPException(
            422, f"Unknown notification kinds: {', '.join(sorted(unknown))}"
        )
    db.refresh(user, with_for_update=True)
    for kind, value in data.items():
        row = db.get(NotificationPreference, (user.id, kind))
        if not row:
            row = NotificationPreference(user_id=user.id, kind=kind)
            db.add(row)
        row.enabled = int(value)
    db.commit()
    return preferences_json(db, user)
