"""Cursor-paginated code discovery and explicit public notebook snapshots."""

import copy
import json
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from .auth import current_user
from .db import get_db
from .models import (
    Notebook,
    NotebookWorkingCopy,
    NotebookComment,
    NotebookPublication,
    NotebookBookmark,
    NotebookShare,
    Competition,
    CompetitionResource,
    ModelCard,
    ChallengeDetails,
    Dataset,
    User,
)
from .notebook_visibility import visible_notebooks, require_visible
from .notebook_editor import Document
from .notebook_runtime import notebook_document

router = APIRouter(prefix="/api", tags=["Code library"])


def optional_user(request: Request, db: Session = Depends(get_db)):
    try:
        return current_user(request, db)
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
        return None


def require_notebook(db, id, owner=None):
    row = (
        db.scalar(select(Notebook).where(Notebook.id == id).with_for_update())
        if owner
        else db.get(Notebook, id)
    )
    if not row:
        raise HTTPException(404, "Code not found")
    if owner and row.owner_id != owner.id:
        raise HTTPException(403, "Only the author can publish or share this code")
    return row


@router.get("/code")
def list_code(
    competition_id: Optional[int] = None,
    filter: Literal["all", "your-work", "shared", "bookmarks"] = "all",
    q: str = Query(default="", max_length=160),
    cursor: Optional[int] = Query(default=None, ge=1),
    limit: int = Query(default=20, ge=1, le=50),
    user=Depends(optional_user),
    db: Session = Depends(get_db),
):
    if filter != "all" and not user:
        raise HTTPException(401, "Sign in to see your code library")
    query = (
        select(
            Notebook.id,
            Notebook.title,
            Notebook.description,
            Notebook.owner_id,
            Notebook.created_at,
            User.username.label("owner"),
        )
        .join(User, User.id == Notebook.owner_id)
        .where(visible_notebooks(user))
    )
    if competition_id is not None:
        if not db.get(Competition, competition_id):
            raise HTTPException(404, "Competition not found")
        query = query.where(
            select(CompetitionResource.id)
            .where(
                CompetitionResource.competition_id == competition_id,
                CompetitionResource.kind == "notebooks",
                CompetitionResource.resource_id == Notebook.id,
            )
            .exists()
        )
    if filter == "your-work":
        query = query.where(Notebook.owner_id == user.id)
    elif filter == "shared":
        query = query.where(
            select(NotebookShare.user_id)
            .where(
                NotebookShare.user_id == user.id,
                NotebookShare.notebook_id == Notebook.id,
            )
            .exists()
        )
    elif filter == "bookmarks":
        query = query.where(
            select(NotebookBookmark.user_id)
            .where(
                NotebookBookmark.user_id == user.id,
                NotebookBookmark.notebook_id == Notebook.id,
            )
            .exists()
        )
    if q.strip():
        query = query.where(Notebook.title.icontains(q.strip(), autoescape=True))
    if cursor:
        query = query.where(Notebook.id < cursor)
    rows = (
        db.execute(query.order_by(Notebook.id.desc()).limit(limit + 1)).mappings().all()
    )
    page = rows[:limit]
    bookmarks = (
        set(
            db.scalars(
                select(NotebookBookmark.notebook_id).where(
                    NotebookBookmark.user_id == user.id,
                    NotebookBookmark.notebook_id.in_([row["id"] for row in page]),
                )
            )
        )
        if user
        else set()
    )
    return {
        "items": [
            {
                **dict(row),
                "description": (row["description"] or "")[:300],
                "bookmarked": row["id"] in bookmarks,
            }
            for row in page
        ],
        "next_cursor": page[-1]["id"] if len(rows) > limit else None,
    }


def publication_document(db, row):
    publication = db.get(NotebookPublication, row.id)
    return json.loads(publication.document) if publication else notebook_document(row)


