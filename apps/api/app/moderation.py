"""Community reports, administrator moderation of content, and the audit log."""

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from .auth import current_user
from .db import get_db
from .models import (
    AuditLog,
    CompetitionPost,
    ContentReply,
    ContentReport,
    Dataset,
    ModelCard,
    Notebook,
    NotebookComment,
    User,
    UserProfile,
    now,
)
from .community import target_row, target_url

router = APIRouter(prefix="/api", tags=["Moderation"])

# "reply" covers competition topic comments and replies to notebook comments.
Kind = Literal[
    "competition-post",
    "reply",
    "code",
    "notebook-comment",
    "dataset",
    "model",
    "profile",
]
MODELS = {
    "competition-post": CompetitionPost,
    "reply": ContentReply,
    "code": Notebook,
    "notebook-comment": NotebookComment,
    "dataset": Dataset,
    "model": ModelCard,
    "profile": UserProfile,
}
# Items with files and dependent records are removed through the Your work flow.
WORK_KINDS = {"dataset": "datasets", "code": "notebooks", "model": "models"}
REPLY_PARENTS = {
    "competition-post": CompetitionPost,
    "notebook-comment": NotebookComment,
}


def record(db, actor, action, target_kind="", target_id="", detail=None):
    """Add an audit entry to the caller's transaction. A null actor is the system."""
    db.add(
        AuditLog(
            actor_id=actor.id if actor else None,
            action=action,
            target_kind=target_kind,
            target_id=str(target_id),
            detail=json.dumps(detail or {}, default=str),
        )
    )


def load_target(db, kind, id, lock=False):
    """Return the moderated row, or None. A missing profile row is created."""
    if kind == "profile":
        user = db.get(User, id)
        if not user:
            return None
        from .accounts import profile_row

        if lock:
            db.refresh(user, with_for_update=True)
        return profile_row(db, user)
    model = MODELS[kind]
    query = select(model).where(model.id == id)
    return db.scalar(query.with_for_update() if lock else query)


def excerpt(value, length=160):
    value = " ".join((value or "").split())
    return value if len(value) <= length else value[: length - 1] + "…"


def describe_target(db, kind, id):
    """Summary for moderators: title, owner, hidden state and an in-app link."""
    unavailable = {
        "available": False,
        "title": "Deleted content",
        "owner": None,
        "owner_id": None,
        "hidden": False,
        "hidden_reason": "",
        "link": None,
    }
    if kind == "profile":
        user = db.get(User, id)
        if not user:
            return {**unavailable, "title": "Deleted user"}
        row = db.get(UserProfile, id)
        return {
            "available": True,
            "title": f"Profile of {user.username}",
            "owner": user.username,
            "owner_id": user.id,
            "hidden": bool(row and row.hidden),
            "hidden_reason": row.hidden_reason if row else "",
            "link": f"#profile/{user.username}",
        }
    row = db.get(MODELS[kind], id) if kind in MODELS else None
    if row is None:
        return unavailable
    owner = db.get(User, row.owner_id)
    link = target_url(db, kind, row)
    return {
        "available": True,
        "title": getattr(row, "title", None) or excerpt(row.body),
        "owner": owner.username if owner else "Deleted user",
        "owner_id": row.owner_id,
        "hidden": bool(row.hidden),
        "hidden_reason": row.hidden_reason,
        "link": link,
    }


def require_reportable(db, kind, id, user):
    """Resolve an item the user can currently see; return its owner id or 404."""
    row = target_row(db, kind, id, user)
    if row is None:
        raise HTTPException(404, "Content not found")
    return row.id if kind == "profile" else row.owner_id


def notify_reporter(db, report, actor):
    from .notifications import notify

    # The reporter learns the outcome even when the item is gone; the listing
    # then shows no title or link.
    notify(
        db,
        report.reporter_id,
        "report",
        actor=None if actor and actor.id == report.reporter_id else actor,
        target_kind=report.target_kind,
        target_id=report.target_id,
        detail={"report_id": report.id},
        check_visible=False,
    )


def resolve_open_reports(db, kind, id, actor, note):
    for report in db.scalars(
        select(ContentReport).where(
            ContentReport.target_kind == kind,
            ContentReport.target_id == id,
            ContentReport.status == "open",
        )
    ):
        report.status = "resolved"
        report.resolution_note = note
        report.resolved_by = actor.id
        report.resolved_at = now()
        notify_reporter(db, report, actor)


async def delete_target(db, kind, id, actor):
    """Permanently remove reported content; profiles are cleared, not deleted."""
    if not describe_target(db, kind, id)["available"]:
        raise HTTPException(404, "Content not found")
    resolve_open_reports(db, kind, id, actor, "Content deleted by an administrator")
    from .progression import mark_related

    mark_related(db, kind, id)
    if kind in WORK_KINDS:
        from .main import remove_work

        # Records the audit entry and commits with the deletion.
        await remove_work(WORK_KINDS[kind], id, actor, db, moderated=True)
        return
    snapshot = describe_target(db, kind, id)
    record(
        db,
        actor,
        "content.delete",
        kind,
        id,
        {"title": snapshot["title"], "owner": snapshot["owner"]},
    )
    from .engagement import remove_engagement

    row = load_target(db, kind, id, lock=True)
    if kind == "profile":
        row.details, row.avatar, row.avatar_type = "{}", "", ""
    else:
        if kind == "competition-post":
            remove_engagement(db, "competition-post", [id])
        elif kind == "notebook-comment":
            remove_engagement(db, "notebook-comment", [id])
        elif kind == "reply" and row.target_kind == "competition-post":
            remove_engagement(db, "competition-comment", [id])
        db.delete(row)
    db.commit()


class ReportInput(BaseModel):
    kind: Kind
    id: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=2000)


@router.post("/reports", status_code=201)
def report(data: ReportInput, user=Depends(current_user), db=Depends(get_db)):
    reason = data.reason.strip()
    if len(reason) < 3:
        raise HTTPException(422, "Describe the problem in at least three characters")
    owner_id = require_reportable(db, data.kind, data.id, user)
    if owner_id == user.id:
        raise HTTPException(422, "You cannot report your own content")
    # Lock the reporter so duplicate submissions cannot race past the check.
    db.refresh(user, with_for_update=True)
    if db.scalar(
        select(ContentReport.id).where(
            ContentReport.reporter_id == user.id,
            ContentReport.target_kind == data.kind,
            ContentReport.target_id == data.id,
            ContentReport.status == "open",
        )
    ):
        raise HTTPException(
            409, "You already reported this item; a moderator will review it"
        )
    row = ContentReport(
        reporter_id=user.id, target_kind=data.kind, target_id=data.id, reason=reason
    )
    db.add(row)
    db.commit()
    return {"id": row.id, "status": row.status}
