"""Explicit immutable file exports; never browse another user's live workspace."""

import base64
import hashlib
import re
import secrets
from typing import Optional
from pathlib import PurePosixPath
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, or_
from sqlalchemy.orm import Session
from .auth import current_user
from .db import DATA_DIR, get_db
from .models import Notebook, NotebookOutput
from .notebook_runtime import get_hub, hub_username
from .notebook_visibility import visible_notebooks, require_visible

router = APIRouter(prefix="/api", tags=["Notebook output files"])
LIMIT = 50 * 1024 * 1024


def readable(db, id, user):
    output = db.get(NotebookOutput, id)
    if not output or (output.owner_id != user.id and not output.shared):
        raise HTTPException(404, "Notebook output not found")
    require_visible(db, output.notebook_id, user)
    return output


def input_path(output):
    return f"input/notebooks/{output.id}/{output.filename}"


def describe(output, title):
    return {
        "id": output.id,
        "kind": "notebook-output",
        "notebook_id": output.notebook_id,
        "title": title,
        "filename": output.filename,
        "size": output.size,
        "sha256": output.sha256,
        "shared": bool(output.shared),
        "created_at": output.created_at,
        "path": input_path(output),
    }


@router.get("/notebook-outputs")
def list_outputs(
    q: str = Query("", max_length=160),
    before: int = Query(2147483647, ge=1),
    notebook_id: Optional[int] = None,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    query = (
        select(NotebookOutput, Notebook.title)
        .join(Notebook)
        .where(
            visible_notebooks(user),
            or_(NotebookOutput.owner_id == user.id, NotebookOutput.shared == 1),
            NotebookOutput.id < before,
        )
    )
    if notebook_id is not None:
        query = query.where(NotebookOutput.notebook_id == notebook_id)
    if q:
        query = query.where(
            or_(Notebook.title.ilike(f"%{q}%"), NotebookOutput.filename.ilike(f"%{q}%"))
        )
    rows = db.execute(query.order_by(NotebookOutput.id.desc()).limit(51)).all()
    return {
        "items": [describe(row, title) for row, title in rows[:50]],
        "next_cursor": rows[49][0].id if len(rows) > 50 else None,
    }


class ExportInput(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    shared: bool = False


@router.post("/code/{id}/outputs", status_code=201)
async def export_output(
    id: int,
    data: ExportInput,
    user=Depends(current_user),
    db: Session = Depends(get_db),
    hub=Depends(get_hub),
):
    notebook = db.get(Notebook, id)
    if not notebook or notebook.owner_id != user.id:
        raise HTTPException(404, "Your notebook was not found")
    path = PurePosixPath(data.path)
    if (
        path.is_absolute()
        or ".." in path.parts
        or "\\" in data.path
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,254}", path.name)
    ):
        raise HTTPException(422, "Use a relative workspace path and a simple filename")
    endpoint = f"/user/{hub_username(user)}/api/contents/{quote(str(path), safe='/')}"
    info = hub.expect(
        await hub.request("GET", endpoint, contents=True, params={"content": 0})
    ).json()
    if info.get("type") != "file" or info.get("size") is None or info["size"] > LIMIT:
        raise HTTPException(422, "Choose a regular output file up to 50 MB")
    result = hub.expect(
        await hub.request("GET", endpoint, contents=True, params={"format": "base64"})
    ).json()
    content = base64.b64decode(result["content"])
    if len(content) > LIMIT:
        raise HTTPException(422, "Output exceeds 50 MB")
    root = DATA_DIR / "notebook-outputs"
    root.mkdir(exist_ok=True)
    key = secrets.token_hex(24)
    target = root / key
    target.write_bytes(content)
    output = NotebookOutput(
        notebook_id=id,
        owner_id=user.id,
        filename=path.name,
        storage_key=key,
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        shared=int(data.shared),
    )
    try:
        db.add(output)
        db.commit()
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return describe(output, notebook.title)


@router.get("/notebook-outputs/{id}/download")
def download_output(id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    output = readable(db, id, user)
    path = DATA_DIR / "notebook-outputs" / output.storage_key
    if not path.is_file():
        raise HTTPException(404, "Output file is unavailable")
    return FileResponse(
        path, filename=output.filename, media_type="application/octet-stream"
    )


async def copy_input(db, id, user, hub, folder=""):
    output = readable(db, id, user)
    source = DATA_DIR / "notebook-outputs" / output.storage_key
    if not source.is_file():
        raise HTTPException(404, "Output file is unavailable")
    path = input_path(output)
    from .notebook_files import mkdir

    destination = f"{folder}/{path}" if folder else path
    await mkdir(user, hub, str(PurePosixPath(destination).parent))
    prefix = f"/user/{hub_username(user)}/api/contents/"
    for directory in ("input", "input/notebooks", f"input/notebooks/{output.id}"):
        found = await hub.request(
            "GET", prefix + directory, contents=True, params={"content": 0}
        )
        if found.status_code == 404:
            hub.expect(
                await hub.request(
                    "PUT", prefix + directory, contents=True, json={"type": "directory"}
                ),
                (200, 201),
            )
        else:
            hub.expect(found)
    hub.expect(
        await hub.request(
            "PUT",
            prefix + quote(destination, safe="/"),
            contents=True,
            json={
                "type": "file",
                "format": "base64",
                "content": base64.b64encode(source.read_bytes()).decode(),
            },
        ),
        (200, 201),
    )
    return describe(output, db.get(Notebook, output.notebook_id).title)


def store_snapshot(db, notebook_id, owner_id, filename, content):
    """Preserve output chronology while reusing identical immutable file bytes."""
    digest = hashlib.sha256(content).hexdigest()
    previous = db.scalar(
        select(NotebookOutput)
        .where(
            NotebookOutput.notebook_id == notebook_id,
            NotebookOutput.filename == filename,
            NotebookOutput.shared == 1,
        )
        .order_by(NotebookOutput.id.desc())
        .limit(1)
    )
    if previous and previous.sha256 == digest:
        return previous
    existing = db.scalar(
        select(NotebookOutput)
        .where(
            NotebookOutput.notebook_id == notebook_id,
            NotebookOutput.sha256 == digest,
        )
        .order_by(NotebookOutput.id.desc())
        .limit(1)
    )
    root = DATA_DIR / "notebook-outputs"
    root.mkdir(exist_ok=True)
    if existing and (root / existing.storage_key).is_file():
        key = existing.storage_key
    else:
        key = secrets.token_hex(24)
        target = root / key
        with target.open("xb") as stream:
            stream.write(content)
    row = NotebookOutput(
        notebook_id=notebook_id,
        owner_id=owner_id,
        filename=filename,
        storage_key=key,
        size=len(content),
        sha256=digest,
        shared=1,
    )
    db.add(row)
    return row
