"""Resumable chunked uploads of dataset and model files into draft versions.

The web proxy limits request bodies to about 11 MB and 180 seconds, so browsers send
files as numbered chunks (UPLOAD_CHUNK_BYTES, 8 MiB by default):

1. POST /api/uploads with the draft version id, relative path, size and an optional
   SHA-256. The owner's storage quota and the uploader's session limit are checked.
2. PUT /api/uploads/{id}/chunks/{index} with the raw chunk bytes, in any order and
   retried freely; an optional X-Chunk-Sha256 header is verified. Each part is
   written to a temporary name and renamed into place.
3. GET /api/uploads/{id} lists the received chunks, so a reloaded browser resumes.
4. POST /api/uploads/{id}/complete checks every chunk and the quota, then assembles
   the parts in the background into a hidden temporary blob, verifies the total size
   and the declared SHA-256, renames it into place and attaches it to the draft.
   Clients poll the status until it is `completed` or `failed`.
5. DELETE /api/uploads/{id} cancels and removes the parts.

cleanup_uploads removes sessions idle for UPLOAD_SESSION_TTL_HOURS with their parts,
and returns assemblies interrupted by a restart to `uploading` so they can finish.
"""

import asyncio
import hashlib
import logging
import math
import os
import re
import secrets
import shutil
import stat
import time
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
)
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import sessionmaker

from .auth import current_user
from .db import DATA_DIR, SessionLocal, get_db
from .file_store import blob_path, clean_path, new_key, temporary_path
from .models import (
    ResourceVersion,
    StoredFile,
    UploadChunk,
    UploadSession,
    now,
)
from .permissions import is_admin
from .runtime_jobs import integer
from .storage_quotas import ACTIVE, require_capacity

router = APIRouter(prefix="/api/uploads", tags=["Uploads"])
MIB = 1024 * 1024
MAX_CHUNKS = 100_000
SESSION_ID = re.compile(r"[0-9a-f]{32}")
# An assembly that has not reported progress for this long was interrupted.
STALE_ASSEMBLY_SECONDS = 600


def chunk_bytes():
    # Stays well under the web proxy's 11 MB request body limit.
    return integer("UPLOAD_CHUNK_BYTES", 8 * MIB, minimum=1024, maximum=10 * MIB)


def max_file_bytes():
    return integer("UPLOAD_MAX_FILE_BYTES", 100 * 1024**3, maximum=16 * 1024**4)


def max_sessions():
    return integer("UPLOAD_MAX_ACTIVE_SESSIONS", 8, maximum=1000)


def ttl_seconds():
    return integer("UPLOAD_SESSION_TTL_HOURS", 24, maximum=24 * 30) * 3600


def parts_root():
    return Path(os.getenv("UPLOAD_DIR") or DATA_DIR / "upload-sessions")


def session_dir(id):
    if not SESSION_ID.fullmatch(id):
        raise ValueError("Invalid upload session id")
    return parts_root() / id


def remove_parts(id):
    with_parts = session_dir(id)
    if with_parts.is_symlink():
        with_parts.unlink()
    elif with_parts.exists():
        shutil.rmtree(with_parts, ignore_errors=True)


def expected_size(session, index):
    if index < session.chunk_count - 1:
        return session.chunk_size
    return session.total_size - session.chunk_size * (session.chunk_count - 1)


def session_json(db, session):
    from .resource_versions import file_json
    from .models import ResourceVersionFile

    received = list(
        db.scalars(
            select(UploadChunk.index)
            .where(UploadChunk.session_id == session.id)
            .order_by(UploadChunk.index)
        )
    )
    member = (
        db.get(ResourceVersionFile, session.version_file_id)
        if session.version_file_id
        else None
    )
    return {
        "id": session.id,
        "version_id": session.version_id,
        "path": session.path,
        "size": session.total_size,
        "sha256": session.sha256,
        "chunk_size": session.chunk_size,
        "chunk_count": session.chunk_count,
        "received": received,
        "received_bytes": session.received_bytes,
        "status": session.status,
        "error": session.error,
        "expires_at": session.expires_at,
        "file": (
            file_json(member, db.get(StoredFile, member.file_id)) if member else None
        ),
    }