@router.get("/code/{id}")
def view_code(id: int, user=Depends(optional_user), db: Session = Depends(get_db)):
    row = require_visible(db, id, user)
    working = db.get(NotebookWorkingCopy, id)
    publication = db.get(NotebookPublication, id)
    document = (
        json.loads(working.document)
        if working and working.private
        else publication_document(db, row)
    )
    inputs = []
    for item in document.get("metadata", {}).get("arena_inputs", []):
        from .dataset_access import visible_datasets

        dataset = db.scalar(
            select(Dataset).where(Dataset.id == item["id"], visible_datasets(user))
        )
        inputs.append(
            {
                "id": item["id"],
                "title": (
                    dataset.title if dataset else item.get("title", "Unavailable input")
                ),
                "available": dataset is not None,
                "filename": item.get("filename", ""),
            }
        )
    return {
        "id": row.id,
        "title": row.title,
        "description": row.description,
        "owner_id": row.owner_id,
        "owner": db.get(User, row.owner_id).username,
        "created_at": row.created_at,
        "working_competition_id": (
            working.competition_id
            if working and user and user.id == row.owner_id
            else None
        ),
        "private": bool(working and working.private),
        "published_at": publication.updated_at if publication else None,
        "forked_from": (
            working.forked_from
            if working
            else publication.forked_from if publication else None
        ),
        "document": document,
        "inputs": inputs,
        "bookmarked": bool(user and db.get(NotebookBookmark, (user.id, id))),
        "competitions": [
            {"id": competition.id, "title": competition.title}
            for competition in db.scalars(
                select(Competition)
                .join(
                    CompetitionResource,
                    CompetitionResource.competition_id == Competition.id,
                )
                .where(
                    CompetitionResource.kind == "notebooks",
                    CompetitionResource.resource_id == id,
                )
            )
        ],
    }


