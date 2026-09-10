"""Durable competition commits: execute a saved snapshot, evaluate, then publish."""

import asyncio
import base64
import contextlib
import json
import secrets
import time
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from websockets.asyncio.client import connect
from .auth import current_user
from .db import DATA_DIR, SessionLocal, get_db
from .models import (
    Notebook,
    NotebookWorkingCopy,
    NotebookCommit,
    NotebookPublication,
    Competition,
    CompetitionResource,
    Entry,
    Submission,
    ChallengeDetails,
    Dataset,
    User,
)
from .notebook_editor import Document, contents
from .notebook_runtime import HubClient, hub_username, start_session
from .code_pages import store_publication
from .kernel_channels import wait_for_kernel
from .scoring import score_csv

router = APIRouter(prefix="/api/code", tags=["Competition commits"])


def eligible(db, notebook_id, competition_id, user):
    notebook = db.scalar(
        select(Notebook).where(Notebook.id == notebook_id).with_for_update()
    )
    if not notebook or notebook.owner_id != user.id:
        raise HTTPException(404, "Your notebook was not found")
    competition = db.get(Competition, competition_id)
    if not competition:
        raise HTTPException(404, "Competition not found")
    if datetime.fromisoformat(competition.deadline) < datetime.now(timezone.utc):
        raise HTTPException(409, "Competition has closed")
    if not db.scalar(
        select(Entry.id).where(
            Entry.user_id == user.id, Entry.competition_id == competition_id
        )
    ):
        raise HTTPException(403, "Join the competition before committing code")
    return notebook, competition


class CommitInput(BaseModel):
    competition_id: int
    output_filename: str = Field(
        default="submission.csv", pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,200}\.csv$"
    )


def status(row):
    return {
        "id": row.id,
        "status": row.status,
        "score": row.score,
        "error": row.error,
        "competition_id": row.competition_id,
        "output_filename": row.output_filename,
        "created_at": row.created_at,
    }


@router.post("/{id}/commits", status_code=202)
def create_commit(
    id: int,
    data: CommitInput,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    notebook, _ = eligible(db, id, data.competition_id, user)
    active = db.scalar(
        select(NotebookCommit).where(
            NotebookCommit.notebook_id == id,
            NotebookCommit.status.in_(["queued", "running"]),
        )
    )
    if active:
        raise HTTPException(409, "This notebook already has a commit in progress")
    working = db.get(NotebookWorkingCopy, id)
    if not working:
        raise HTTPException(409, "Save the notebook in the editor before committing")
    if (
        working.competition_id and working.competition_id != data.competition_id
    ) or db.scalar(
        select(CompetitionResource.id).where(
            CompetitionResource.kind == "notebooks",
            CompetitionResource.resource_id == id,
            CompetitionResource.competition_id != data.competition_id,
        )
    ):
        raise HTTPException(
            409, "Fork a separate notebook to enter a different competition"
        )
    document = Document.model_validate(json.loads(working.document)).model_dump()
    if not any(
        cell["cell_type"] == "code" and "".join(cell.get("source", "")).strip()
        for cell in document["cells"]
    ):
        raise HTTPException(422, "Add executable code before committing")
    working.competition_id = data.competition_id
    job = NotebookCommit(
        notebook_id=id,
        competition_id=data.competition_id,
        owner_id=user.id,
        document=json.dumps(document),
        output_filename=data.output_filename,
    )
    db.add(job)
    db.commit()
    return status(job)


@router.get("/{id}/commits/latest")
def latest_commit(id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    notebook = db.get(Notebook, id)
    if not notebook or notebook.owner_id != user.id:
        raise HTTPException(404, "Your notebook was not found")
    job = db.scalar(
        select(NotebookCommit)
        .where(NotebookCommit.notebook_id == id)
        .order_by(NotebookCommit.id.desc())
    )
    return status(job) if job else None


async def run_cell(hub, user, kernel, code):
    url = (
        hub.proxy_url.replace("http://", "ws://", 1).replace("https://", "wss://", 1)
        + f"/user/{hub_username(user)}/api/kernels/{kernel}/channels"
    )
    outputs, count, total = [], None, 0
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
                    "buffers": [],
                    "content": {
                        "code": code,
                        "silent": False,
                        "store_history": True,
                        "user_expressions": {},
                        "allow_stdin": False,
                        "stop_on_error": True,
                    },
                }
            )
        )
        deadline = time.monotonic() + 120
        failed = False
        clear_next = False
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError("A cell exceeded the 120-second execution limit")
            raw = await asyncio.wait_for(socket.recv(), remaining)
            if not isinstance(raw, str):
                continue
            message = json.loads(raw)
            if message.get("parent_header", {}).get("msg_id") != msg_id:
                continue
            kind, content = message["header"]["msg_type"], message["content"]
            total += len(raw)
            if total > 8 * 1024 * 1024:
                raise ValueError("Cell output exceeds the 8 MB limit")
            if kind == "status" and content.get("execution_state") == "idle":
                if failed:
                    raise ValueError(
                        "Notebook execution failed: "
                        + next(
                            (
                                str(o.get("evalue", "Python error"))
                                for o in outputs
                                if o["output_type"] == "error"
                            ),
                            "Python error",
                        )[:1000]
                    )
                return outputs, count
            if kind == "execute_input":
                count = content.get("execution_count")
            elif kind == "clear_output":
                if content.get("wait"):
                    clear_next = True
                else:
                    outputs = []
            elif kind in ("stream", "display_data", "execute_result", "error"):
                if clear_next:
                    outputs, clear_next = [], False
                outputs.append({**content, "output_type": kind})
                failed = failed or kind == "error"


