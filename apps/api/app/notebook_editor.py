"""Notebook-scoped document and kernel APIs. No arbitrary file paths or kernel IDs."""

import asyncio
import base64
import json
import re
import secrets
import time
from datetime import datetime, timezone
from typing import Literal
from weakref import WeakValueDictionary

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session
from websockets.asyncio.client import connect

from .kernel_channels import wait_for_kernel
from .auth import current_user
from .db import DATA_DIR, get_db
from .models import Dataset, Notebook, User, NotebookWorkingCopy
from .notebook_drafts import owned, path_for, open_draft, user_lock
from .notebook_runtime import HubClient, get_hub, hub_username, open_notebook

router = APIRouter(prefix="/api/editor", tags=["Arena notebook editor"])
Kind = Literal["notebooks", "drafts"]
_kernel_locks = WeakValueDictionary()


class Document(BaseModel):
    nbformat: Literal[4] = 4
    nbformat_minor: int = Field(default=5, ge=0, le=5)
    metadata: dict = Field(default_factory=dict)
    cells: list[dict] = Field(max_length=500)

    @model_validator(mode="after")
    def validate_cells(self):
        if len(json.dumps(self.model_dump())) > 10 * 1024 * 1024:
            raise ValueError("Notebook must be smaller than 10 MB")
        ids = set()
        for cell in self.cells:
            if cell.get("cell_type") not in ("code", "markdown", "raw"):
                raise ValueError("Unsupported cell type")
            source = cell.get("source", "")
            if not isinstance(source, str) and not (
                isinstance(source, list)
                and all(isinstance(line, str) for line in source)
            ):
                raise ValueError("Cell source must be text")
            id = cell.setdefault("id", secrets.token_hex(8))
            if (
                not isinstance(id, str)
                or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", id)
                or id in ids
            ):
                raise ValueError("Cell IDs must be unique")
            ids.add(id)
            cell.setdefault("metadata", {})
            if cell["cell_type"] == "code":
                cell.setdefault("execution_count", None)
                outputs = cell.setdefault("outputs", [])
                if not isinstance(outputs, list) or any(
                    not isinstance(output, dict) for output in outputs
                ):
                    raise ValueError("Cell outputs must be objects")
                for output in outputs:
                    output.pop(
                        "transient", None
                    )  # Display IDs are runtime-only nbformat fields.
        return self


class Execution(BaseModel):
    code: str = Field(max_length=100000)


def resolve(kind, id, user, db):
    if kind == "drafts":
        path = path_for(owned(db, id, user))
        db.commit()  # Do not hold a database row lock throughout kernel execution.
        return path
    from .notebook_visibility import require_visible

    if id.isdecimal():
        require_visible(db, int(id), user)
    if not id.isdecimal() or not db.get(Notebook, int(id)):
        raise HTTPException(404, "Notebook not found")
    return f"arena-notebook-{int(id)}.ipynb"


def contents(user, path):
    return f"/user/{hub_username(user)}/api/contents/{path}"


@router.get("/{kind}/{id}/document")
async def get_document(
    kind: Kind,
    id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    hub: HubClient = Depends(get_hub),
):
    if kind == "drafts":
        await open_draft(id=id, user=user, db=db, hub=hub)
    else:
        resolve(kind, id, user, db)
        await open_notebook(int(id), user, db, hub)
    path = resolve(kind, id, user, db)
    return hub.expect(
        await hub.request("GET", contents(user, path), contents=True)
    ).json()["content"]


