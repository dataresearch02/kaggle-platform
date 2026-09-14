"""Save & Run All for any notebook owner, run history, and scheduled runs.

A run executes an immutable saved version in a fresh, network-less runtime through the
same broker as competition commits (see compute_worker.py). Success stores the executed
notebook as a new version and captures generated output files with the commit snapshot
rules and limits. Schedules are enqueued by the evaluation worker's scheduler loop:
`enqueue_due` records one run per schedule slot and moves `next_run_at` past the
current time, so restarts create no duplicates and downtime yields at most one
catch-up run. Three consecutive failures disable a schedule; failures and disabling
notify the owner.
"""

import json
import math
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import current_user
from .compute import (
    Accelerator,
    capacity,
    close_usage,
    gpu_supported,
    iso,
    lock_pool,
    require_gpu,
)
from .db import get_db
from .models import Notebook, NotebookRun, NotebookSchedule, NotebookVersion, now
from .site_settings import setting

router = APIRouter(prefix="/api/code", tags=["Notebook runs"])
ACTIVE = ("queued", "running")
MAX_CONSECUTIVE_FAILURES = 3
LOG_LIMIT = 50000
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def owned(db, id, user, lock=False):
    query = select(Notebook).where(Notebook.id == id)
    notebook = db.scalar(query.with_for_update() if lock else query)
    if not notebook or notebook.owner_id != user.id:
        raise HTTPException(404, "Your notebook was not found")
    return notebook


def has_code(document):
    return any(
        cell.get("cell_type") == "code" and "".join(cell.get("source", "")).strip()
        for cell in document.get("cells", [])
    )


def run_source(db, notebook, version_id=None):
    """The saved version to run: the requested one, else the latest."""
    query = select(NotebookVersion).where(NotebookVersion.notebook_id == notebook.id)
    if version_id is not None:
        query = query.where(NotebookVersion.id == version_id)
    version = db.scalar(query.order_by(NotebookVersion.id.desc()).limit(1))
    if version_id is not None and not version:
        raise HTTPException(404, "Version not found")
    if version:
        return version, json.loads(version.document)
    from .notebook_runtime import notebook_document

    # Legacy notebooks saved before version history run their saved working copy.
    return None, notebook_document(notebook, db, working=True)


def queue_run(db, notebook, accelerator="cpu", version_id=None, schedule=None):
    version, document = run_source(db, notebook, version_id)
    if not has_code(document):
        raise HTTPException(
            422, "Add executable code and save a version before running"
        )
    run = NotebookRun(
        notebook_id=notebook.id,
        owner_id=notebook.owner_id,
        version_id=version.id if version else None,
        document=json.dumps(document),
        accelerator=accelerator,
        trigger="schedule" if schedule else "manual",
        schedule_id=schedule.id if schedule else None,
        scheduled_for=schedule.next_run_at if schedule else None,
        status="queued",
    )
    db.add(run)
    return run


