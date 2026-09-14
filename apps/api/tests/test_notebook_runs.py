import asyncio
import json

import pytest
from sqlalchemy.orm import sessionmaker

from app import compute_worker, notebook_runs, runtime_jobs
from app.db import get_db
from app.main import app
from app.models import NotebookRun, NotebookSchedule, SiteSetting

PASSWORD = "good-password-123"


@pytest.fixture
def worker_db(monkeypatch):
    with next(app.dependency_overrides[get_db]()) as db:
        factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(compute_worker, "SessionLocal", factory)
    return factory


def notebook(member, title="Background run"):
    return member.post(
        "/api/notebooks", json={"title": title, "code": "print('hello')"}
    ).json()["id"]


def execute(worker_db, run_id):
    with worker_db() as db:
        assert compute_worker.claim(db) == ("run", run_id)
    asyncio.run(compute_worker.execute_run(run_id))
    compute_worker.release("run", run_id)


def test_owner_run_stores_executed_version_outputs_and_log(
    member, worker_db, monkeypatch
):
    id = notebook(member)
    path = f"/api/code/{id}/runs"
    queued = member.post(path, json={"accelerator": "cpu"})
    assert queued.status_code == 202, queued.text
    run = queued.json()
    assert run["status"] == "queued" and run["internet"] is False
    assert member.post(path).status_code == 409

    member.post("/api/auth/logout")
    member.post(
        "/api/auth/register", json={"username": "stranger", "password": PASSWORD}
    )
    assert member.post(path).status_code == 404
    assert member.get(path).status_code == 404
    assert member.post(f"{path}/{run['id']}/cancel").status_code == 404
    member.post("/api/auth/logout")
    member.post("/api/auth/login", json={"username": "learner", "password": PASSWORD})

    async def fake_run(name, work, env, timeout, active, gpus=None):
        assert name.startswith("arena-run-") and active() and gpus == 0
        assert env["ARENA_CELL_TIMEOUT_SECONDS"]
        executed = json.loads((work / "source.ipynb").read_text())
        executed["cells"][0]["outputs"] = [
            {"output_type": "stream", "name": "stdout", "text": "hello\n"}
        ]
        executed["cells"][0]["execution_count"] = 1
        (work / "executed.ipynb").write_text(json.dumps(executed))
        (work / "result.json").write_text('{"status": "succeeded", "error": ""}')
        (work / "model.txt").write_text("weights")

    monkeypatch.setattr(runtime_jobs, "run", fake_run)
    execute(worker_db, run["id"])
    detail = member.get(f"{path}/{run['id']}").json()
    assert detail["status"] == "succeeded" and "hello" in detail["log"]
    assert (
        detail["output_files"] == 1 and detail["started_at"] and detail["finished_at"]
    )
    versions = member.get(f"/api/code/{id}/versions").json()
    assert versions[0]["id"] == detail["executed_version_id"]
    assert versions[0]["label"]["name"] == f"Run {run['id']}"
    executed = member.get(f"/api/code/{id}/versions/{versions[0]['id']}").json()
    assert executed["cells"][0]["outputs"][0]["text"] == "hello\n"
    outputs = member.get(f"/api/notebook-outputs?notebook_id={id}").json()["items"]
    assert [row["filename"] for row in outputs] == ["model.txt"]
    assert [row["id"] for row in member.get(path).json()] == [run["id"]]


