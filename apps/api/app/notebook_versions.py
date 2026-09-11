"""Owner-only immutable history and explicit restoration into private work."""

import json
from typing import Literal
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
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
        {"id": row.id, "created_at": row.created_at}
        for row in db.scalars(
            select(NotebookVersion)
            .where(NotebookVersion.notebook_id == id, NotebookVersion.id < before)
            .order_by(NotebookVersion.id.desc())
            .limit(50)
        )
    ]


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
