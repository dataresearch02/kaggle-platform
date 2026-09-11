"""Leased notebook files: autosave is temporary; explicit Save publishes a snapshot."""

import asyncio
import json
import logging
import secrets
import time
from functools import wraps
from typing import Optional
from weakref import WeakValueDictionary
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Response, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_user
from .db import SessionLocal, get_db
from .models import (
    Notebook,
    NotebookWorkingCopy,
    NotebookDraft,
    User,
    Competition,
    CompetitionResource,
    Entry,
)
from .notebook_runtime import HubClient, get_hub, hub_username, notebook_document

router = APIRouter(prefix="/api/notebook-drafts", tags=["Notebook drafts"])
LEASE_SECONDS = 180
_locks = WeakValueDictionary()


def user_lock(user_id):
    lock = _locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[user_id] = lock
    return lock


def serialized(function):
    @wraps(function)
    async def wrapper(*args, **kwargs):
        async with user_lock(kwargs["user"].id):
            return await function(*args, **kwargs)

    return wrapper


class DraftSave(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    competition_id: Optional[int] = Field(default=None, ge=1)


def joined_competition(db, competition_id, user):
    if competition_id is None:
        return
    competition = db.scalar(
        select(Competition).where(Competition.id == competition_id).with_for_update()
    )
    if not competition:
        raise HTTPException(404, "Competition not found")
    if not db.scalar(
        select(Entry.id).where(
            Entry.competition_id == competition_id, Entry.user_id == user.id
        )
    ):
        raise HTTPException(
            403, "Join the competition before creating or saving competition code"
        )


def owned(db, id, user):
    draft = db.scalar(
        select(NotebookDraft).where(NotebookDraft.id == id).with_for_update()
    )
    if not draft or draft.owner_id != user.id:
        raise HTTPException(404, "Draft not found")
    if draft.expires_at < time.time():
        raise HTTPException(410, "Draft expired. Create a new notebook.")
    return draft


def path_for(draft):
    return f"arena-draft-{draft.id}.ipynb"


def endpoint(user, path):
    return f"/user/{hub_username(user)}/api/contents/{path}"


@router.post("", status_code=201)
def create(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    competition_id: Optional[int] = Query(default=None, ge=1),
):
    joined_competition(db, competition_id, user)
    draft = NotebookDraft(
        id=secrets.token_hex(16),
        owner_id=user.id,
        expires_at=time.time() + LEASE_SECONDS,
    )
    db.add(draft)
    db.commit()
    return {"id": draft.id}


@router.post("/{id}/heartbeat")
@serialized
async def heartbeat(
    id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    draft = owned(db, id, user)
    draft.expires_at = time.time() + LEASE_SECONDS
    db.commit()
    return {"active": True}


@router.post("/{id}/open")
@serialized
async def open_draft(
    id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    hub: HubClient = Depends(get_hub),
):
    draft = owned(db, id, user)
    if (await hub.status(user))["state"] != "ready":
        raise HTTPException(409, "Wait for your notebook server to start")
    path = path_for(draft)
    response = await hub.request(
        "GET", endpoint(user, path), contents=True, params={"content": 0}
    )
    if response.status_code == 404:
        document = notebook_document(Notebook(id=draft.id, code=""))
        hub.expect(
            await hub.request(
                "PUT",
                endpoint(user, path),
                contents=True,
                json={"type": "notebook", "format": "json", "content": document},
            ),
            (200, 201),
        )
    else:
        hub.expect(response)
    draft.expires_at = time.time() + LEASE_SECONDS
    db.commit()
    return {
        "url": "/jupyter/hub/arena-login?"
        + urlencode({"next": f"/jupyter/user/{hub_username(user)}/lab/tree/{path}"})
    }


@router.post("/{id}/save")
@serialized
async def save(
    id: str,
    data: DraftSave,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    hub: HubClient = Depends(get_hub),
):
    draft = owned(db, id, user)
    if draft.notebook_id:
        db.scalar(
            select(Notebook).where(Notebook.id == draft.notebook_id).with_for_update()
        )
        working = db.get(NotebookWorkingCopy, draft.notebook_id)
        linked = set(
            db.scalars(
                select(CompetitionResource.competition_id).where(
                    CompetitionResource.kind == "notebooks",
                    CompetitionResource.resource_id == draft.notebook_id,
                )
            )
        )
        if working and working.competition_id:
            linked.add(working.competition_id)
        if linked and linked != {data.competition_id}:
            raise HTTPException(
                409,
                "Keep this notebook's competition context when saving; use Save & Commit to publish evaluated changes",
            )
    joined_competition(db, data.competition_id, user)
    response = await hub.request("GET", endpoint(user, path_for(draft)), contents=True)
    if response.status_code == 404:
        raise HTTPException(
            409, "The temporary file is unavailable. Reopen the draft before saving."
        )
    document = hub.expect(response).json()["content"]
    code = "\n\n".join(
        "".join(cell.get("source", []))
        for cell in document["cells"]
        if cell["cell_type"] == "code"
    )
    notebook = db.get(Notebook, draft.notebook_id) if draft.notebook_id else None
    if notebook is None:
        notebook = Notebook(
            owner_id=user.id, title=data.title, description="", code=code
        )
        db.add(notebook)
        db.flush()
        draft.notebook_id = notebook.id
    notebook.title = data.title
    notebook.code = code
    working = db.get(NotebookWorkingCopy, notebook.id)
    if not working:
        working = NotebookWorkingCopy(notebook_id=notebook.id, private=1)
        db.add(working)
    working.competition_id = data.competition_id
    working.document = json.dumps(document)
    from .notebook_versions import save_version

    save_version(db, notebook, document)
    # The working copy retains Markdown, metadata and outputs, not only template code.
    hub.expect(
        await hub.request(
            "PUT",
            endpoint(user, f"arena-notebook-{notebook.id}.ipynb"),
            contents=True,
            json={"type": "notebook", "format": "json", "content": document},
        ),
        (200, 201),
    )
    draft.expires_at = time.time() + LEASE_SECONDS
    db.commit()
    return {"id": notebook.id, "title": notebook.title}


async def remove_file(draft, user, hub):
    if (await hub.status(user))["state"] != "ready":
        return False
    # Shut down only this document's kernel before removing its temporary file.
    sessions = hub.expect(
        await hub.request(
            "GET", f"/user/{hub_username(user)}/api/sessions", contents=True
        )
    ).json()
    for session in sessions:
        if session.get("path") == path_for(draft):
            hub.expect(
                await hub.request(
                    "DELETE",
                    f"/user/{hub_username(user)}/api/sessions/{session['id']}",
                    contents=True,
                ),
                (204, 404),
            )
    hub.expect(
        await hub.request("DELETE", endpoint(user, path_for(draft)), contents=True),
        (204, 404),
    )
    return True


@router.delete("/{id}", status_code=204)
@serialized
async def discard(
    id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    hub: HubClient = Depends(get_hub),
):
    draft = db.get(NotebookDraft, id)
    if not draft or draft.owner_id != user.id:
        return Response(status_code=204)
    # Persist expiry first, so failures are retried by cleanup instead of losing track.
    draft.expires_at = 0
    db.commit()
    if await remove_file(draft, user, hub):
        db.delete(draft)
        db.commit()
    return Response(status_code=204)


async def cleanup_drafts():
    while True:
        await asyncio.sleep(30)
        try:
            hub = get_hub()
            with SessionLocal() as db:
                drafts = db.scalars(
                    select(NotebookDraft)
                    .where(NotebookDraft.expires_at < time.time())
                    .limit(100)
                ).all()
                for draft in drafts:
                    user = db.get(User, draft.owner_id)
                    try:
                        if user:
                            async with user_lock(user.id):
                                db.refresh(draft)
                                if draft.expires_at < time.time() and await remove_file(
                                    draft, user, hub
                                ):
                                    db.delete(draft)
                                    db.commit()
                    except HTTPException:
                        db.rollback()
        except HTTPException:
            pass  # Standalone API mode has no Hub.
        except Exception:
            logging.getLogger(__name__).exception("Draft cleanup failed; will retry")