@router.put("/{kind}/{id}/document")
async def put_document(
    kind: Kind,
    id: str,
    data: Document,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    hub: HubClient = Depends(get_hub),
):
    async with user_lock(user.id):
        path = resolve(kind, id, user, db)
        hub.expect(
            await hub.request(
                "PUT",
                contents(user, path),
                contents=True,
                json={
                    "type": "notebook",
                    "format": "json",
                    "content": data.model_dump(),
                },
            ),
            (200, 201),
        )
    if kind == "notebooks":
        working = db.get(NotebookWorkingCopy, int(id))
        if db.get(Notebook, int(id)).owner_id == user.id:
            if not working:
                working = NotebookWorkingCopy(notebook_id=int(id), private=0)
                db.add(working)
            from .notebook_versions import save_version

            from .notebook_files import snapshot_outputs, folder_for

            await snapshot_outputs(
                db, db.get(Notebook, int(id)), user, hub, folder_for(db, path)
            )
            save_version(db, db.get(Notebook, int(id)), data.model_dump())
            working.document = json.dumps(data.model_dump())
            db.commit()
    return {"saved": True}


@router.post("/{kind}/{id}/inputs/{dataset_id}")
async def attach_input(
    kind: Kind,
    id: str,
    dataset_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    hub: HubClient = Depends(get_hub),
):
    """Copy a public Arena dataset to a fixed name in this user's workspace."""
    async with user_lock(user.id):
        resolve(kind, id, user, db)
        from .dataset_access import readable

        dataset = readable(db, dataset_id, user)
        if dataset is None:
            raise HTTPException(404, "Dataset not found")
        source = DATA_DIR / "uploads" / dataset.storage_key
        if not source.is_file():
            raise HTTPException(404, "Dataset file not found")
        path = f"arena-input-{dataset.id}.csv"
        content = await asyncio.to_thread(source.read_bytes)
        hub.expect(
            await hub.request(
                "PUT",
                contents(user, path),
                contents=True,
                json={
                    "type": "file",
                    "format": "base64",
                    "content": base64.b64encode(content).decode("ascii"),
                },
            ),
            (200, 201),
        )
    from .notebook_files import folder_for, mkdir, endpoint

    target_folder = folder_for(db, resolve(kind, id, user, db))
    await mkdir(user, hub, target_folder)
    hub.expect(
        await hub.request(
            "PUT",
            endpoint(user, target_folder + "/" + path),
            contents=True,
            json={
                "type": "file",
                "format": "base64",
                "content": base64.b64encode(content).decode(),
            },
        ),
        (200, 201),
    )
    return {"path": path}


async def kernel_for(user, path, hub, db):
    from .notebook_files import folder_for, prepare_inputs

    folder = folder_for(db, path)
    scoped_path = folder + "/session.ipynb"
    base = f"/user/{hub_username(user)}/api"
    async with user_lock(user.id):
        sessions = hub.expect(
            await hub.request("GET", base + "/sessions", contents=True)
        ).json()
        for session in sessions:
            if session.get("path") in (path, scoped_path):
                return session["kernel"]["id"]
        response = await hub.request("GET", contents(user, path), contents=True)
        if response.status_code == 404:
            from .notebook_runtime import notebook_document

            notebook = (
                db.get(
                    Notebook,
                    int(path.removeprefix("arena-notebook-").removesuffix(".ipynb")),
                )
                if path.startswith("arena-notebook-")
                else None
            )
            document = (
                notebook_document(notebook, db, working=notebook.owner_id == user.id)
                if notebook
                else {"metadata": {}}
            )
        else:
            document = hub.expect(response).json()["content"]
        await prepare_inputs(db, user, hub, folder, document)
        session = hub.expect(
            await hub.request(
                "POST",
                base + "/sessions",
                contents=True,
                json={
                    "path": scoped_path,
                    "name": path,
                    "type": "notebook",
                    "kernel": {"name": "python3"},
                },
            ),
            (200, 201),
        ).json()
        return session["kernel"]["id"]


@router.post("/{kind}/{id}/kernel/{action}")
async def control_kernel(
    kind: Kind,
    id: str,
    action: Literal["interrupt", "restart"],
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    hub: HubClient = Depends(get_hub),
):
    path = resolve(kind, id, user, db)
    if action == "restart":
        sessions = hub.expect(
            await hub.request(
                "GET", f"/user/{hub_username(user)}/api/sessions", contents=True
            )
        ).json()
        for session in sessions:
            if session.get("path") == path:
                hub.expect(
                    await hub.request(
                        "DELETE",
                        f"/user/{hub_username(user)}/api/sessions/{session['id']}",
                        contents=True,
                    ),
                    (204, 404),
                )
    kernel = await kernel_for(user, path, hub, db)
    hub.expect(
        await hub.request(
            "POST",
            f"/user/{hub_username(user)}/api/kernels/{kernel}/{action}",
            contents=True,
        ),
        (200, 204),
    )
    return {"state": "idle"}


