"""Trusted worker launches untrusted notebooks in disposable, offline containers."""

import asyncio
import contextlib
import json
import os
import secrets
import stat
from pathlib import Path

import httpx
from .db import DATA_DIR, SessionLocal
from .models import NotebookCommit, User, ChallengeDetails
from .dataset_access import readable

RUNNER = """import os
import json
from pathlib import Path
import nbformat
from nbclient import NotebookClient
os.environ["ARENA_TEST_DATA"] = "/work/test.csv"
os.environ["ARENA_SUBMISSION_FILE"] = "/work/" + os.environ["PREDICTION_FILE"]
notebook = nbformat.read("/work/source.ipynb", as_version=4)
NotebookClient(notebook, timeout=120, kernel_name="python3", resources={"metadata": {"path": "/work"}}).execute()
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
        (work / "source.ipynb").write_text(json.dumps(document))
        (work / "runner.py").write_text(RUNNER)
    # Containers run as the API storage UID; the privileged broker never runs user code.
    for path in [work, *work.iterdir()]:
        if os.geteuid() == 0:
            os.chown(path, 10001, 10001)
    host_root = Path(os.environ["EVALUATION_HOST_PATH"])
    if not host_root.is_absolute():
        raise ValueError("EVALUATION_HOST_PATH must be absolute")
    transport = httpx.AsyncHTTPTransport(
        uds=os.getenv("DOCKER_SOCKET_PATH", "/var/run/docker.sock")
    )
    async with httpx.AsyncClient(
        transport=transport, base_url="http://docker", timeout=30
    ) as docker:
        created = False
        try:
            response = await docker.post(
                "/containers/create",
                params={"name": container_name},
                json={
                    "Image": os.getenv("EVALUATION_IMAGE", "arena-singleuser:5.3.0"),
                    "User": "10001:10001",
                    "WorkingDir": "/work",
                    "Entrypoint": ["python"],
                    "Cmd": ["/work/runner.py"],
                    "Env": [
                        "HOME=/tmp",
                        "JUPYTER_RUNTIME_DIR=/tmp/jupyter",
                        f"PREDICTION_FILE={filename}",
                    ],
                    "Labels": {"arena.evaluation": "true", "arena.job": str(job_id)},
                    "HostConfig": {
                        "NetworkMode": "none",
                        "ReadonlyRootfs": True,
                        "Binds": [f"{host_root / name}:/work:rw,z"],
                        "Tmpfs": {"/tmp": "rw,nosuid,nodev,size=268435456"},
                        "Memory": 2147483648,
                        "NanoCpus": 2000000000,
                        "PidsLimit": 256,
                        "CapDrop": ["ALL"],
                        "SecurityOpt": ["no-new-privileges:true"],
                    },
                },
            )
            response.raise_for_status()
            created = True
            (
                await docker.post(f"/containers/{container_name}/start")
            ).raise_for_status()
            # Short polling also lets cancellation and timeout promptly reach cleanup.
            while True:
                with SessionLocal() as db:
                    current = db.get(NotebookCommit, job_id)
                    if not current or current.status != "running":
                        raise ValueError("Evaluation cancelled")
                response = await docker.get(f"/containers/{container_name}/json")
                response.raise_for_status()
                state = response.json()["State"]
                if not state["Running"]:
                    if state.get("OOMKilled"):
                        raise ValueError("Notebook exceeded the 2 GB memory limit")
                    if state.get("ExitCode") != 0:
                        raise ValueError(
                            "Notebook execution failed. Run the notebook interactively to inspect Python errors."
                        )
                    break
                await asyncio.sleep(1)
            if not (work / filename).exists():
                raise ValueError(f"Notebook did not produce {filename}")
            executed = json.loads(
                read_result(work / "executed.ipynb", 10 * 1024 * 1024)
            )
            predictions = read_result(work / filename, 1024 * 1024)
            complete_commit(job_id, executed, predictions)
        finally:
            if created:
                with contextlib.suppress(Exception):
                    await docker.delete(
                        f"/containers/{container_name}", params={"force": "true"}
                    )