def seconds_between(start, end):
    if not start or not end:
        return None
    return round(
        (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds(), 1
    )


def run_json(run, detail=False):
    result = {
        "id": run.id,
        "notebook_id": run.notebook_id,
        "status": run.status,
        "accelerator": run.accelerator,
        "internet": False,
        "trigger": run.trigger,
        "schedule_id": run.schedule_id,
        "version_id": run.version_id,
        "executed_version_id": run.executed_version_id,
        "output_files": run.output_files,
        "error": run.error,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "duration_seconds": seconds_between(run.started_at, run.finished_at),
    }
    if detail:
        result["log"] = run.log
    return result


def text(value):
    return "".join(value) if isinstance(value, list) else str(value or "")


def build_log(executed, result):
    """A truncated plain-text log of cell streams, results and errors."""
    parts = []
    for index, cell in enumerate(executed.get("cells", []), start=1):
        if cell.get("cell_type") != "code":
            continue
        chunks = []
        for output in cell.get("outputs", []):
            kind = output.get("output_type")
            if kind == "stream":
                chunks.append(text(output.get("text")))
            elif kind == "error":
                chunks.append(
                    "\n".join(output.get("traceback") or [])
                    or f"{output.get('ename')}: {output.get('evalue')}"
                )
            elif kind in ("execute_result", "display_data"):
                plain = (output.get("data") or {}).get("text/plain")
                if plain:
                    chunks.append(text(plain))
        if chunks:
            parts.append(
                f"--- Cell {index} ---\n"
                + "".join(
                    chunk if chunk.endswith("\n") else chunk + "\n" for chunk in chunks
                )
            )
    if result.get("status") != "succeeded" and result.get("error"):
        parts.append("--- Run error ---\n" + str(result["error"]))
    log = ANSI.sub("", "\n".join(parts)).replace("\x00", "")
    if len(log) > LOG_LIMIT:
        log = log[:LOG_LIMIT] + "\n… log truncated …\n"
    return log


def finish_run(db, run, status, error="", log=None):
    run.status, run.finished_at = status, now()
    if error:
        run.error = ANSI.sub("", str(error))[:2000]
    if log is not None:
        run.log = log
    if run.accelerator == "gpu":
        close_usage(db, "run", run.id)
    schedule_result(db, run)


def complete_run(db, run, executed, result, files):
    """Store the outcome of a running job; the caller commits."""
    if run.status != "running":
        return
    notebook = db.get(Notebook, run.notebook_id)
    log = build_log(executed, result)
    status = result.get("status")
    if not notebook:
        finish_run(db, run, "failed", "The notebook was deleted", log)
        return
    if status != "succeeded":
        finish_run(
            db,
            run,
            status if status == "timed_out" else "failed",
            result.get("error") or "Notebook execution failed",
            log,
        )
        return
    from .notebook_editor import Document
    from .notebook_files import capture_completed_job
    from .notebook_versions import save_version

    try:
        document = Document.model_validate(executed).model_dump()
    except ValueError:
        finish_run(
            db, run, "failed", "The executed notebook is invalid or over 10 MB", log
        )
        return
    document["metadata"]["arena_version"] = {
        "name": f"Run {run.id}",
        "tags": ["executed", run.trigger],
    }
    document["metadata"]["arena_run"] = {"id": run.id, "accelerator": run.accelerator}
    version = save_version(db, notebook, document)
    db.flush()
    capture_completed_job(db, run, files)
    run.executed_version_id, run.output_files = version.id, len(files)
    finish_run(db, run, "succeeded", log=log)


def schedule_result(db, run):
    if run.schedule_id is None or run.status == "cancelled":
        return
    schedule = db.get(NotebookSchedule, run.schedule_id)
    if not schedule:
        return
    if run.status == "succeeded":
        schedule.consecutive_failures = 0
        return
    from .notifications import notify

    schedule.consecutive_failures = (schedule.consecutive_failures or 0) + 1
    notify(
        db,
        schedule.owner_id,
        "run",
        target_kind="code",
        target_id=run.notebook_id,
        detail={
            "event": "failed",
            "status": run.status,
            "run_id": run.id,
            "failures": schedule.consecutive_failures,
        },
    )
    if (
        schedule.consecutive_failures >= MAX_CONSECUTIVE_FAILURES
        and schedule.status == "active"
    ):
        schedule.status, schedule.next_run_at = "disabled", None
        schedule.disabled_reason = (
            f"Disabled after {MAX_CONSECUTIVE_FAILURES} consecutive failed runs."
            " Fix the notebook, then resume the schedule."
        )
        notify(
            db,
            schedule.owner_id,
            "run",
            target_kind="code",
            target_id=run.notebook_id,
            detail={"event": "disabled", "run_id": run.id, "schedule_id": schedule.id},
        )


def next_occurrence(schedule, after):
    """The first slot strictly after `after` (epoch seconds, UTC)."""
    if schedule.frequency == "hourly":
        step = schedule.interval_hours * 3600
        if after < schedule.anchor_at:
            return schedule.anchor_at
        return (
            schedule.anchor_at
            + (math.floor((after - schedule.anchor_at) / step) + 1) * step
        )
    hour, minute = (int(part) for part in schedule.time_utc.split(":"))
    candidate = datetime.fromtimestamp(after, timezone.utc).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    weekly = schedule.frequency == "weekly"
    if weekly:
        candidate += timedelta(days=(schedule.weekday - candidate.weekday()) % 7)
    if candidate.timestamp() <= after:
        candidate += timedelta(days=7 if weekly else 1)
    return candidate.timestamp()


def enqueue_due(db, at=None):
    """Enqueue due scheduled runs; returns the new run ids. Safe to repeat."""
    at = time.time() if at is None else at
    created = []
    due = db.scalars(
        select(NotebookSchedule)
        .where(
            NotebookSchedule.status == "active",
            NotebookSchedule.next_run_at <= at,
        )
        .order_by(NotebookSchedule.next_run_at)
        .with_for_update(skip_locked=True)
        .limit(100)
    ).all()
    for schedule in due:
        notebook = db.get(Notebook, schedule.notebook_id)
        if not notebook or notebook.owner_id != schedule.owner_id:
            schedule.status, schedule.next_run_at = "disabled", None
            schedule.disabled_reason = "The notebook is no longer available"
            continue
        slot = schedule.next_run_at
        recorded = db.scalar(
            select(NotebookRun.id).where(
                NotebookRun.schedule_id == schedule.id,
                NotebookRun.scheduled_for == slot,
            )
        )
        busy = db.scalar(
            select(NotebookRun.id)
            .where(
                NotebookRun.notebook_id == notebook.id,
                NotebookRun.status.in_(ACTIVE),
            )
            .limit(1)
        )
        # A slot that arrives while the previous run is still active is skipped.
        if not recorded and not busy:
            try:
                run = queue_run(db, notebook, schedule.accelerator, schedule=schedule)
            except HTTPException as error:
                run = NotebookRun(
                    notebook_id=notebook.id,
                    owner_id=notebook.owner_id,
                    document="{}",
                    accelerator=schedule.accelerator,
                    trigger="schedule",
                    schedule_id=schedule.id,
                    scheduled_for=slot,
                    status="queued",
                )
                db.add(run)
                db.flush()
                finish_run(db, run, "failed", str(error.detail))
            db.flush()
            created.append(run.id)
        # Missed slots during downtime collapse into the single run above.
        schedule.next_run_at = next_occurrence(schedule, at)
    db.commit()
    return created


class RunInput(BaseModel):
    accelerator: Accelerator = "cpu"
    version_id: Optional[int] = Field(default=None, ge=1)


class ScheduleInput(BaseModel):
    frequency: Literal["daily", "weekly", "hourly"]
    time_utc: str = Field(default="00:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    weekday: int = Field(default=0, ge=0, le=6)
    interval_hours: int = Field(default=24, ge=1, le=168)
    accelerator: Accelerator = "cpu"


def require_accelerator(db, accelerator):
    if accelerator == "gpu" and (not gpu_supported("job") or capacity(db) <= 0):
        raise HTTPException(409, "GPUs are not available on this site. Choose CPU.")


def schedule_json(db, schedule):
    last = db.scalar(
        select(NotebookRun)
        .where(NotebookRun.schedule_id == schedule.id)
        .order_by(NotebookRun.id.desc())
        .limit(1)
    )
    return {
        "id": schedule.id,
        "notebook_id": schedule.notebook_id,
        "frequency": schedule.frequency,
        "time_utc": schedule.time_utc,
        "weekday": schedule.weekday,
        "interval_hours": schedule.interval_hours,
        "accelerator": schedule.accelerator,
        "status": schedule.status,
        "consecutive_failures": schedule.consecutive_failures,
        "next_run_at": iso(schedule.next_run_at) if schedule.next_run_at else None,
        "disabled_reason": schedule.disabled_reason,
        "created_at": schedule.created_at,
        "last_run": run_json(last) if last else None,
    }


def owned_schedule(db, id, schedule_id, user):
    owned(db, id, user)
    schedule = db.scalar(
        select(NotebookSchedule)
        .where(NotebookSchedule.id == schedule_id)
        .with_for_update()
    )
    if not schedule or schedule.notebook_id != id:
        raise HTTPException(404, "Schedule not found")
    return schedule


@router.post("/{id}/runs", status_code=202)
def create_run(
    id: int,
    data: Optional[RunInput] = None,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    data = data or RunInput()
    notebook = owned(db, id, user, lock=True)
    if db.scalar(
        select(NotebookRun.id)
        .where(NotebookRun.notebook_id == id, NotebookRun.status.in_(ACTIVE))
        .limit(1)
    ):
        raise HTTPException(409, "This notebook already has a run in progress")
    if data.accelerator == "gpu":
        lock_pool(db)
        # Queued GPU runs wait in the worker until a GPU is free.
        require_gpu(db, user, "job", check_capacity=False)
    run = queue_run(db, notebook, data.accelerator, data.version_id)
    db.commit()
    return run_json(run)


@router.get("/{id}/runs")
def list_runs(
    id: int,
    before: int = Query(default=2147483647, ge=1),
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    owned(db, id, user)
    return [
        run_json(row)
        for row in db.scalars(
            select(NotebookRun)
            .where(NotebookRun.notebook_id == id, NotebookRun.id < before)
            .order_by(NotebookRun.id.desc())
            .limit(50)
        )
    ]


@router.get("/{id}/runs/{run_id}")
def get_run(
    id: int, run_id: int, user=Depends(current_user), db: Session = Depends(get_db)
):
    owned(db, id, user)
    run = db.get(NotebookRun, run_id)
    if not run or run.notebook_id != id:
        raise HTTPException(404, "Run not found")
    return run_json(run, detail=True)


@router.post("/{id}/runs/{run_id}/cancel")
def cancel_run(
    id: int, run_id: int, user=Depends(current_user), db: Session = Depends(get_db)
):
    owned(db, id, user)
    run = db.scalar(
        select(NotebookRun).where(NotebookRun.id == run_id).with_for_update()
    )
    if not run or run.notebook_id != id:
        raise HTTPException(404, "Run not found")
    if run.status in ACTIVE:
        # The worker sees the new status, deletes the Job and stops waiting.
        finish_run(db, run, "cancelled", "Cancelled by owner")
        db.commit()
    return run_json(run, detail=True)


@router.get("/{id}/schedules")
def list_schedules(id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    owned(db, id, user)
    return [
        schedule_json(db, row)
        for row in db.scalars(
            select(NotebookSchedule)
            .where(NotebookSchedule.notebook_id == id)
            .order_by(NotebookSchedule.id)
        )
    ]


@router.post("/{id}/schedules", status_code=201)
def create_schedule(
    id: int,
    data: ScheduleInput,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    notebook = owned(db, id, user)
    db.refresh(user, with_for_update=True)
    limit = int(setting(db, "max_schedules_per_user"))
    if (
        db.scalar(
            select(func.count())
            .select_from(NotebookSchedule)
            .where(NotebookSchedule.owner_id == user.id)
        )
        >= limit
    ):
        raise HTTPException(
            409,
            f"You can keep up to {limit} scheduled runs. Delete one before adding"
            " another.",
        )
    require_accelerator(db, data.accelerator)
    if not has_code(run_source(db, notebook)[1]):
        raise HTTPException(422, "Add executable code and save a version first")
    moment = time.time()
    schedule = NotebookSchedule(
        notebook_id=id,
        owner_id=user.id,
        **data.model_dump(),
        status="active",
        anchor_at=moment,
    )
    schedule.next_run_at = next_occurrence(schedule, moment)
    db.add(schedule)
    db.commit()
    return schedule_json(db, schedule)


@router.put("/{id}/schedules/{schedule_id}")
def update_schedule(
    id: int,
    schedule_id: int,
    data: ScheduleInput,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    schedule = owned_schedule(db, id, schedule_id, user)
    require_accelerator(db, data.accelerator)
    for key, value in data.model_dump().items():
        setattr(schedule, key, value)
    moment = time.time()
    schedule.anchor_at = moment
    if schedule.status == "active":
        schedule.next_run_at = next_occurrence(schedule, moment)
    db.commit()
    return schedule_json(db, schedule)


@router.post("/{id}/schedules/{schedule_id}/pause")
def pause_schedule(
    id: int, schedule_id: int, user=Depends(current_user), db: Session = Depends(get_db)
):
    schedule = owned_schedule(db, id, schedule_id, user)
    if schedule.status == "active":
        schedule.status, schedule.next_run_at = "paused", None
    db.commit()
    return schedule_json(db, schedule)


@router.post("/{id}/schedules/{schedule_id}/resume")
def resume_schedule(
    id: int, schedule_id: int, user=Depends(current_user), db: Session = Depends(get_db)
):
    schedule = owned_schedule(db, id, schedule_id, user)
    require_accelerator(db, schedule.accelerator)
    schedule.status, schedule.disabled_reason = "active", ""
    schedule.consecutive_failures = 0
    schedule.next_run_at = next_occurrence(schedule, time.time())
    db.commit()
    return schedule_json(db, schedule)


@router.delete("/{id}/schedules/{schedule_id}", status_code=204)
def delete_schedule(
    id: int, schedule_id: int, user=Depends(current_user), db: Session = Depends(get_db)
):
    db.delete(owned_schedule(db, id, schedule_id, user))
    db.commit()
    return Response(status_code=204)