def kernel_lock(key):
    lock = _kernel_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _kernel_locks[key] = lock
    return lock


@router.post("/{kind}/{id}/execute")
async def execute(
    kind: Kind,
    id: str,
    data: Execution,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    hub: HubClient = Depends(get_hub),
):
    path = resolve(kind, id, user, db)
    kernel = await kernel_for(user, path, hub, db)
    lock = kernel_lock((user.id, kernel))
    if lock.locked():
        raise HTTPException(409, "This notebook is already running a cell")
    await lock.acquire()
    base = f"/user/{hub_username(user)}/api/kernels/{kernel}"
    url = (
        hub.proxy_url.replace("http://", "ws://", 1).replace("https://", "wss://", 1)
        + base
        + "/channels"
    )

    async def stream():
        finished = False
        total = 0
        try:
            async with connect(
                url,
                additional_headers={"Authorization": f"token {hub.token}"},
                proxy=None,
                max_size=12 * 1024 * 1024,
                open_timeout=30,
            ) as socket:
                await wait_for_kernel(socket, hub_username(user))
                msg_id = secrets.token_hex(16)
                await socket.send(
                    json.dumps(
                        {
                            "header": {
                                "msg_id": msg_id,
                                "username": hub_username(user),
                                "session": secrets.token_hex(16),
                                "date": datetime.now(timezone.utc).isoformat(),
                                "msg_type": "execute_request",
                                "version": "5.3",
                            },
                            "parent_header": {},
                            "metadata": {},
                            "channel": "shell",
                            "content": {
                                "code": data.code,
                                "silent": False,
                                "store_history": True,
                                "user_expressions": {},
                                "allow_stdin": False,
                                "stop_on_error": True,
                            },
                            "buffers": [],
                        }
                    )
                )
                from .runtime_jobs import integer

                deadline = time.monotonic() + integer(
                    "NOTEBOOK_CELL_TIMEOUT_SECONDS", 120
                )
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise asyncio.TimeoutError()
                    try:
                        raw = await asyncio.wait_for(socket.recv(), min(remaining, 15))
                    except asyncio.TimeoutError:
                        if time.monotonic() >= deadline:
                            raise
                        yield json.dumps({"type": "heartbeat"}) + "\n"
                        continue
                    if not isinstance(raw, str):
                        continue  # Binary widget comms are not supported by the editor.
                    message = json.loads(raw)
                    if message.get("parent_header", {}).get("msg_id") != msg_id:
                        continue
                    msg_type = message["header"]["msg_type"]
                    content = message["content"]
                    if (
                        msg_type == "status"
                        and content.get("execution_state") == "idle"
                    ):
                        finished = True
                        yield json.dumps({"type": "done"}) + "\n"
                        break
                    if msg_type in (
                        "stream",
                        "display_data",
                        "execute_result",
                        "error",
                        "clear_output",
                        "update_display_data",
                        "execute_input",
                    ):
                        payload = (
                            json.dumps({"type": msg_type, "content": content}) + "\n"
                        )
                        total += len(payload)
                        if total > 10 * 1024 * 1024:
                            raise ValueError(
                                "Output exceeded 10 MB. Reduce the output and run again."
                            )
                        yield payload
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            message = (
                str(exc)
                if isinstance(exc, ValueError)
                else "Execution interrupted or timed out. You can retry or restart the kernel."
            )
            yield json.dumps({"type": "failure", "message": message}) + "\n"
        finally:
            if not finished:
                try:
                    await hub.request("POST", base + "/interrupt", contents=True)
                except HTTPException:
                    pass
            lock.release()

    return StreamingResponse(
        stream(),
        media_type="application/x-ndjson",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"},
    )