async def execute_snapshot(job_id, hub=None):
    hub = hub or HubClient()
    kernel = None
    user = None
    directory = None
    try:
        with SessionLocal() as db:
            job = db.get(NotebookCommit, job_id)
            if not job:
                return
            user = db.get(User, job.owner_id)
            _, competition = eligible(db, job.notebook_id, job.competition_id, user)
            document = json.loads(job.document)
            details = db.get(ChallengeDetails, competition.id)
            test_csv = (
                details.test_csv
                if details
                else "id,temperature,working_day\n7,20,1\n8,10,1\n9,23,0\n"
            )
            filename = job.output_filename
            inputs = []
            for item in document.get("metadata", {}).get("arena_inputs", []):
                dataset = db.get(Dataset, item["id"])
                if not dataset:
                    raise ValueError("An attached dataset is no longer available")
                inputs.append(
                    (
                        f"arena-input-{dataset.id}.csv",
                        DATA_DIR / "uploads" / dataset.storage_key,
                    )
                )
        await start_session(user=user, hub=hub)
        deadline = time.monotonic() + 240
        while (await hub.status(user))["state"] != "ready":
            if time.monotonic() > deadline:
                raise ValueError("Notebook runtime did not start in time")
            await asyncio.sleep(1)
        directory = f"arena-commit-{job_id}-{secrets.token_hex(6)}"

        async def put(path, content, kind="file", format="text"):
            return hub.expect(
                await hub.request(
                    "PUT",
                    contents(user, path),
                    contents=True,
                    json={
                        "type": kind,
                        **(
                            {"format": format, "content": content}
                            if kind != "directory"
                            else {}
                        ),
                    },
                ),
                (200, 201),
            )

        await put(directory, None, "directory")
        await put(f"{directory}/test.csv", test_csv)
        for name, source in inputs:
            await put(
                f"{directory}/{name}",
                base64.b64encode(await asyncio.to_thread(source.read_bytes)).decode(),
                format="base64",
            )
        await put(f"{directory}/run.ipynb", document, "notebook", "json")
        session = hub.expect(
            await hub.request(
                "POST",
                f"/user/{hub_username(user)}/api/sessions",
                contents=True,
                json={
                    "path": f"{directory}/run.ipynb",
                    "name": f"commit-{job_id}",
                    "type": "notebook",
                    "kernel": {"name": "python3"},
                },
            ),
            (200, 201),
        ).json()
        kernel = session["kernel"]["id"]
        await run_cell(
            hub,
            user,
            kernel,
            'import os\nos.environ["ARENA_TEST_DATA"] = os.path.abspath("test.csv")\nos.environ["ARENA_SUBMISSION_FILE"] = os.path.abspath('
            + repr(filename)
            + ")",
        )
        for cell in document["cells"]:
            if cell["cell_type"] == "code":
                cell["outputs"], cell["execution_count"] = await run_cell(
                    hub, user, kernel, "".join(cell.get("source", ""))
                )
        response = await hub.request(
            "GET",
            contents(user, f"{directory}/{filename}"),
            contents=True,
            params={"format": "base64"},
        )
        if response.status_code == 404:
            raise ValueError(
                f"Notebook did not produce {filename}. Write an id,prediction CSV in the current working directory."
            )
        model = hub.expect(response).json()
        if model.get("size", 0) > 1024 * 1024:
            raise ValueError("Prediction CSV exceeds the 1 MB limit")
        content = base64.b64decode(model["content"])
        if len(content) > 1024 * 1024:
            raise ValueError("Prediction CSV exceeds the 1 MB limit")
        complete_commit(job_id, document, content)
    finally:
        if kernel and user:
            with contextlib.suppress(Exception):
                await hub.request(
                    "DELETE",
                    f"/user/{hub_username(user)}/api/kernels/{kernel}",
                    contents=True,
                )
        # The run directory is retained in the owner's durable workspace for inspection.


