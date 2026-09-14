"""Serial consumer for exercise attempts and background notebook runs, and the scheduler.

Runs in the single evaluation-worker replica next to the competition commit and
benchmark consumers, so at most three isolated workloads run at once. Every workload
is a disposable Kubernetes Job or Docker container from runtime_jobs: no network, no
service-account token, CPU/memory limits, a deadline and only its own work directory.
Short exercise attempts are claimed before notebook runs. GPU work stays queued while
all GPU capacity is allocated, and is refused once its owner's weekly quota is used.
"""

import asyncio
import json
import logging
import secrets
import shutil
import time

from fastapi import HTTPException
from sqlalchemy import select, update

from .db import DATA_DIR, SessionLocal
from .models import (
    CourseExercise,
    ExerciseAttempt,
    GpuUsage,
    Notebook,
    NotebookRun,
    User,
    now,
)
from .runtime_jobs import integer

# Executes a saved notebook top to bottom; cell errors are reported, not raised.
RUN_RUNNER = """import json
import os
from pathlib import Path
import nbformat
from nbclient import NotebookClient
from nbclient.exceptions import CellTimeoutError

notebook = nbformat.read("/work/source.ipynb", as_version=4)
result = {"status": "succeeded", "error": ""}
try:
    NotebookClient(
        notebook,
        timeout=int(os.environ["ARENA_CELL_TIMEOUT_SECONDS"]),
        kernel_name="python3",
        resources={"metadata": {"path": "/work"}},
    ).execute()
except CellTimeoutError as error:
    result = {"status": "timed_out", "error": "A cell exceeded its time limit: " + str(error)[:2000]}
except Exception as error:
    result = {"status": "failed", "error": (type(error).__name__ + ": " + str(error))[:4000]}
Path("/work/executed.ipynb").write_text(json.dumps(notebook))
Path("/work/result.json").write_text(json.dumps(result))
"""

# Runs learner code, then the hidden checker, in one fresh kernel. The checker file is
# read and deleted before learner code starts; its verdict is printed after a random
# marker the learner's code cannot know in advance. Only the learner cell's output is
# returned, never output produced while the checker runs.
ATTEMPT_RUNNER = r'''import asyncio
import json
import os
import secrets
from pathlib import Path

import nbformat
from nbclient import NotebookClient
from nbclient.exceptions import CellTimeoutError

WORK = Path("/work")
TIMEOUT = int(os.environ["ARENA_CELL_TIMEOUT_SECONDS"])
learner = (WORK / "learner.py").read_text()
checker = (WORK / "checker.py").read_text()
(WORK / "checker.py").unlink()
MARKER = "ARENA-VERDICT-" + secrets.token_hex(16) + ":"
CHECK = """
class _ArenaVerdict(BaseException):
    pass

def arena_pass(message="Correct!"):
    raise _ArenaVerdict(True, str(message))

def arena_fail(message="Not quite. Check the requirements and try again."):
    raise _ArenaVerdict(False, str(message))

try:
    exec(compile(%r, "checker", "exec"), globals())
except _ArenaVerdict as _arena_outcome:
    _arena_verdict = list(_arena_outcome.args)
except AssertionError as _arena_error:
    _arena_verdict = [False, str(_arena_error) or "A check did not pass."]
except Exception as _arena_error:
    _arena_verdict = [False, "The checks stopped with " + type(_arena_error).__name__ + ": " + str(_arena_error)]
else:
    _arena_verdict = [True, "Correct! All checks passed."]
print(%r + __import__("json").dumps(_arena_verdict))
""" % (checker, MARKER)


def text(value):
    return "".join(value) if isinstance(value, list) else str(value or "")


def learner_output(cell):
    stdout, errors = [], []
    for output in cell.outputs:
        kind = output.get("output_type")
        if kind == "stream":
            stdout.append(text(output.get("text")))
        elif kind in ("execute_result", "display_data"):
            plain = output.get("data", {}).get("text/plain")
            if plain:
                stdout.append(text(plain) + "\n")
        elif kind == "error":
            errors.append(
                "\n".join(output.get("traceback") or [])
                or output.get("ename", "Error") + ": " + output.get("evalue", "")
            )
    return "".join(stdout), "\n".join(errors)


async def main():
    notebook = nbformat.v4.new_notebook()
    notebook.cells = [nbformat.v4.new_code_cell(learner)]
    client = NotebookClient(
        notebook,
        timeout=TIMEOUT,
        kernel_name="python3",
        allow_errors=True,
        resources={"metadata": {"path": str(WORK)}},
    )
    result = {"status": "failed", "message": "", "stdout": "", "error": ""}
    try:
        async with client.async_setup_kernel():
            try:
                await client.async_execute_cell(notebook.cells[0], 0)
            except CellTimeoutError:
                result["message"] = f"Your code did not finish within {TIMEOUT} seconds."
                return result
            result["stdout"], result["error"] = learner_output(notebook.cells[0])
            if result["error"]:
                result["message"] = "Your code raised an error before the checks could run."
                return result
            notebook.cells.append(nbformat.v4.new_code_cell(CHECK))
            try:
                await client.async_execute_cell(notebook.cells[1], 1)
            except CellTimeoutError:
                result["message"] = f"The checks did not finish within {TIMEOUT} seconds."
                return result
            verdict = None
            for output in notebook.cells[1].outputs:
                if output.get("output_type") == "stream":
                    for line in text(output.get("text")).splitlines():
                        if line.startswith(MARKER):
                            verdict = json.loads(line[len(MARKER):])
            if isinstance(verdict, list) and len(verdict) == 2:
                result["status"] = "passed" if verdict[0] is True else "failed"
                result["message"] = str(verdict[1])
            else:
                result["message"] = (
                    "The checks could not report a result. Do not replace print or sys.stdout."
                )
    except Exception as error:
        result["message"] = "The Python kernel stopped unexpectedly (" + type(error).__name__ + "). It may have run out of memory."
    return result


outcome = asyncio.run(main())
(WORK / "result.json").write_text(json.dumps(outcome))
'''