@router.post("/{kind}/{id}/notebook-inputs/{output_id}")
async def attach_notebook_output(
    kind: Kind,
    id: str,
    output_id: int,
    user=Depends(current_user),
    db: Session = Depends(get_db),
    hub=Depends(get_hub),
):
    from .notebook_outputs import copy_input

    async with user_lock(user.id):
        resolve(kind, id, user, db)
        from .notebook_files import folder_for

        result = await copy_input(db, output_id, user, hub)
        await copy_input(
            db, output_id, user, hub, folder_for(db, resolve(kind, id, user, db))
        )
        return result


@router.post("/{kind}/{id}/input-sources/{source_kind}/{source_id}")
async def attach_source(
    kind: Kind,
    id: str,
    source_kind: str,
    source_id: int,
    user=Depends(current_user),
    db=Depends(get_db),
    hub=Depends(get_hub),
):
    from .input_sources import source_files, materialize
    from .notebook_files import folder_for

    async with user_lock(user.id):
        path = resolve(kind, id, user, db)
        item, _ = source_files(db, user, source_kind, source_id)
        sessions = hub.expect(
            await hub.request(
                "GET", f"/user/{hub_username(user)}/api/sessions", contents=True
            )
        ).json()
        if any(session.get("path") == path for session in sessions):
            await materialize(db, user, hub, "", item)
        return await materialize(db, user, hub, folder_for(db, path), item)


@router.post("/{kind}/{id}/remove-input-source")
async def remove_source(
    kind: Kind,
    id: str,
    item: dict,
    user=Depends(current_user),
    db=Depends(get_db),
    hub=Depends(get_hub),
):
    from .input_sources import validate_reference
    from .notebook_files import folder_for, endpoint
    from pathlib import PurePosixPath

    async with user_lock(user.id):
        notebook_path = resolve(kind, id, user, db)
        folders = [folder_for(db, notebook_path)]
        sessions = hub.expect(
            await hub.request(
                "GET", f"/user/{hub_username(user)}/api/sessions", contents=True
            )
        ).json()
        if any(session.get("path") == notebook_path for session in sessions):
            folders.append("")
        result = validate_reference(item)
        files = [(file["id"], file["filename"], None) for file in result["files"]]
        for folder in folders:
            directories = {(folder + "/" if folder else "") + result["path"]}
            for _, name, _ in files:
                path = (folder + "/" if folder else "") + result["path"] + "/" + name
                response = await hub.request(
                    "DELETE", endpoint(user, path), contents=True
                )
                if response.status_code != 404:
                    hub.expect(response, (204,))
                parent = str(PurePosixPath(path).parent)
                while parent.startswith(
                    (folder + "/" if folder else "") + result["path"]
                ):
                    directories.add(parent)
                    parent = str(PurePosixPath(parent).parent)
            for directory in sorted(directories, key=len, reverse=True):
                response = await hub.request(
                    "DELETE", endpoint(user, directory), contents=True
                )
                if response.status_code not in (400, 404):
                    hub.expect(response, (204,))
        return {"removed": True}


@router.delete("/{kind}/{id}/legacy-inputs/{source_kind}/{source_id}")
async def remove_legacy_input(
    kind: Kind,
    id: str,
    source_kind: Literal["dataset", "notebook-output"],
    source_id: int,
    user=Depends(current_user),
    db=Depends(get_db),
    hub=Depends(get_hub),
):
    from .notebook_files import folder_for, endpoint
    from .notebook_outputs import readable, input_path

    async with user_lock(user.id):
        folder = folder_for(db, resolve(kind, id, user, db))
        path = (
            input_path(readable(db, source_id, user))
            if source_kind == "notebook-output"
            else f"arena-input-{source_id}.csv"
        )
        for target in (path, folder + "/" + path):
            response = await hub.request(
                "DELETE", endpoint(user, target), contents=True
            )
            if response.status_code != 404:
                hub.expect(response, (204,))
        return {"removed": True}
