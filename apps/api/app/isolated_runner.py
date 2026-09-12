"""Trusted worker launches untrusted notebooks in disposable, offline containers."""

import json
import os
import secrets
import stat
from pathlib import Path

from .db import DATA_DIR, SessionLocal
from .models import NotebookCommit, User, ChallengeDetails
from .dataset_access import readable
from .runtime_jobs import run, integer

RUNNER = """import os
import json
from pathlib import Path
import nbformat
from nbclient import NotebookClient
os.environ["ARENA_TEST_DATA"] = "/work/test.csv"
os.environ["ARENA_SUBMISSION_FILE"] = "/work/" + os.environ["PREDICTION_FILE"]
notebook = nbformat.read("/work/source.ipynb", as_version=4)
NotebookClient(notebook, timeout=int(os.environ["ARENA_CELL_TIMEOUT_SECONDS"]), kernel_name="python3", resources={"metadata": {"path": "/work"}}).execute()
Path("/work/executed.ipynb").write_text(json.dumps(notebook))
"""


def read_result(path, limit):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("Invalid or oversized execution result")
        result = stream.read(limit + 1)
        if len(result) > limit:
            raise ValueError("Execution result exceeds its size limit")
        return result


async def execute(job_id):
    from .notebook_commits import eligible, complete_commit

    root = DATA_DIR / "evaluations"
    root.mkdir(exist_ok=True)
    name = f"job-{job_id}-{secrets.token_hex(12)}"
    work = root / name
    work.mkdir(mode=0o700)
    container_name = f"arena-evaluation-{job_id}"
    with SessionLocal() as db:
        job = db.get(NotebookCommit, job_id)
        if not job or job.status != "running":
            return
        user = db.get(User, job.owner_id)
        _, competition = eligible(db, job.notebook_id, job.competition_id, user)
        details = db.get(ChallengeDetails, competition.id)
        document = json.loads(job.document)
        filename = job.output_filename
        (work / "test.csv").write_text(
            details.test_csv
            if details
            else "id,temperature,working_day\n7,20,1\n8,10,1\n9,23,0\n"
        )
        for item in document.get("metadata", {}).get("arena_inputs", []):
            dataset = readable(db, item["id"], user)
            (work / f"arena-input-{dataset.id}.csv").write_bytes(
                (DATA_DIR / "uploads" / dataset.storage_key).read_bytes()
            )
        from .notebook_outputs import readable as readable_output, input_path

        for item in document.get("metadata", {}).get("arena_notebook_inputs", []):
            output = readable_output(db, item["id"], user)
            target = work / input_path(output)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(
                (DATA_DIR / "notebook-outputs" / output.storage_key).read_bytes()
            )
        from .input_sources import resolve_attachment

        for item in document.get("metadata", {}).get("arena_input_sources", []):
            source, files = resolve_attachment(db, user, item)
            for input_file in files:
                target = work / source["path"] / input_file.filename
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(input_file.read(db))
        (work / "source.ipynb").write_text(json.dumps(document))
        (work / "runner.py").write_text(RUNNER)

    def active():
        with SessionLocal() as db:
            current = db.get(NotebookCommit, job_id)
            return bool(current and current.status == "running")

    await run(
        container_name,
        work,
        {
            "PREDICTION_FILE": filename,
            "ARENA_CELL_TIMEOUT_SECONDS": str(
                integer("NOTEBOOK_CELL_TIMEOUT_SECONDS", 120)
            ),
        },
        integer("EVALUATION_TIMEOUT_SECONDS", 900),
        active,
    )
    if not (work / filename).exists():
        raise ValueError(f"Notebook did not produce {filename}")
    executed = json.loads(read_result(work / "executed.ipynb", 10 * 1024 * 1024))
    predictions = read_result(work / filename, 1024 * 1024)
    from .notebook_files import collect_job_files

    output_files = collect_job_files(work)
    complete_commit(job_id, executed, predictions, output_files)
