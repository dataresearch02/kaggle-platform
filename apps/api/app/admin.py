"""Administrator API: accounts, reports, moderation, audit log and site settings."""

import logging
import os
import secrets
import time
from typing import Literal, Optional

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from .auth import hash_password
from .db import get_db
from .models import ApiToken, AuditLog, ContentReport, Session, User, now
from .moderation import (
    MODELS,
    Kind,
    delete_target,
    describe_target,
    load_target,
    record,
)
from .pagination import Page, count, page, set_total, window
from .permissions import owner_column, require_admin
from .site_settings import SettingsInput, site_settings, update_settings

router = APIRouter(
    prefix="/api/admin",
    tags=["Administration"],
    dependencies=[Depends(require_admin)],
)


def bootstrap_admins(db, names=None):
    """Promote existing users named in ARENA_ADMIN_USERNAMES (comma-separated)."""
    names = os.getenv("ARENA_ADMIN_USERNAMES", "") if names is None else names
    promoted = []
    for name in sorted({part.strip().lower() for part in names.split(",")} - {""}):
        user = db.scalar(select(User).where(User.username == name))
        if not user:
            logging.getLogger(__name__).warning(
                "ARENA_ADMIN_USERNAMES names %r, but no such user exists", name
            )
            continue
        if user.role != "admin":
            record(
                db,
                None,
                "user.role",
                "user",
                user.id,
                {
                    "username": user.username,
                    "from": user.role,
                    "to": "admin",
                    "source": "ARENA_ADMIN_USERNAMES",
                },
            )
            user.role = "admin"
            promoted.append(user.username)
    db.commit()
    return promoted


def locked_user(db, id):
    row = db.scalar(select(User).where(User.id == id).with_for_update())
    if not row:
        raise HTTPException(404, "User not found")
    return row


def user_json(db, row):
    return {
        "id": row.id,
        "username": row.username,
        "role": row.role,
        "status": row.status,
        "created_at": row.created_at,
        "active_sessions": db.scalar(
            select(func.count())
            .select_from(Session)
            .where(Session.user_id == row.id, Session.expires_at > time.time())
        ),
        "api_tokens": db.scalar(
            select(func.count())
            .select_from(ApiToken)
            .where(ApiToken.user_id == row.id, ApiToken.expires_at > time.time())
        ),
    }


@router.get("/users")
def users(
    response: Response,
    q: str = Query("", max_length=40),
    role: Optional[Literal["user", "host", "admin"]] = None,
    status: Optional[Literal["active", "suspended"]] = None,
    pagination: Page = Depends(page),
    db=Depends(get_db),
):
    query = select(User)
    if q.strip():
        query = query.where(User.username.icontains(q.strip(), autoescape=True))
    if role:
        query = query.where(User.role == role)
    if status:
        query = query.where(User.status == status)
    set_total(response, count(db, query))
    return [
        user_json(db, row)
        for row in db.scalars(window(query.order_by(User.id), pagination))
    ]


class UserUpdate(BaseModel):
    role: Optional[Literal["user", "host", "admin"]] = None
    status: Optional[Literal["active", "suspended"]] = None


@router.put("/users/{id}")
def update_user(
    id: int, data: UserUpdate, admin=Depends(require_admin), db=Depends(get_db)
):
    row = locked_user(db, id)
    for field in ("role", "status"):
        value = getattr(data, field)
        if value is None or value == getattr(row, field):
            continue
        if row.id == admin.id:
            raise HTTPException(
                409, "Ask another administrator to change your own role or status"
            )
        record(
            db,
            admin,
            f"user.{field}",
            "user",
            row.id,
            {"username": row.username, "from": getattr(row, field), "to": value},
        )
        setattr(row, field, value)
    db.commit()
    return user_json(db, row)


def revoke_credentials(db, user_id, tokens):
    sessions = db.execute(delete(Session).where(Session.user_id == user_id)).rowcount
    revoked_tokens = (
        db.execute(delete(ApiToken).where(ApiToken.user_id == user_id)).rowcount
        if tokens
        else 0
    )
    return sessions, revoked_tokens


@router.post("/users/{id}/password-reset")
def reset_password(
    id: int, response: Response, admin=Depends(require_admin), db=Depends(get_db)
):
    row = locked_user(db, id)
    if row.id == admin.id:
        raise HTTPException(409, "Change your own password from Account settings")
    # 24 URL-safe characters (144 random bits); shown to the administrator once.
    password = secrets.token_urlsafe(18)
    row.password_hash = hash_password(password)
    sessions, tokens = revoke_credentials(db, row.id, tokens=True)
    record(
        db,
        admin,
        "user.password_reset",
        "user",
        row.id,
        {
            "username": row.username,
            "sessions_revoked": sessions,
            "tokens_revoked": tokens,
        },
    )
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return {
        "temporary_password": password,
        "sessions_revoked": sessions,
        "tokens_revoked": tokens,
    }


@router.post("/users/{id}/revoke-sessions")
def revoke_sessions(id: int, admin=Depends(require_admin), db=Depends(get_db)):
    row = locked_user(db, id)
    sessions, _ = revoke_credentials(db, row.id, tokens=False)
    record(
        db,
        admin,
        "user.sessions_revoked",
        "user",
        row.id,
        {"username": row.username, "sessions_revoked": sessions},
    )
    db.commit()
    return {"sessions_revoked": sessions}


def username(db, id):
    user = db.get(User, id) if id else None
    return user.username if user else None