def owned_session(db, id, user, lock=False):
    query = select(UploadSession).where(UploadSession.id == id)
    session = db.scalar(query.with_for_update() if lock else query)
    if not session or (session.user_id != user.id and not is_admin(user)):
        raise HTTPException(404, "Upload not found")
    return session


def touch(session):
    session.updated_at = time.time()
    session.expires_at = session.updated_at + ttl_seconds()


class SessionInput(BaseModel):
    version_id: int
    path: str = Field(min_length=1, max_length=240)
    size: int = Field(ge=1)
    sha256: str = Field(default="", pattern=r"^([0-9a-fA-F]{64})?$")


@router.post("", status_code=201)
def create_session(data: SessionInput, user=Depends(current_user), db=Depends(get_db)):
    from .resource_versions import writable_draft

    _, row = writable_draft(db, data.version_id, user)
    try:
        path = clean_path(data.path)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if data.size > max_file_bytes():
        raise HTTPException(
            413, f"Files are limited to {max_file_bytes() / 1024**3:.0f} GiB"
        )
    size = chunk_bytes()
    count = math.ceil(data.size / size)
    if count > MAX_CHUNKS:
        raise HTTPException(
            413,
            "This file needs too many chunks; ask an administrator to raise UPLOAD_CHUNK_BYTES",
        )
    active = db.scalar(
        select(func.count())
        .select_from(UploadSession)
        .where(UploadSession.user_id == user.id, UploadSession.status.in_(ACTIVE))
    )
    if active >= max_sessions():
        raise HTTPException(
            429,
            f"Finish or cancel an upload first; at most {max_sessions()} can be in progress",
        )
    require_capacity(db, row.owner_id, data.size)
    session = UploadSession(
        id=secrets.token_hex(16),
        user_id=user.id,
        owner_id=row.owner_id,
        version_id=data.version_id,
        path=path,
        total_size=data.size,
        chunk_size=size,
        chunk_count=count,
        sha256=data.sha256.lower(),
        status="uploading",
        created_at=now(),
        updated_at=0,
        expires_at=0,
    )
    touch(session)
    db.add(session)
    db.commit()
    return session_json(db, session)


@router.get("/{id}")
def get_session(id: str, user=Depends(current_user), db=Depends(get_db)):
    return session_json(db, owned_session(db, id, user))


def write_part(directory, index, content):
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / f"{index}.{secrets.token_hex(4)}.tmp"
    try:
        with open(temporary, "xb") as stream:
            stream.write(content)
        os.replace(temporary, directory / f"{index}.part")
    finally:
        temporary.unlink(missing_ok=True)


@router.put("/{id}/chunks/{index}")
async def upload_chunk(
    id: str,
    index: int,
    request: Request,
    user=Depends(current_user),
    db=Depends(get_db),
):
    session = owned_session(db, id, user)
    if session.status != "uploading":
        raise HTTPException(409, f"This upload is {session.status}")
    if not 0 <= index < session.chunk_count:
        raise HTTPException(422, "Chunk index is out of range")
    expected = expected_size(session, index)
    declared = request.headers.get("x-chunk-sha256", "").lower()
    if declared and not re.fullmatch(r"[0-9a-f]{64}", declared):
        raise HTTPException(422, "X-Chunk-Sha256 must be a hex SHA-256 digest")
    db.rollback()  # Do not hold a database connection while the body arrives.
    content = bytearray()
    async for piece in request.stream():
        content.extend(piece)
        if len(content) > expected:
            raise HTTPException(413, f"Chunk {index} must be exactly {expected} bytes")
    if len(content) != expected:
        raise HTTPException(422, f"Chunk {index} must be exactly {expected} bytes")
    digest = hashlib.sha256(content).hexdigest()
    if declared and declared != digest:
        raise HTTPException(
            422, f"Chunk {index} was corrupted in transit; send it again"
        )
    await asyncio.to_thread(write_part, session_dir(id), index, bytes(content))
    session = owned_session(db, id, user, lock=True)
    if session.status != "uploading":
        raise HTTPException(409, f"This upload is {session.status}")
    chunk = db.get(UploadChunk, (id, index))
    if chunk:
        chunk.size, chunk.sha256 = expected, digest
    else:
        db.add(UploadChunk(session_id=id, index=index, size=expected, sha256=digest))
    db.flush()
    session.received_bytes = int(
        db.scalar(
            select(func.coalesce(func.sum(UploadChunk.size), 0)).where(
                UploadChunk.session_id == id
            )
        )
    )
    touch(session)
    db.commit()
    return {
        "index": index,
        "size": expected,
        "sha256": digest,
        "received_bytes": session.received_bytes,
    }


