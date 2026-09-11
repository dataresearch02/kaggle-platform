"""Immutable supplemental dataset files and hosted model artifacts."""

import hashlib
import secrets
from pathlib import PurePosixPath
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_user
from .code_pages import optional_user
from .dataset_access import readable
from .db import DATA_DIR, get_db
from .models import ArtifactVersion, Dataset, ModelCard, WorkFileDeletion

router = APIRouter(prefix="/api/assets", tags=["Artifact files"])
Kind = Literal["datasets", "models"]
MAX_BYTES = 10 * 1024 * 1024


def resource(db, kind, id, user, write=False):
    model = Dataset if kind == "datasets" else ModelCard
    if write:
        row = db.scalar(select(model).where(model.id == id).with_for_update())
        if not row or row.owner_id != user.id:
            raise HTTPException(404, "Your resource was not found")
        return row
    if kind == "datasets":
        return readable(db, id, user)
    row = db.get(model, id)
    if not row:
        raise HTTPException(404, "Model not found")
    return row


def info(row):
    return {
        key: getattr(row, key) for key in ("id", "path", "size", "sha256", "created_at")
    }


@router.get("/{kind}/{id}")
def listing(
    kind: Kind,
    id: int,
    before: int = 2147483647,
    user=Depends(optional_user),
    db: Session = Depends(get_db),
):
    resource(db, kind, id, user)
    return [
        info(row)
        for row in db.scalars(
            select(ArtifactVersion)
            .where(
                ArtifactVersion.kind == kind,
                ArtifactVersion.resource_id == id,
                ArtifactVersion.id < before,
            )
            .order_by(ArtifactVersion.id.desc())
            .limit(50)
        )
    ]


@router.post("/{kind}/{id}", status_code=201)
async def upload(
    kind: Kind,
    id: int,
    path: str = Form(...),
    file: UploadFile = File(...),
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    resource(db, kind, id, user, write=True)
    if (
        not path
        or len(path) > 240
        or "\\" in path
        or any(ord(char) < 32 for char in path)
        or PurePosixPath(path).is_absolute()
        or any(part in ("", ".", "..") for part in path.split("/"))
    ):
        raise HTTPException(
            422, "Use a relative file path without empty, dot or parent segments"
        )
    root = DATA_DIR / "artifacts"
    root.mkdir(exist_ok=True)
    key = secrets.token_hex(24)
    target = root / key
    size, digest = 0, hashlib.sha256()
    try:
        with target.open("xb") as stream:
            while chunk := await file.read(256 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise HTTPException(
                        413, "Each artifact is limited to 10 MB for local testing"
                    )
                digest.update(chunk)
                stream.write(chunk)
        row = ArtifactVersion(
            kind=kind,
            resource_id=id,
            path=path,
            storage_key=key,
            size=size,
            sha256=digest.hexdigest(),
        )
        db.add(row)
        db.commit()
        return info(row)
    except BaseException:
        target.unlink(missing_ok=True)
        raise


@router.get("/{kind}/{id}/{version_id}/download")
def download(
    kind: Kind,
    id: int,
    version_id: int,
    user=Depends(optional_user),
    db: Session = Depends(get_db),
):
    resource(db, kind, id, user)
    row = db.get(ArtifactVersion, version_id)
    if not row or row.kind != kind or row.resource_id != id:
        raise HTTPException(404, "File version not found")
    target = DATA_DIR / "artifacts" / row.storage_key
    if not target.is_file():
        raise HTTPException(404, "File is unavailable")
    return FileResponse(
        target,
        media_type="application/octet-stream",
        filename=PurePosixPath(row.path).name,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


def delete_artifacts(db, kind, id, owner_id):
    for row in db.scalars(
        select(ArtifactVersion).where(
            ArtifactVersion.kind == kind, ArtifactVersion.resource_id == id
        )
    ):
        db.add(
            WorkFileDeletion(owner_id=owner_id, kind="artifact", path=row.storage_key)
        )
        db.delete(row)