def complete_commit(job_id, document, predictions):
    with SessionLocal() as db:
        job = db.get(NotebookCommit, job_id)
        if not job or job.status != "running":
            return
        user = db.get(User, job.owner_id)
        notebook, competition = eligible(db, job.notebook_id, job.competition_id, user)
        score = score_csv(predictions, json.loads(competition.solution))
        store_publication(db, notebook, Document.model_validate(document))
        working = db.get(NotebookWorkingCopy, notebook.id)
        if working:
            working.private = 0
            publication = db.get(NotebookPublication, notebook.id)
            publication.forked_from = working.forked_from
        if not db.scalar(
            select(CompetitionResource.id).where(
                CompetitionResource.competition_id == competition.id,
                CompetitionResource.kind == "notebooks",
                CompetitionResource.resource_id == notebook.id,
            )
        ):
            db.add(
                CompetitionResource(
                    competition_id=competition.id,
                    kind="notebooks",
                    resource_id=notebook.id,
                )
            )
        db.add(
            Submission(
                user_id=user.id,
                competition_id=competition.id,
                filename=job.output_filename,
                score=score,
            )
        )
        job.status, job.score, job.document = "succeeded", score, json.dumps(document)
        db.commit()


async def commit_worker():
    while True:
        job_id = None
        try:
            with SessionLocal() as db:
                job = db.scalar(
                    select(NotebookCommit)
                    .where(NotebookCommit.status == "queued")
                    .order_by(NotebookCommit.id)
                    .with_for_update(skip_locked=True)
                )
                if job:
                    job.status = "running"
                    job_id = job.id
                    db.commit()
            if job_id is None:
                await asyncio.sleep(2)
                continue
            await asyncio.wait_for(execute_snapshot(job_id), timeout=900)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if job_id:
                with SessionLocal() as db:
                    job = db.get(NotebookCommit, job_id)
                    if job:
                        job.status = "failed"
                        job.error = (
                            str(getattr(exc, "detail", exc))
                            or "Execution timed out or was interrupted"
                        )[:2000]
                        db.commit()
            await asyncio.sleep(1)


def migrate_forks(db):
    # Remove the old automatic competition links once, preserving owners' saved source.
    for publication in db.scalars(
        select(NotebookPublication).where(NotebookPublication.forked_from.is_not(None))
    ):
        if db.get(NotebookWorkingCopy, publication.notebook_id):
            continue
        links = list(
            db.scalars(
                select(CompetitionResource).where(
                    CompetitionResource.kind == "notebooks",
                    CompetitionResource.resource_id == publication.notebook_id,
                )
            )
        )
        if not links:
            continue
        db.add(
            NotebookWorkingCopy(
                notebook_id=publication.notebook_id,
                document=publication.document,
                forked_from=publication.forked_from,
                competition_id=links[0].competition_id if links else None,
                private=1,
            )
        )
        for link in links:
            db.delete(link)
    for job in db.scalars(
        select(NotebookCommit).where(NotebookCommit.status == "running")
    ):
        job.status, job.error = (
            "failed",
            "Server restarted during execution. Save and commit again.",
        )
    db.commit()