@router.post("/{id}/complete", status_code=202)
def complete(
    id: str, background: BackgroundTasks, user=Depends(current_user), db=Depends(get_db)
):
    session = owned_session(db, id, user, lock=True)
    if session.status in ("assembling", "completed"):
        return session_json(db, session)
    if session.status != "uploading":
        raise HTTPException(409, f"This upload is {session.status}; start it again")
    chunks = dict(
        db.execute(
            select(UploadChunk.index, UploadChunk.size).where(
                UploadChunk.session_id == id
            )
        ).all()
    )
    missing = [
        index
        for index in range(session.chunk_count)
        if chunks.get(index) != expected_size(session, index)
    ]
    if missing:
        raise HTTPException(
            409, f"{len(missing)} chunks are missing, starting with chunk {missing[0]}"
        )
    version = db.get(ResourceVersion, session.version_id)
    if not version or version.status != "draft":
        raise HTTPException(409, "The draft version was published or discarded")
    require_capacity(
        db, session.owner_id, session.total_size, session.id, reserved=False
    )
    session.status, session.error = "assembling", ""
    touch(session)
    db.commit()
    background.add_task(
        assemble, sessionmaker(bind=db.get_bind(), expire_on_commit=False), id
    )
    return session_json(db, session)


@router.delete("/{id}", status_code=204)
def abort(id: str, user=Depends(current_user), db=Depends(get_db)):
    session = owned_session(db, id, user, lock=True)
    if session.status == "assembling":
        raise HTTPException(409, "The upload is being assembled; wait for it to finish")
    db.execute(delete(UploadChunk).where(UploadChunk.session_id == id))
    db.delete(session)
    db.commit()
    remove_parts(id)
    return Response(status_code=204)


def drop_sessions(db, version_ids):
    """Cancel uploads into versions that are being removed (in the caller's transaction)."""
    if not version_ids:
        return
    sessions = list(
        db.scalars(
            select(UploadSession).where(UploadSession.version_id.in_(version_ids))
        )
    )
    if any(session.status == "assembling" for session in sessions):
        raise HTTPException(
            409, "An upload into this version is being assembled; try again shortly"
        )
    for session in sessions:
        db.execute(delete(UploadChunk).where(UploadChunk.session_id == session.id))
        db.delete(session)
        remove_parts(session.id)
    db.flush()


def fail(factory, id, message):
    with factory() as db:
        session = db.get(UploadSession, id)
        if session:
            session.status, session.error = "failed", message[:2000]
            db.execute(delete(UploadChunk).where(UploadChunk.session_id == id))
            session.received_bytes = 0
            touch(session)
            db.commit()
    remove_parts(id)


def heartbeat(factory, id):
    with factory() as db:
        session = db.get(UploadSession, id)
        if session and session.status == "assembling":
            touch(session)
            db.commit()


def open_part(path, size):
    fd = os.open(
        path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    )
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_size != size:
        os.close(fd)
        raise ValueError(
            "An uploaded chunk is missing or has the wrong size; upload the file again"
        )
    return os.fdopen(fd, "rb")