def attempt_timeout():
    return integer("EXERCISE_TIMEOUT_SECONDS", 180, minimum=10, maximum=3600)


def attempt_cell_timeout():
    return integer("EXERCISE_CELL_TIMEOUT_SECONDS", 60, minimum=1, maximum=3600)


def run_timeout():
    return integer("EVALUATION_TIMEOUT_SECONDS", 900)


def recover(db):
    """Fail work interrupted by a restart without charging it to the learner."""
    for attempt in db.scalars(
        select(ExerciseAttempt).where(ExerciseAttempt.status == "running")
    ):
        attempt.status, attempt.finished_at = "failed", now()
        attempt.message = "The worker restarted during this check. Run it again."
    for run in db.scalars(select(NotebookRun).where(NotebookRun.status == "running")):
        run.status, run.finished_at = "failed", now()
        run.error = "The worker restarted during this run. Run the notebook again."
    db.execute(
        update(GpuUsage)
        .where(
            GpuUsage.kind.in_(("run", "attempt", "commit", "benchmark")),
            GpuUsage.ended_at.is_(None),
        )
        .values(ended_at=time.time())
    )
    db.commit()


def refuse(db, kind, row, message):
    if kind == "attempt":
        from .learn import finish_attempt

        finish_attempt(db, row, "failed", message=message, counted=False)
    else:
        from .notebook_runs import finish_run

        finish_run(db, row, "failed", message)


def claim(db):
    """Mark the next runnable attempt or run as running; returns (kind, id) or None."""
    from .compute import capacity, in_use, lock_pool, open_usage, require_gpu
    from .compute import workload_gpus

    for kind, model in (("attempt", ExerciseAttempt), ("run", NotebookRun)):
        rows = db.scalars(
            select(model)
            .where(model.status == "queued")
            .order_by(model.id)
            .with_for_update(skip_locked=True)
            .limit(20)
        ).all()
        for row in rows:
            owner_id = row.user_id if kind == "attempt" else row.owner_id
            if row.accelerator == "gpu":
                lock_pool(db)
                try:
                    require_gpu(db, db.get(User, owner_id), "job", check_capacity=False)
                except HTTPException as error:
                    refuse(db, kind, row, error.detail)
                    db.commit()
                    continue
                if in_use(db) + workload_gpus() > capacity(db):
                    continue  # Wait for a free GPU; CPU work behind it keeps running.
                open_usage(db, owner_id, kind, row.id, workload_gpus())
            row.status, row.started_at = "running", now()
            db.commit()
            return kind, row.id
    db.commit()
    return None


def workspace(prefix, id):
    root = DATA_DIR / "evaluations"
    root.mkdir(exist_ok=True)
    work = root / f"{prefix}-{id}-{secrets.token_hex(8)}"
    work.mkdir(mode=0o700)
    return work


def still_running(model, id):
    def active():
        with SessionLocal() as db:
            current = db.get(model, id)
            return bool(current and current.status == "running")

    return active


async def execute_attempt(id):
    from .compute import workload_gpus
    from .isolated_runner import read_result
    from .practice_inputs import stage_practice_inputs
    from .runtime_jobs import run

    work = workspace("attempt", id)
    try:
        with SessionLocal() as db:
            attempt = db.get(ExerciseAttempt, id)
            if not attempt or attempt.status != "running":
                return
            exercise = db.get(CourseExercise, attempt.exercise_id)
            if not exercise:
                raise ValueError("This exercise was removed")
            (work / "learner.py").write_text(attempt.code)
            (work / "checker.py").write_text(exercise.checker)
            (work / "runner.py").write_text(ATTEMPT_RUNNER)
            stage_practice_inputs(json.loads(exercise.inputs or "[]"), work)
            gpus = workload_gpus() if attempt.accelerator == "gpu" else 0
        await run(
            f"arena-attempt-{id}-{secrets.token_hex(3)}",
            work,
            {"ARENA_CELL_TIMEOUT_SECONDS": str(attempt_cell_timeout())},
            attempt_timeout(),
            still_running(ExerciseAttempt, id),
            gpus,
        )
        result = json.loads(read_result(work / "result.json", 1024 * 1024))
        from .learn import finish_attempt

        with SessionLocal() as db:
            attempt = db.scalar(
                select(ExerciseAttempt)
                .where(ExerciseAttempt.id == id)
                .with_for_update()
            )
            if not attempt or attempt.status != "running":
                return
            finish_attempt(
                db,
                attempt,
                "passed" if result.get("status") == "passed" else "failed",
                message=result.get("message") or "The checks did not pass.",
                stdout=result.get("stdout"),
                error=result.get("error"),
            )
            db.commit()
    finally:
        # Remove the learner's code and staged inputs; the checker is never kept.
        shutil.rmtree(work, ignore_errors=True)


