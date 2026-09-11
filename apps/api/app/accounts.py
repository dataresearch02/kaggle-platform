"""Persistent account profiles, session-only settings, groups and CLI credentials."""

import base64
import hashlib
import json
import secrets
import time
from typing import Literal, Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    UploadFile,
    File,
)
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select, delete, or_
from sqlalchemy.orm import Session as DBSession

from .auth import current_user, verify_password, hash_password, new_session
from .code_pages import optional_user
from .db import get_db
from .models import (
    User,
    UserProfile,
    ApiToken,
    UserGroup,
    GroupMember,
    ServiceNotice,
    NoticeRead,
    Session,
)

router = APIRouter(prefix="/api", tags=["Account management"])


def interactive_user(request: Request, user=Depends(current_user)):
    if request.headers.get("authorization"):
        raise HTTPException(
            403, "Manage account settings using a signed-in browser session"
        )
    return user


def profile_row(db, user):
    row = db.get(UserProfile, user.id)
    if not row:
        row = UserProfile(
            user_id=user.id,
            details="{}",
            avatar="",
            avatar_type="",
            visibility="public",
        )
        db.add(row)
    return row


class ProfileInput(BaseModel):
    display_name: str = Field(default="", max_length=80)
    tagline: str = Field(default="", max_length=160)
    pronouns: str = Field(default="", max_length=40)
    occupation: str = Field(default="", max_length=100)
    organization: str = Field(default="", max_length=100)
    location: str = Field(default="", max_length=120)
    bio: str = Field(default="", max_length=5000)
    website: Optional[HttpUrl] = None


def profile_info(db, user):
    row = db.get(UserProfile, user.id)
    return {
        "username": user.username,
        "joined_at": user.created_at,
        **ProfileInput().model_dump(),
        **(json.loads(row.details) if row else {}),
        "avatar_url": (
            f"/api/profiles/{user.username}/avatar" if row and row.avatar else None
        ),
        "visibility": row.visibility if row else "public",
    }


def visible_profile(db, username, visitor):
    user = db.scalar(select(User).where(User.username == username.lower()))
    row = db.get(UserProfile, user.id) if user else None
    if not user or (
        row and row.visibility == "private" and (not visitor or visitor.id != user.id)
    ):
        raise HTTPException(404, "Profile not found")
    return user


@router.get("/account/profile")
def my_profile(user=Depends(interactive_user), db: DBSession = Depends(get_db)):
    return profile_info(db, user)


@router.put("/account/profile")
def update_profile(
    data: ProfileInput, user=Depends(interactive_user), db: DBSession = Depends(get_db)
):
    db.refresh(user, with_for_update=True)
    profile_row(db, user).details = json.dumps(data.model_dump(mode="json"))
    db.commit()
    return profile_info(db, user)


@router.get("/profiles/{username}")
def public_profile(
    username: str, user=Depends(optional_user), db: DBSession = Depends(get_db)
):
    return profile_info(db, visible_profile(db, username, user))