@router.put("/code/{id}/bookmark")
def bookmark(id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    require_visible(db, id, user)
    row = db.scalar(select(Notebook).where(Notebook.id == id).with_for_update())
    if not row:
        raise HTTPException(404, "Code not found")
    if not db.get(NotebookBookmark, (user.id, id)):
        db.add(NotebookBookmark(user_id=user.id, notebook_id=id))
    db.commit()
    return {"bookmarked": True}


@router.delete("/code/{id}/bookmark")
def unbookmark(id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    row = db.get(NotebookBookmark, (user.id, id))
    if row:
        db.delete(row)
        db.commit()
    return {"bookmarked": False}


class ShareInput(BaseModel):
    username: str = Field(min_length=3, max_length=40)


@router.get("/code/{id}/shares")
def shares(id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    require_notebook(db, id, user)
    return [
        {"id": row.id, "username": row.username}
        for row in db.scalars(
            select(User)
            .join(NotebookShare, NotebookShare.user_id == User.id)
            .where(NotebookShare.notebook_id == id)
        )
    ]


@router.post("/code/{id}/shares", status_code=201)
def share(
    id: int, data: ShareInput, user=Depends(current_user), db: Session = Depends(get_db)
):
    require_notebook(db, id, user)
    recipient = db.scalar(select(User).where(User.username == data.username.strip()))
    if not recipient:
        raise HTTPException(404, "No user has that username")
    if recipient.id == user.id:
        raise HTTPException(
            422, "Choose another user; your code already appears in Your work"
        )
    if not db.get(NotebookShare, (id, recipient.id)):
        db.add(NotebookShare(notebook_id=id, user_id=recipient.id))
    db.commit()
    return {"shared": True}


@router.delete("/code/{id}/shares/{user_id}")
def revoke_share(
    id: int, user_id: int, user=Depends(current_user), db: Session = Depends(get_db)
):
    require_notebook(db, id, user)
    row = db.get(NotebookShare, (id, user_id))
    if row:
        db.delete(row)
        db.commit()
    return {"shared": False}


@router.put("/code/{id}/publication")
def publish_code(
    id: int, data: Document, user=Depends(current_user), db: Session = Depends(get_db)
):
    row = require_notebook(db, id, user)
    working = db.get(NotebookWorkingCopy, id)
    if (working and working.competition_id) or db.scalar(
        select(CompetitionResource.id).where(
            CompetitionResource.kind == "notebooks",
            CompetitionResource.resource_id == id,
        )
    ):
        raise HTTPException(409, "Use Save & Commit to evaluate competition code")
    store_publication(db, row, data)
    if working:
        working.private = 0
        working.document = db.get(NotebookPublication, id).document
    db.commit()
    return {"published": True}


def store_publication(db, row, data):
    """Store a portable full notebook snapshot within the caller's transaction."""
    document = data.model_dump()
    for cell in document["cells"]:
        cell.setdefault("source", "")
        count = cell.get("execution_count")
        if count is not None and (
            not isinstance(count, int) or isinstance(count, bool)
        ):
            raise HTTPException(422, "Execution counts must be integers or null")
    # Retain only portable, public input references; never runtime connection metadata.
    inputs = []
    proposed = document.get("metadata", {}).get("arena_inputs", [])
    if not isinstance(proposed, list):
        raise HTTPException(422, "Inputs must be a list")
    for item in proposed:
        if not isinstance(item, dict) or not isinstance(item.get("id"), int):
            raise HTTPException(422, "Each input needs a dataset ID")
        from .dataset_access import visibility

        if visibility(db, item["id"]) != "public":
            raise HTTPException(
                422,
                "Publish attached datasets or remove their references before publishing this notebook",
            )
        dataset = db.get(Dataset, item["id"])
        if not dataset:
            raise HTTPException(422, "Remove unavailable datasets before publishing")
        if not any(entry["id"] == dataset.id for entry in inputs):
            inputs.append(
                {"id": dataset.id, "title": dataset.title, "filename": dataset.filename}
            )
    document["metadata"] = {
        "kernelspec": {
            "name": "python3",
            "display_name": "Python 3",
            "language": "python",
        },
        "arena_inputs": inputs,
    }
    publication = db.get(NotebookPublication, row.id)
    if not publication:
        publication = NotebookPublication(notebook_id=row.id)
        db.add(publication)
    from .notebook_versions import save_version

    publication.document = json.dumps(document)
    save_version(db, row, document)
    row.code = "\n\n".join(
        "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]
        for cell in document["cells"]
        if cell["cell_type"] == "code"
    )


@router.post("/code/{id}/fork", status_code=201)
def fork_code(
    id: int,
    competition_id: Optional[int] = None,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    source = require_visible(db, id, user)
    if competition_id and not db.get(Competition, competition_id):
        raise HTTPException(404, "Competition not found")
    if competition_id is None:
        competition_id = db.scalar(
            select(CompetitionResource.competition_id)
            .where(
                CompetitionResource.kind == "notebooks",
                CompetitionResource.resource_id == id,
            )
            .order_by(CompetitionResource.id)
        )
    row = Notebook(
        owner_id=user.id,
        title=("Fork of " + source.title)[:160],
        description=source.description,
        code=source.code,
    )
    db.add(row)
    db.flush()
    original = db.get(NotebookWorkingCopy, id)
    document = (
        json.loads(original.document)
        if original and original.private
        else publication_document(db, source)
    )
    db.add(
        NotebookWorkingCopy(
            notebook_id=row.id,
            forked_from=source.id,
            competition_id=competition_id,
            document=json.dumps(document),
            private=1,
        )
    )
    db.commit()
    return {"id": row.id, "title": row.title, "owner_id": row.owner_id}


@router.get("/work/status")
def work_status(user=Depends(current_user), db: Session = Depends(get_db)):
    return {
        "has_work": any(
            db.scalar(
                select(
                    model.id if model is not ChallengeDetails else model.competition_id
                )
                .where(model.owner_id == user.id)
                .limit(1)
            )
            is not None
            for model in (Notebook, Dataset, ModelCard, ChallengeDetails)
        )
    }


class NotebookCommentInput(BaseModel):
    body: str = Field(min_length=1, max_length=10000)


@router.get("/code/{id}/comments")
def code_comments(
    id: int,
    after: int = Query(0, ge=0),
    user=Depends(optional_user),
    db: Session = Depends(get_db),
):
    require_visible(db, id, user)
    rows = db.execute(
        select(NotebookComment, User.username)
        .join(User, User.id == NotebookComment.owner_id)
        .where(NotebookComment.notebook_id == id, NotebookComment.id > after)
        .order_by(NotebookComment.id)
        .limit(51)
    ).all()
    return {
        "items": [
            {
                "id": row.id,
                "owner_id": row.owner_id,
                "username": username,
                "body": row.body,
                "created_at": row.created_at,
            }
            for row, username in rows[:50]
        ],
        "next_cursor": rows[49][0].id if len(rows) > 50 else None,
    }


@router.post("/code/{id}/comments", status_code=201)
def add_code_comment(
    id: int,
    data: NotebookCommentInput,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    require_visible(db, id, user)
    body = data.body.strip()
    if not body:
        raise HTTPException(422, "Write a comment first")
    row = NotebookComment(notebook_id=id, owner_id=user.id, body=body)
    db.add(row)
    db.commit()
    return {
        "id": row.id,
        "owner_id": user.id,
        "username": user.username,
        "body": row.body,
        "created_at": row.created_at,
    }


@router.delete("/code/{id}/comments/{comment_id}", status_code=204)
def delete_code_comment(
    id: int, comment_id: int, user=Depends(current_user), db: Session = Depends(get_db)
):
    require_visible(db, id, user)
    row = db.get(NotebookComment, comment_id)
    if not row or row.notebook_id != id:
        raise HTTPException(404, "Comment not found")
    if row.owner_id != user.id:
        raise HTTPException(403, "You can only delete your own comments")
    from .engagement import remove_engagement

    remove_engagement(db, "notebook-comment", [row.id])
    db.delete(row)
    db.commit()
