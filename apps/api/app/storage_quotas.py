"""Per-user storage quotas for dataset and model files.

Usage is the size of every stored blob a user owns (dataset-version files, model-
version files and legacy supplemental files) plus the bytes received so far by their
unfinished uploads. A blob that several versions share is counted once; uploading
identical bytes again stores and counts a new blob. Files in a resource are charged
to the resource owner, even when an administrator uploads them.

Enforcement is conservative: a new upload session must fit next to the full declared
size of the owner's other unfinished sessions, and completing one must still fit.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from .auth import current_user
from .db import get_db
from .file_store import STORES
from .models import (
    ArtifactVersion,
    Dataset,
    ResourceVersionFile,
    StoredFile,
    UploadSession,
    User,
    UserStorageQuota,
    WorkFileDeletion,
)
from .moderation import record
from .pagination import Page, page, set_total, window
from .permissions import require_admin
from .site_settings import setting

router = APIRouter(prefix="/api", tags=["Storage"])
GIB = 1024**3
ACTIVE = ("uploading", "assembling")


def quota_bytes(db, user_id):
    override = db.get(UserStorageQuota, user_id)
    if override:
        return int(override.quota_bytes)
    return int(float(setting(db, "storage_quota_gib")) * GIB)


def stored_bytes(db, user_id):
    return int(
        db.scalar(
            select(func.coalesce(func.sum(StoredFile.size), 0)).where(
                StoredFile.owner_id == user_id
            )
        )
    )


def upload_bytes(db, user_id, declared=False, exclude=None):
    """Received bytes of unfinished uploads, or their full declared sizes."""
    column = UploadSession.total_size if declared else UploadSession.received_bytes
    query = select(func.coalesce(func.sum(column), 0)).where(
        UploadSession.owner_id == user_id, UploadSession.status.in_(ACTIVE)
    )
    if exclude:
        query = query.where(UploadSession.id != exclude)
    return int(db.scalar(query))


def usage_json(db, user_id):
    quota, stored = quota_bytes(db, user_id), stored_bytes(db, user_id)
    parts, reserved = upload_bytes(db, user_id), upload_bytes(db, user_id, True)
    return {
        "quota_bytes": quota,
        "stored_bytes": stored,
        "upload_bytes": parts,
        "used_bytes": stored + parts,
        # Declared sizes of unfinished uploads, held until they finish or expire.
        "reserved_bytes": reserved,
        "available_bytes": max(0, quota - stored - reserved),
        "custom_quota": db.get(UserStorageQuota, user_id) is not None,
    }


def gib(value):
    return f"{value / GIB:.2f} GiB"


def require_capacity(db, owner_id, size, session_id=None, reserved=True):
    """Refuse `size` more bytes for the owner; locks the owner row against races."""
    db.scalar(select(User.id).where(User.id == owner_id).with_for_update())
    quota = quota_bytes(db, owner_id)
    used = stored_bytes(db, owner_id)
    if reserved:
        used += upload_bytes(db, owner_id, True, exclude=session_id)
    if used + size > quota:
        raise HTTPException(
            413,
            f"This file needs {gib(size)} but only {gib(max(0, quota - used))} of the"
            f" {gib(quota)} storage quota is available. Delete versions or ask an"
            " administrator for more space.",
        )


def release_files(db, file_ids, cleanup_owner, keep_primary=True):
    """Delete stored blobs no version references any more and queue their removal.

    Returns {(store, key): WorkFileDeletion}. Unless the whole dataset is being
    deleted, a blob that is still a dataset's legacy primary CSV is kept. Legacy
    supplemental file-version rows for a removed blob are deleted with it.
    """
    scheduled = {}
    for file_id in sorted(set(file_ids)):
        row = db.get(StoredFile, file_id)
        if not row or db.scalar(
            select(ResourceVersionFile.id)
            .where(ResourceVersionFile.file_id == file_id)
            .limit(1)
        ):
            continue
        if (
            keep_primary
            and row.store == "uploads"
            and db.scalar(
                select(Dataset.id)
                .where(Dataset.storage_key == row.storage_key)
                .limit(1)
            )
        ):
            continue
        if row.store == "artifacts":
            for legacy in db.scalars(
                select(ArtifactVersion).where(
                    ArtifactVersion.storage_key == row.storage_key
                )
            ):
                db.delete(legacy)
        if (row.store, row.storage_key) not in scheduled:
            task = WorkFileDeletion(
                owner_id=cleanup_owner, kind=STORES[row.store], path=row.storage_key
            )
            scheduled[(row.store, row.storage_key)] = task
            db.add(task)
        db.delete(row)
    db.flush()
    return scheduled


@router.get("/storage/usage")
def my_usage(user=Depends(current_user), db=Depends(get_db)):
    return usage_json(db, user.id)


@router.get("/admin/storage", dependencies=[Depends(require_admin)])
def all_usage(
    response: Response,
    q: str = Query("", max_length=40),
    pagination: Page = Depends(page),
    db=Depends(get_db),
):
    """Every user's storage, largest first."""
    stored = (
        select(StoredFile.owner_id, func.sum(StoredFile.size).label("bytes"))
        .group_by(StoredFile.owner_id)
        .subquery()
    )
    parts = (
        select(
            UploadSession.owner_id,
            func.sum(UploadSession.received_bytes).label("bytes"),
        )
        .where(UploadSession.status.in_(ACTIVE))
        .group_by(UploadSession.owner_id)
        .subquery()
    )
    stored_total = func.coalesce(stored.c.bytes, 0)
    parts_total = func.coalesce(parts.c.bytes, 0)
    matching = User.username.icontains(q.strip(), autoescape=True)
    set_total(
        response, db.scalar(select(func.count()).select_from(User).where(matching))
    )
    query = (
        select(User.id, User.username, stored_total, parts_total)
        .outerjoin(stored, stored.c.owner_id == User.id)
        .outerjoin(parts, parts.c.owner_id == User.id)
        .where(matching)
        .order_by((stored_total + parts_total).desc(), User.id)
    )
    default = quota_bytes(db, -1)
    overrides = dict(
        db.execute(select(UserStorageQuota.user_id, UserStorageQuota.quota_bytes)).all()
    )
    return [
        {
            "user_id": id,
            "username": username,
            "stored_bytes": int(stored_value),
            "upload_bytes": int(parts_value),
            "used_bytes": int(stored_value) + int(parts_value),
            "quota_bytes": int(overrides.get(id, default)),
            "custom_quota": id in overrides,
        }
        for id, username, stored_value, parts_value in db.execute(
            window(query, pagination)
        )
    ]


class QuotaInput(BaseModel):
    # Null restores the site default.
    quota_gib: Optional[float] = Field(default=None, ge=0, le=1048576)


@router.put("/admin/users/{id}/storage-quota")
def set_quota(
    id: int, data: QuotaInput, admin=Depends(require_admin), db=Depends(get_db)
):
    user = db.scalar(select(User).where(User.id == id).with_for_update())
    if not user:
        raise HTTPException(404, "User not found")
    row = db.get(UserStorageQuota, id)
    before = row.quota_bytes if row else None
    after = None if data.quota_gib is None else int(data.quota_gib * GIB)
    if before != after:
        if after is None:
            db.delete(row)
        elif row:
            row.quota_bytes = after
        else:
            db.add(UserStorageQuota(user_id=id, quota_bytes=after))
        record(
            db,
            admin,
            "user.storage_quota",
            "user",
            id,
            {"username": user.username, "from_bytes": before, "to_bytes": after},
        )
        db.commit()
    return {"user_id": id, "username": user.username, **usage_json(db, id)}