def test_failed_cancelled_and_timed_out_runs(member, worker_db, monkeypatch):
    id = notebook(member)
    path = f"/api/code/{id}/runs"

    async def failing(name, work, env, timeout, active, gpus=None):
        executed = json.loads((work / "source.ipynb").read_text())
        executed["cells"][0]["outputs"] = [
            {
                "output_type": "error",
                "ename": "ValueError",
                "evalue": "boom",
                "traceback": ["\x1b[31mValueError\x1b[0m: boom"],
            }
        ]
        (work / "executed.ipynb").write_text(json.dumps(executed))
        (work / "result.json").write_text(
            json.dumps({"status": "failed", "error": "CellExecutionError"})
        )

    monkeypatch.setattr(runtime_jobs, "run", failing)
    run = member.post(path).json()
    execute(worker_db, run["id"])
    detail = member.get(f"{path}/{run['id']}").json()
    assert detail["status"] == "failed" and "ValueError: boom" in detail["log"]
    assert "\x1b" not in detail["log"] and detail["executed_version_id"] is None
    assert len(member.get(f"/api/code/{id}/versions").json()) == 1

    run = member.post(path).json()
    with worker_db() as db:
        compute_worker.claim(db)
    cancelled = member.post(f"{path}/{run['id']}/cancel").json()
    assert cancelled["status"] == "cancelled"
    compute_worker.fail("run", run["id"], ValueError("Evaluation cancelled"))
    assert member.get(f"{path}/{run['id']}").json()["status"] == "cancelled"

    run = member.post(path).json()
    with worker_db() as db:
        compute_worker.claim(db)
    compute_worker.fail("run", run["id"], ValueError("Job failed: DeadlineExceeded"))
    assert member.get(f"{path}/{run['id']}").json()["status"] == "timed_out"
    assert member.delete(f"/api/work/notebooks/{id}").status_code == 204


def test_schedules_enqueue_idempotently_catch_up_once_and_disable(member, worker_db):
    id = notebook(member)
    path = f"/api/code/{id}/schedules"
    assert (
        member.post(path, json={"frequency": "hourly", "interval_hours": 0}).status_code
        == 422
    )
    assert (
        member.post(path, json={"frequency": "daily", "time_utc": "25:00"}).status_code
        == 422
    )
    schedule = member.post(path, json={"frequency": "daily", "time_utc": "06:30"})
    assert schedule.status_code == 201, schedule.text
    schedule = schedule.json()
    assert schedule["status"] == "active" and schedule["next_run_at"].endswith(
        "06:30:00+00:00"
    )
    with worker_db() as db:
        db.merge(SiteSetting(key="max_schedules_per_user", value="1"))
        db.commit()
    assert member.post(path, json={"frequency": "weekly"}).status_code == 409
    item = f"{path}/{schedule['id']}"
    assert member.post(item + "/pause").json()["next_run_at"] is None
    assert member.post(item + "/resume").json()["status"] == "active"
    weekly = member.put(
        item, json={"frequency": "weekly", "weekday": 2, "time_utc": "08:00"}
    )
    assert weekly.json()["frequency"] == "weekly"

    with worker_db() as db:
        due = db.get(NotebookSchedule, schedule["id"]).next_run_at
        first = notebook_runs.enqueue_due(db, at=due + 5)
        assert len(first) == 1
        # A restarted scheduler at the same moment enqueues nothing more.
        assert notebook_runs.enqueue_due(db, at=due + 5) == []
    member.post(f"/api/code/{id}/runs/{first[0]}/cancel")

    with worker_db() as db:
        row = db.get(NotebookSchedule, schedule["id"])
        # The worker was down for three weeks after the next slot.
        later = row.next_run_at + 21 * 86400 + 60
        assert len(notebook_runs.enqueue_due(db, at=later)) == 1
        row = db.get(NotebookSchedule, schedule["id"])
        assert later < row.next_run_at <= later + 7 * 86400

    for failure in range(3):
        with worker_db() as db:
            run = db.query(NotebookRun).filter_by(status="queued").one()
        with worker_db() as db:
            assert compute_worker.claim(db) == ("run", run.id)
        compute_worker.fail("run", run.id, ValueError("boom"))
        if failure < 2:
            with worker_db() as db:
                at = db.get(NotebookSchedule, schedule["id"]).next_run_at + 1
                assert len(notebook_runs.enqueue_due(db, at=at)) == 1
    [current] = member.get(path).json()
    assert current["status"] == "disabled" and current["consecutive_failures"] == 3
    assert current["last_run"]["status"] == "failed"
    messages = [row["message"] for row in member.get("/api/notifications").json()]
    assert sum("scheduled notebook run failed" in text for text in messages) == 3
    assert any("disabled after repeated failures" in text for text in messages)
    assert member.post(item + "/resume").json()["consecutive_failures"] == 0
    assert member.delete(item).status_code == 204
    assert member.get(path).json() == []