@router.get("/profiles/{username}/avatar")
def avatar(username: str, user=Depends(optional_user), db: DBSession = Depends(get_db)):
    owner = visible_profile(db, username, user)
    row = db.get(UserProfile, owner.id)
    if not row or not row.avatar:
        raise HTTPException(404, "No profile photo")
    return Response(
        base64.b64decode(row.avatar),
        media_type=row.avatar_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.put("/account/avatar")
async def update_avatar(
    file: UploadFile = File(...),
    user=Depends(interactive_user),
    db: DBSession = Depends(get_db),
):
    content = await file.read(2 * 1024 * 1024 + 1)
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(413, "Profile photo must be at most 2 MB")
    mime = (
        "image/png"
        if content.startswith(b"\x89PNG\r\n\x1a\n")
        else "image/jpeg" if content.startswith(b"\xff\xd8\xff") else None
    )
    if not mime:
        raise HTTPException(422, "Choose a PNG or JPEG photo")
    db.refresh(user, with_for_update=True)
    row = profile_row(db, user)
    row.avatar, row.avatar_type = base64.b64encode(content).decode(), mime
    db.commit()
    return profile_info(db, user)


@router.delete("/account/avatar", status_code=204)
def delete_avatar(user=Depends(interactive_user), db: DBSession = Depends(get_db)):
    db.refresh(user, with_for_update=True)
    row = profile_row(db, user)
    row.avatar, row.avatar_type = "", ""
    db.commit()


class SettingsInput(BaseModel):
    visibility: Literal["public", "private"]


@router.put("/account/settings")
def settings(
    data: SettingsInput, user=Depends(interactive_user), db: DBSession = Depends(get_db)
):
    db.refresh(user, with_for_update=True)
    profile_row(db, user).visibility = data.visibility
    db.commit()
    return {"visibility": data.visibility}


class PasswordInput(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


@router.put("/account/password")
def password(
    data: PasswordInput,
    response: Response,
    user=Depends(interactive_user),
    db: DBSession = Depends(get_db),
):
    db.refresh(user, with_for_update=True)
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(403, "Current password is incorrect")
    user.password_hash = hash_password(data.new_password)
    db.execute(delete(Session).where(Session.user_id == user.id))
    db.execute(delete(ApiToken).where(ApiToken.user_id == user.id))
    new_session(db, user, response)
    return {"changed": True}


class TokenInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    scope: Literal["read", "read-write"] = "read"
    days: int = Field(default=30, ge=1, le=365)


@router.get("/account/tokens")
def tokens(user=Depends(interactive_user), db: DBSession = Depends(get_db)):
    return [
        {
            key: getattr(row, key)
            for key in (
                "id",
                "name",
                "prefix",
                "scope",
                "created_at",
                "expires_at",
                "last_used_at",
            )
        }
        for row in db.scalars(
            select(ApiToken)
            .where(ApiToken.user_id == user.id)
            .order_by(ApiToken.id.desc())
        )
    ]


@router.post("/account/tokens", status_code=201)
def create_token(
    data: TokenInput, user=Depends(interactive_user), db: DBSession = Depends(get_db)
):
    db.refresh(user, with_for_update=True)
    if len(tokens(user, db)) >= 25:
        raise HTTPException(
            409, "Revoke an existing token before creating another (limit 25)"
        )
    secret = "arena_" + secrets.token_urlsafe(32)
    row = ApiToken(
        user_id=user.id,
        name=data.name,
        scope=data.scope,
        prefix=secret[:12],
        token_hash=hashlib.sha256(secret.encode()).hexdigest(),
        expires_at=time.time() + data.days * 86400,
    )
    db.add(row)
    db.commit()
    return {"id": row.id, "token": secret, "expires_at": row.expires_at}


@router.delete("/account/tokens/{id}", status_code=204)
def revoke_token(
    id: int, user=Depends(interactive_user), db: DBSession = Depends(get_db)
):
    row = db.get(ApiToken, id)
    if not row or row.user_id != user.id:
        raise HTTPException(404, "Token not found")
    db.delete(row)
    db.commit()


class GroupInput(BaseModel):
    name: str = Field(min_length=3, max_length=80)
    description: str = Field(default="", max_length=1000)


def group_owned(db, id, user):
    row = db.scalar(select(UserGroup).where(UserGroup.id == id).with_for_update())
    if not row or row.owner_id != user.id:
        raise HTTPException(404, "Your group was not found")
    return row


@router.get("/account/groups")
def groups(user=Depends(interactive_user), db: DBSession = Depends(get_db)):
    result = []
    for row in db.scalars(
        select(UserGroup)
        .join(GroupMember)
        .where(GroupMember.user_id == user.id)
        .order_by(UserGroup.id.desc())
    ):
        members = list(
            db.scalars(
                select(User).join(GroupMember).where(GroupMember.group_id == row.id)
            )
        )
        result.append(
            {
                "id": row.id,
                "name": row.name,
                "description": row.description,
                "owner_id": row.owner_id,
                "invite_code": row.invite_code if row.owner_id == user.id else None,
                "members": [{"id": m.id, "username": m.username} for m in members],
            }
        )
    return result


@router.post("/account/groups", status_code=201)
def create_group(
    data: GroupInput, user=Depends(interactive_user), db: DBSession = Depends(get_db)
):
    row = UserGroup(
        owner_id=user.id, **data.model_dump(), invite_code=secrets.token_urlsafe(24)
    )
    db.add(row)
    db.flush()
    db.add(GroupMember(group_id=row.id, user_id=user.id))
    db.commit()
    return {"id": row.id}


class InviteInput(BaseModel):
    code: str = Field(min_length=1, max_length=80)


@router.post("/account/groups/join")
def join_group(
    data: InviteInput, user=Depends(interactive_user), db: DBSession = Depends(get_db)
):
    row = db.scalar(
        select(UserGroup)
        .where(UserGroup.invite_code == data.code.strip())
        .with_for_update()
    )
    if not row:
        raise HTTPException(404, "Invalid invite code")
    if not db.get(GroupMember, (row.id, user.id)):
        db.add(GroupMember(group_id=row.id, user_id=user.id))
        db.commit()
    return {"id": row.id}


@router.put("/account/groups/{id}")
def update_group(
    id: int,
    data: GroupInput,
    user=Depends(interactive_user),
    db: DBSession = Depends(get_db),
):
    row = group_owned(db, id, user)
    row.name, row.description = data.name, data.description
    db.commit()
    return {"updated": True}


@router.post("/account/groups/{id}/invite")
def rotate_invite(
    id: int, user=Depends(interactive_user), db: DBSession = Depends(get_db)
):
    row = group_owned(db, id, user)
    row.invite_code = secrets.token_urlsafe(24)
    db.commit()
    return {"invite_code": row.invite_code}


@router.delete("/account/groups/{id}/members/{member_id}", status_code=204)
def leave_group(
    id: int,
    member_id: int,
    user=Depends(interactive_user),
    db: DBSession = Depends(get_db),
):
    row = db.scalar(select(UserGroup).where(UserGroup.id == id).with_for_update())
    if not row or (row.owner_id != user.id and member_id != user.id):
        raise HTTPException(404, "Group membership not found")
    if member_id == row.owner_id:
        raise HTTPException(409, "The owner must delete the group instead of leaving")
    member = db.get(GroupMember, (id, member_id))
    if member:
        db.delete(member)
        db.commit()


@router.delete("/account/groups/{id}", status_code=204)
def delete_group(
    id: int, user=Depends(interactive_user), db: DBSession = Depends(get_db)
):
    row = group_owned(db, id, user)
    db.execute(delete(GroupMember).where(GroupMember.group_id == id))
    db.delete(row)
    db.commit()


@router.get("/account/notifications")
def notifications(user=Depends(interactive_user), db: DBSession = Depends(get_db)):
    rows = db.scalars(
        select(ServiceNotice)
        .where(or_(ServiceNotice.user_id == None, ServiceNotice.user_id == user.id))
        .order_by(ServiceNotice.id.desc())
        .limit(100)
    )
    return [
        {
            "id": row.id,
            "title": row.title,
            "body": row.body,
            "created_at": row.created_at,
            "read": db.get(NoticeRead, (row.id, user.id)) is not None,
        }
        for row in rows
    ]


@router.post("/account/notifications/{id}/read", status_code=204)
def read_notice(
    id: int, user=Depends(interactive_user), db: DBSession = Depends(get_db)
):
    row = db.get(ServiceNotice, id)
    if not row or (row.user_id is not None and row.user_id != user.id):
        raise HTTPException(404, "Notification not found")
    # Lock the user so duplicate read requests are idempotent on PostgreSQL.
    db.refresh(user, with_for_update=True)
    if not db.get(NoticeRead, (id, user.id)):
        db.add(NoticeRead(notice_id=id, user_id=user.id))
        db.commit()
