"""Notebook-scoped execution folders and automatic saved output snapshots."""

import base64
from pathlib import PurePosixPath
from urllib.parse import quote
from fastapi import HTTPException
from sqlalchemy import select
from .db import DATA_DIR
from .models import NotebookOutput, NotebookWorkspaceFolder
from .notebook_runtime import hub_username


def folder_for(db, path):
    if path.startswith("arena-notebook-"):
        id = int(path.removeprefix("arena-notebook-").removesuffix(".ipynb"))
        row = db.get(NotebookWorkspaceFolder, id)
        if row:
            return row.folder
    return "workspaces/" + path.removesuffix(".ipynb")


def endpoint(user, path):
    return f'/user/{hub_username(user)}/api/contents/{quote(path, safe="/")}'


async def mkdir(user, hub, folder):
    parts = PurePosixPath(folder).parts
    for index in range(1, len(parts) + 1):
        target = endpoint(user, "/".join(parts[:index]))
        response = await hub.request(
            "GET", target, contents=True, params={"content": 0}
        )
        if response.status_code == 404:
            hub.expect(
                await hub.request(
                    "PUT", target, contents=True, json={"type": "directory"}
                ),
                (200, 201),
            )
        else:
            hub.expect(response)


async def prepare_inputs(db, user, hub, folder, document):
    from .dataset_access import readable
    from .notebook_outputs import copy_input

    from .input_sources import materialize

    for item in document.get("metadata", {}).get("arena_input_sources", []):
        await materialize(db, user, hub, folder, item)
    await mkdir(user, hub, folder)
    for item in document.get("metadata", {}).get("arena_inputs", []):
        dataset = readable(db, item["id"], user)
        content = (DATA_DIR / "uploads" / dataset.storage_key).read_bytes()
        await hub.request(
            "PUT",
            endpoint(user, f"{folder}/arena-input-{dataset.id}.csv"),
            contents=True,
            json={
                "type": "file",
                "format": "base64",
                "content": base64.b64encode(content).decode(),
            },
        )
    for item in document.get("metadata", {}).get("arena_notebook_inputs", []):
        await copy_input(db, item["id"], user, hub, folder)


async def snapshot_outputs(db, notebook, user, hub, folder):
    """Snapshot regular visible files, excluding attached inputs and notebook internals."""
    pending = [folder]
    files = []
    while pending:
        current = pending.pop()
        response = await hub.request("GET", endpoint(user, current), contents=True)
        if response.status_code == 404:
            continue  # Notebook has not started a scoped execution yet.
        listing = hub.expect(response).json()
        if listing.get("type") != "directory":
            continue
        for item in listing.get("content", []):
            name = item.get("name", "")
            if (
                not name
                or name.startswith(".")
                or "/" in name
                or "\\" in name
                or name == "input"
                or name.startswith("arena-input-")
                or name.endswith(".ipynb")
            ):
                continue
            path = current + "/" + name
            if item.get("type") == "directory":
                if len(PurePosixPath(path).parts) > 12:
                    raise HTTPException(
                        422, "Notebook output folders are too deeply nested"
                    )
                pending.append(path)
            elif item.get("type") == "file":
                files.append((path, item.get("size", 0)))
            if len(files) + len(pending) > 200:
                raise HTTPException(
                    422, "Save supports up to 200 notebook output files/folders"
                )
    if sum(size or 0 for _, size in files) > 50 * 1024 * 1024:
        raise HTTPException(422, "Saved notebook output files must total 50 MB or less")
    root = DATA_DIR / "notebook-outputs"
    root.mkdir(exist_ok=True)
    total = 0
    for path, _ in files:
        result = hub.expect(
            await hub.request(
                "GET", endpoint(user, path), contents=True, params={"format": "base64"}
            )
        ).json()
        content = base64.b64decode(result["content"])
        total += len(content)
        if total > 50 * 1024 * 1024:
            raise HTTPException(422, "Notebook output exceeds 50 MB")
        filename = path[len(folder) + 1 :]
        if len(filename) > 255:
            raise HTTPException(
                422, "Notebook output paths must be shorter than 256 characters"
            )
        from .notebook_outputs import store_snapshot

        store_snapshot(db, notebook.id, user.id, filename, content)


def collect_job_files(work):
    """Collect successful isolated-job artifacts, excluding evaluation inputs/secrets."""
    import os
    from .isolated_runner import read_result

    files = []
    total = 0
    excluded = {"input", "test.csv", "source.ipynb", "executed.ipynb", "runner.py"}
    for directory, directories, names in os.walk(work, followlinks=False):
        directories[:] = [
            name
            for name in directories
            if not name.startswith(".")
            and name != "input"
            and not (work.__class__(directory) / name).is_symlink()
        ]
        for name in names:
            path = work.__class__(directory) / name
            if (
                name.startswith(".")
                or name.startswith("arena-input-")
                or name in excluded
                or path.is_symlink()
            ):
                continue
            relative = path.relative_to(work).as_posix()
            if len(relative) > 255 or len(files) >= 200:
                raise ValueError("Too many output files or output path too long")
            content = read_result(path, 50 * 1024 * 1024)
            total += len(content)
            if total > 50 * 1024 * 1024:
                raise ValueError("Notebook output files exceed 50 MB")
            files.append((relative, content))
    return files


def capture_completed_job(db, job, files):
    from .notebook_outputs import store_snapshot

    for filename, content in files:
        store_snapshot(db, job.notebook_id, job.owner_id, filename, content)