async def execute_run(id):
    from .compute import workload_gpus
    from .isolated_runner import read_result, stage_inputs
    from .notebook_files import collect_job_files
    from .notebook_runs import complete_run
    from .runtime_jobs import run

    work = workspace("run", id)
    try:
        with SessionLocal() as db:
            row = db.get(NotebookRun, id)
            if not row or row.status != "running":
                return
            user = db.get(User, row.owner_id)
            notebook = db.get(Notebook, row.notebook_id)
            if not user or not notebook or notebook.owner_id != user.id:
                raise ValueError("The notebook is no longer available")
            document = json.loads(row.document)
            stage_inputs(db, user, document, work)
            (work / "source.ipynb").write_text(json.dumps(document))
            (work / "runner.py").write_text(RUN_RUNNER)
            gpus = workload_gpus() if row.accelerator == "gpu" else 0
        await run(
            f"arena-run-{id}-{secrets.token_hex(3)}",
            work,
            {
                "ARENA_CELL_TIMEOUT_SECONDS": str(
                    integer("NOTEBOOK_CELL_TIMEOUT_SECONDS", 120)
                )
            },
            run_timeout(),
            still_running(NotebookRun, id),
            gpus,
        )
        executed = json.loads(read_result(work / "executed.ipynb", 10 * 1024 * 1024))
        result = json.loads(read_result(work / "result.json", 1024 * 1024))
        files = (
            collect_job_files(work, ("result.json",))
            if result.get("status") == "succeeded"
            else []
        )
        with SessionLocal() as db:
            row = db.scalar(
                select(NotebookRun).where(NotebookRun.id == id).with_for_update()
            )
            if row:
                complete_run(db, row, executed, result, files)
                db.commit()
    finally:
        # Outputs are copied into immutable storage; the job directory is not kept.
        shutil.rmtree(work, ignore_errors=True)


def fail(kind, id, exc):
    """Record an execution error, a timeout or the end of a cancelled workload."""
    from .compute import close_usage

    timed_out = isinstance(exc, (asyncio.TimeoutError, TimeoutError)) or (
        "DeadlineExceeded" in str(exc)
    )
    message = str(getattr(exc, "detail", exc)) or "Execution was interrupted"
    model = ExerciseAttempt if kind == "attempt" else NotebookRun
    with SessionLocal() as db:
        row = db.scalar(select(model).where(model.id == id).with_for_update())
        if row is not None and row.status == "running":
            if kind == "attempt":
                from .learn import finish_attempt

                finish_attempt(
                    db,
                    row,
                    "failed",
                    message=(
                        f"Your code did not finish within {attempt_timeout()} seconds."
                        if timed_out
                        else f"The check could not run: {message}"
                    ),
                    counted=timed_out,
                )
            else:
                from .notebook_runs import finish_run

                finish_run(
                    db,
                    row,
                    "timed_out" if timed_out else "failed",
                    (
                        f"The run exceeded its {run_timeout()}-second limit."
                        if timed_out
                        else message
                    ),
                )
        close_usage(db, kind, id)
        db.commit()


def release(kind, id):
    from .compute import close_usage

    with SessionLocal() as db:
        close_usage(db, kind, id)
        db.commit()


async def worker():
    while True:
        claimed = None
        try:
            with SessionLocal() as db:
                claimed = claim(db)
            if claimed is None:
                await asyncio.sleep(2)
                continue
            kind, id = claimed
            if kind == "attempt":
                await asyncio.wait_for(execute_attempt(id), attempt_timeout() + 60)
            else:
                await asyncio.wait_for(execute_run(id), run_timeout() + 60)
            release(kind, id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            try:
                if claimed:
                    fail(*claimed, exc)
                else:
                    logging.getLogger(__name__).exception("Compute queue claim failed")
            except Exception:
                logging.getLogger(__name__).exception("Could not record a failure")
            await asyncio.sleep(1)


async def scheduler():
    from .notebook_runs import enqueue_due

    while True:
        try:
            with SessionLocal() as db:
                enqueue_due(db)
        except Exception:
            logging.getLogger(__name__).exception("Schedule check failed; will retry")
        await asyncio.sleep(integer("SCHEDULER_INTERVAL_SECONDS", 30, maximum=3600))