def report_json(db, row):
    return {
        "id": row.id,
        "kind": row.target_kind,
        "target_id": row.target_id,
        "reason": row.reason,
        "status": row.status,
        "reporter": username(db, row.reporter_id) or "Deleted user",
        "created_at": row.created_at,
        "resolution_note": row.resolution_note,
        "resolved_by": username(db, row.resolved_by),
        "resolved_at": row.resolved_at,
        "target": describe_target(db, row.target_kind, row.target_id),
    }


@router.get("/reports")
def reports(
    response: Response,
    status: Literal["open", "resolved", "all"] = "open",
    pagination: Page = Depends(page),
    db=Depends(get_db),
):
    query = select(ContentReport)
    if status != "all":
        query = query.where(ContentReport.status == status)
    set_total(response, count(db, query))
    return [
        report_json(db, row)
        for row in db.scalars(
            window(query.order_by(ContentReport.id.desc()), pagination)
        )
    ]


class ResolveInput(BaseModel):
    note: str = Field(default="", max_length=2000)


@router.post("/reports/{id}/resolve")
def resolve_report(
    id: int, data: ResolveInput, admin=Depends(require_admin), db=Depends(get_db)
):
    row = db.scalar(
        select(ContentReport).where(ContentReport.id == id).with_for_update()
    )
    if not row:
        raise HTTPException(404, "Report not found")
    if row.status == "resolved":
        raise HTTPException(409, "This report is already resolved")
    row.status = "resolved"
    row.resolution_note = data.note.strip()
    row.resolved_by = admin.id
    row.resolved_at = now()
    from .moderation import notify_reporter

    notify_reporter(db, row, admin)
    record(
        db,
        admin,
        "report.resolve",
        row.target_kind,
        row.target_id,
        {"report_id": row.id, "note": row.resolution_note},
    )
    db.commit()
    return report_json(db, row)


class HideInput(BaseModel):
    hidden: bool
    reason: str = Field(default="", max_length=1000)


@router.put("/moderation/{kind}/{id}")
def moderate(
    kind: Kind,
    id: int,
    data: HideInput,
    admin=Depends(require_admin),
    db=Depends(get_db),
):
    row = load_target(db, kind, id, lock=True)
    if row is None:
        raise HTTPException(404, "Content not found")
    reason = data.reason.strip()
    if data.hidden and len(reason) < 3:
        raise HTTPException(422, "Give a reason of at least three characters")
    if bool(row.hidden) != data.hidden:
        record(
            db,
            admin,
            "content.hide" if data.hidden else "content.unhide",
            kind,
            id,
            {"reason": reason},
        )
    row.hidden = int(data.hidden)
    row.hidden_reason = reason if data.hidden else ""
    from .progression import mark_related

    mark_related(db, kind, id)
    db.commit()
    return {"kind": kind, "id": id, **describe_target(db, kind, id)}


@router.delete("/moderation/{kind}/{id}", status_code=204)
async def delete_content(
    kind: Kind, id: int, admin=Depends(require_admin), db=Depends(get_db)
):
    await delete_target(db, kind, id, admin)
    return Response(status_code=204)


@router.get("/hidden")
def hidden_content(
    response: Response,
    kind: Optional[Kind] = None,
    pagination: Page = Depends(page),
    db=Depends(get_db),
):
    items = []
    for name, model in MODELS.items():
        if kind and name != kind:
            continue
        key = owner_column(model) if name == "profile" else model.id
        items.extend(
            (name, target_id)
            for target_id in db.scalars(
                select(key).where(model.hidden == 1).order_by(key.desc())
            )
        )
    set_total(response, len(items))
    return [
        {"kind": name, "id": target_id, **describe_target(db, name, target_id)}
        for name, target_id in pagination.slice(items)
    ]


@router.get("/revisions/{kind}/{id}")
def revisions(
    kind: Literal["competition-post", "reply", "notebook-comment"],
    id: int,
    db=Depends(get_db),
):
    """Previous text of an edited or author-deleted topic, comment or reply."""
    from .models import ContentRevision

    return [
        {
            "id": row.id,
            "editor": username(db, row.editor_id),
            "title": row.title,
            "body": row.body,
            "created_at": row.created_at,
        }
        for row in db.scalars(
            select(ContentRevision)
            .where(ContentRevision.target_kind == kind, ContentRevision.target_id == id)
            .order_by(ContentRevision.id.desc())
        )
    ]


@router.get("/audit")
def audit_log(
    response: Response,
    actor: str = Query("", max_length=40),
    action: str = Query("", max_length=60),
    pagination: Page = Depends(page),
    db=Depends(get_db),
):
    query = select(AuditLog, User.username).outerjoin(
        User, User.id == AuditLog.actor_id
    )
    if actor.strip().lower() == "system":
        query = query.where(AuditLog.actor_id.is_(None))
    elif actor.strip():
        query = query.where(User.username == actor.strip().lower())
    if action.strip():
        query = query.where(AuditLog.action.startswith(action.strip(), autoescape=True))
    set_total(response, count(db, query))
    return [
        {
            "id": row.id,
            "actor": name or ("system" if row.actor_id is None else "Deleted user"),
            "action": row.action,
            "target_kind": row.target_kind,
            "target_id": row.target_id,
            "detail": json.loads(row.detail or "{}"),
            "created_at": row.created_at,
        }
        for row, name in db.execute(
            window(query.order_by(AuditLog.id.desc()), pagination)
        )
    ]


@router.get("/settings")
def settings(db=Depends(get_db)):
    return site_settings(db)


@router.put("/settings")
def change_settings(
    data: SettingsInput, admin=Depends(require_admin), db=Depends(get_db)
):
    changes = update_settings(db, data)
    if changes:
        record(db, admin, "settings.update", "settings", "", {"changes": changes})
    db.commit()
    return site_settings(db)
