"""Owner-only immutable history and explicit restoration into private work."""

import json
from typing import Literal
from pydantic import BaseModel, Field, field_validator
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .auth import current_user
from .db import get_db
from .models import Notebook, NotebookVersion, NotebookWorkingCopy

router = APIRouter(prefix="/api/code", tags=["Notebook history"])


def save_version(db, notebook, document):
    encoded = json.dumps(document, sort_keys=True)
    previous = db.scalar(
        select(NotebookVersion)
        .where(NotebookVersion.notebook_id == notebook.id)
        .order_by(NotebookVersion.id.desc())
        .limit(1)
    )
    if previous and previous.document == encoded:
        return previous
    version = NotebookVersion(
        notebook_id=notebook.id, owner_id=notebook.owner_id, document=encoded
    )
    db.add(version)
    return version


def owned(db, id, user):
    notebook = db.scalar(select(Notebook).where(Notebook.id == id).with_for_update())
    if not notebook or notebook.owner_id != user.id:
        raise HTTPException(404, "Your notebook was not found")
    return notebook


@router.get("/{id}/versions")
def versions(
    id: int,
    before: int = Query(default=2147483647, ge=1),
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    owned(db, id, user)
    return [
        {
            "id": row.id,
            "created_at": row.created_at,
            "label": json.loads(row.document).get("metadata", {}).get("arena_version"),
        }
        for row in db.scalars(
            select(NotebookVersion)
            .where(NotebookVersion.notebook_id == id, NotebookVersion.id < before)
            .order_by(NotebookVersion.id.desc())
            .limit(50)
        )
    ]


@router.get("/{id}/versions/count")
def version_count(id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    owned(db, id, user)
    return {
        "count": db.scalar(
            select(func.count())
            .select_from(NotebookVersion)
            .where(NotebookVersion.notebook_id == id)
        )
    }


@router.get("/{id}/versions/{version_id}")
def version_document(
    id: int, version_id: int, user=Depends(current_user), db: Session = Depends(get_db)
):
    owned(db, id, user)
    version = db.get(NotebookVersion, version_id)
    if not version or version.notebook_id != id:
        raise HTTPException(404, "Version not found")
    return json.loads(version.document)


class VisibilityInput(BaseModel):
    visibility: Literal["private", "public"]


@router.put("/{id}/visibility")
def set_visibility(
    id: int,
    data: VisibilityInput,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    from .models import NotebookPublication

    notebook = owned(db, id, user)
    working = db.get(NotebookWorkingCopy, id)
    publication = db.get(NotebookPublication, id)
    if data.visibility == "public" and not publication:
        raise HTTPException(
            409, "Publish the notebook explicitly before making it public"
        )
    if not working:
        from .notebook_runtime import notebook_document

        working = NotebookWorkingCopy(
            notebook_id=id, document=json.dumps(notebook_document(notebook, db))
        )
        db.add(working)
    working.private = int(data.visibility == "private")
    db.commit()
    return {"private": bool(working.private)}


class VersionLabel(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    tags: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value):
        if not value.strip():
            raise ValueError("Enter a version name")
        return value.strip()

    @field_validator("tags")
    @classmethod
    def valid_tags(cls, values):
        if any(not value.strip() or len(value) > 30 for value in values):
            raise ValueError("Tags must contain 1–30 characters")
        return list(dict.fromkeys(value.strip() for value in values))


@router.patch("/{id}/versions/{version_id}")
def label_version(
    id: int,
    version_id: int,
    data: VersionLabel,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    owned(db, id, user)
    row = db.get(NotebookVersion, version_id)
    if not row or row.notebook_id != id:
        raise HTTPException(404, "Version not found")
    document = json.loads(row.document)
    document.setdefault("metadata", {})["arena_version"] = data.model_dump()
    row.document = json.dumps(document, sort_keys=True)
    db.commit()
    return data.model_dump()


class ShareSettingsInput(BaseModel):
    visibility: Literal["private", "public"]
    usernames: list[str] = Field(default_factory=list, max_length=100)
    allow_comments: bool = True


@router.get("/{id}/share-settings")
def share_settings(id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    from .models import NotebookSettings, NotebookShare, User

    owned(db, id, user)
    working = db.get(NotebookWorkingCopy, id)
    settings = db.get(NotebookSettings, id)
    return {
        "visibility": "private" if working and working.private else "public",
        "allow_comments": bool(settings.allow_comments) if settings else True,
        "owner": user.username,
        "usernames": list(
            db.scalars(
                select(User.username)
                .join(NotebookShare, NotebookShare.user_id == User.id)
                .where(NotebookShare.notebook_id == id)
            )
        ),
    }


@router.put("/{id}/share-settings")
def update_share_settings(
    id: int,
    data: ShareSettingsInput,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    from sqlalchemy import delete
    from .models import (
        NotebookSettings,
        NotebookShare,
        NotebookPublication,
        User,
        CompetitionResource,
    )
    from .notebook_editor import Document
    from .code_pages import store_publication

    notebook = owned(db, id, user)
    working = db.get(NotebookWorkingCopy, id)
    if not working:
        raise HTTPException(409, "Save the notebook before sharing")
    names = set(name.strip() for name in data.usernames) - {user.username}
    recipients = list(db.scalars(select(User).where(User.username.in_(names))))
    if {recipient.username for recipient in recipients} != names:
        raise HTTPException(422, "One or more usernames do not exist")
    if data.visibility == "public" and working.private:
        competition = working.competition_id or db.scalar(
            select(CompetitionResource.id).where(
                CompetitionResource.kind == "notebooks",
                CompetitionResource.resource_id == id,
            )
        )
        if competition and not db.get(NotebookPublication, id):
            raise HTTPException(
                409,
                "Commit and successfully evaluate competition code before making it public",
            )
        if not competition:
            store_publication(
                db, notebook, Document.model_validate_json(working.document)
            )
    working.private = int(data.visibility == "private")
    db.execute(delete(NotebookShare).where(NotebookShare.notebook_id == id))
    for recipient in recipients:
        db.add(NotebookShare(notebook_id=id, user_id=recipient.id))
    settings = db.get(NotebookSettings, id)
    if not settings:
        settings = NotebookSettings(notebook_id=id)
        db.add(settings)
    settings.allow_comments = int(data.allow_comments)
    db.commit()
    return share_settings(id, user, db)