def assemble(factory, id):
    """Concatenate verified parts into a new blob and attach it to the draft."""
    from .resource_versions import attach_file

    with factory() as db:
        session = db.get(UploadSession, id)
        if not session or session.status != "assembling":
            return
        version = db.get(ResourceVersion, session.version_id)
        store = "uploads" if version and version.kind == "dataset" else "artifacts"
        path, total, declared, owner_id = (
            session.path,
            session.total_size,
            session.sha256,
            session.owner_id,
        )
        sizes = [expected_size(session, index) for index in range(session.chunk_count)]
    key = new_key(
        ".csv" if store == "uploads" and path.lower().endswith(".csv") else ""
    )
    temporary, target = temporary_path(store, key), blob_path(store, key)
    digest, written = hashlib.sha256(), 0
    try:
        with open(temporary, "xb") as output:
            for index, size in enumerate(sizes):
                with open_part(session_dir(id) / f"{index}.part", size) as part:
                    while chunk := part.read(MIB):
                        digest.update(chunk)
                        written += len(chunk)
                        output.write(chunk)
                if index % 64 == 63:
                    heartbeat(factory, id)
            output.flush()
            os.fsync(output.fileno())
        if written != total:
            raise ValueError(
                "The assembled file does not match the declared size; upload it again"
            )
        if declared and declared != digest.hexdigest():
            raise ValueError(
                "SHA-256 mismatch: the file changed or was corrupted during upload. Upload it again."
            )
        os.replace(temporary, target)
    except (OSError, ValueError) as exc:
        temporary.unlink(missing_ok=True)
        fail(
            factory,
            id,
            (
                str(exc)
                if isinstance(exc, ValueError)
                else "Assembly failed; upload the file again"
            ),
        )
        return
    try:
        with factory() as db:
            session = db.scalar(
                select(UploadSession).where(UploadSession.id == id).with_for_update()
            )
            version = db.scalar(
                select(ResourceVersion)
                .where(ResourceVersion.id == session.version_id)
                .with_for_update()
                if session
                else select(ResourceVersion).where(ResourceVersion.id == -1)
            )
            if (
                not session
                or session.status != "assembling"
                or not version
                or version.status != "draft"
            ):
                raise ValueError(
                    "The draft version was published or discarded before the upload finished"
                )
            try:
                require_capacity(db, owner_id, total, id, reserved=False)
            except HTTPException as exc:
                raise ValueError(exc.detail)
            stored = StoredFile(
                owner_id=owner_id,
                store=store,
                storage_key=key,
                size=written,
                sha256=digest.hexdigest(),
            )
            db.add(stored)
            db.flush()
            member = attach_file(db, version, path, stored.id, owner_id)
            session.status, session.version_file_id = "completed", member.id
            touch(session)
            db.commit()
    except (ValueError, HTTPException) as exc:
        target.unlink(missing_ok=True)
        fail(factory, id, str(getattr(exc, "detail", exc)))
        return
    except Exception:
        target.unlink(missing_ok=True)
        logging.getLogger(__name__).exception("Attaching upload %s failed", id)
        fail(factory, id, "The upload could not be attached; upload the file again")
        return
    remove_parts(id)


def expire_uploads(db, at=None):
    """Recover interrupted assemblies and remove expired sessions. Returns removed ids."""
    at = time.time() if at is None else at
    for session in db.scalars(
        select(UploadSession).where(
            UploadSession.status == "assembling",
            UploadSession.updated_at < at - STALE_ASSEMBLY_SECONDS,
        )
    ):
        session.status, session.error = (
            "uploading",
            "Assembly was interrupted; complete the upload again",
        )
    removed = []
    for session in db.scalars(
        select(UploadSession).where(
            UploadSession.expires_at < at, UploadSession.status != "assembling"
        )
    ):
        db.execute(delete(UploadChunk).where(UploadChunk.session_id == session.id))
        db.delete(session)
        removed.append(session.id)
    db.commit()
    for id in removed:
        remove_parts(id)
    root = parts_root()
    if root.is_dir():
        known = set(db.scalars(select(UploadSession.id)))
        for folder in root.iterdir():
            if (
                SESSION_ID.fullmatch(folder.name)
                and folder.name not in known
                and folder.lstat().st_mtime < at - ttl_seconds()
            ):
                remove_parts(folder.name)
    return removed


async def cleanup_uploads():
    def run():
        with SessionLocal() as db:
            expire_uploads(db)

    while True:
        await asyncio.sleep(60)
        try:
            await asyncio.to_thread(run)
        except Exception:
            logging.getLogger(__name__).exception("Upload cleanup failed; will retry")
