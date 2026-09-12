"""Durable benchmark queue using the same offline CPU boundary as notebook runs."""

import asyncio
import contextlib
import json
import math
import os
import secrets
from pathlib import Path
from sqlalchemy import select
from .db import DATA_DIR, SessionLocal
from .models import BenchmarkRun, now
from .isolated_runner import read_result


def recover(db):
    for row in db.scalars(select(BenchmarkRun).where(BenchmarkRun.status == "running")):
        row.status, row.error, row.finished_at = (
            "failed",
            "Worker restarted; run the evaluation again",
            now(),
        )
    db.commit()


def finish(id, payload):
    with SessionLocal() as db:
        row = db.scalar(
            select(BenchmarkRun).where(BenchmarkRun.id == id).with_for_update()
        )
        if not row or row.status != "running":
            return
        snapshot = json.loads(row.snapshot)
        expected = {
            (m["version_id"], t["version_id"])
            for m in snapshot["models"]
            for t in snapshot["tasks"]
        }
        cells = payload["results"]
        actual = {(c["model_version_id"], c["task_version_id"]) for c in cells}
        if actual != expected or len(cells) != len(expected):
            raise ValueError("Incomplete evaluation matrix")
        for cell in cells:
            if cell["status"] not in ("succeeded", "failed"):
                raise ValueError("Invalid evaluation status")
            if cell["status"] == "succeeded" and (
                not isinstance(cell["score"], (int, float))
                or not math.isfinite(cell["score"])
                or not 0 <= cell["score"] <= 1
            ):
                raise ValueError("Invalid benchmark score")
        row.results, row.logs = (
            json.dumps(cells, allow_nan=False),
            str(payload.get("logs", ""))[:50000],
        )
        # Finished matrices can contain failed model/task cells, which stay unranked.
        row.status, row.finished_at = "succeeded", now()
        db.commit()


async def execute(id):
    root = DATA_DIR / "evaluations"
    root.mkdir(exist_ok=True)
    name = f"benchmark-{id}-{secrets.token_hex(8)}"
    work = root / name
    work.mkdir(mode=0o700)
    with SessionLocal() as db:
        row = db.get(BenchmarkRun, id)
        (work / "snapshot.json").write_text(row.snapshot)
        snapshot = json.loads(row.snapshot)
    (work / "runner.py").write_bytes(
        (Path(__file__).parent / "benchmark_runner.py").read_bytes()
    )
    (work / "inference").mkdir()
    from .runtime_jobs import run
    from .benchmark_providers import broker

    def active():
        with SessionLocal() as db:
            current = db.get(BenchmarkRun, id)
            return bool(current and current.status == "running")

    directory_fd = os.open(
        work / "inference", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    )
    inference_task = asyncio.create_task(broker(directory_fd, snapshot["models"]))
    try:
        await run(f"arena-benchmark-{id}", work, {}, 300, active)
        payload = json.loads(read_result(work / "results.json", 10 * 1024 * 1024))
        finish(id, payload)
    finally:
        inference_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await inference_task
        os.close(directory_fd)


async def worker():
    while True:
        id = None
        try:
            with SessionLocal() as db:
                row = db.scalar(
                    select(BenchmarkRun)
                    .where(BenchmarkRun.status == "queued")
                    .order_by(BenchmarkRun.id)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                if row:
                    row.status, id = "running", row.id
                    db.commit()
            if id is None:
                await asyncio.sleep(2)
                continue
            await asyncio.wait_for(execute(id), timeout=300)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if id:
                with SessionLocal() as db:
                    row = db.scalar(
                        select(BenchmarkRun)
                        .where(BenchmarkRun.id == id)
                        .with_for_update()
                    )
                    if row and row.status == "running":
                        row.status, row.error, row.finished_at = (
                            "failed",
                            (str(exc) or "Evaluation exceeded the five-minute limit")[
                                :2000
                            ],
                            now(),
                        )
                        db.commit()
            await asyncio.sleep(1)
