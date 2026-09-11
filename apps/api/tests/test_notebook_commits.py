import json
import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.db import get_db
from app.models import (
    NotebookWorkingCopy,
    NotebookCommit,
    CompetitionResource,
    Submission,
)
from app import notebook_commits


@pytest.fixture
def commit_db(monkeypatch):
    with next(app.dependency_overrides[get_db]()) as db:
        factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(notebook_commits, "SessionLocal", factory)
    return factory


def test_fork_is_private_save_is_not_publish_and_success_commits(member, commit_db):
    fork = member.post("/api/code/1/fork?competition_id=1").json()["id"]
    path = f"/api/code/{fork}"
    assert member.get(path).json()["private"] is True
    assert (
        member.get("/api/code?competition_id=1&filter=your-work").json()["items"] == []
    )
    assert any(
        row["id"] == fork
        for row in member.get("/api/code?filter=your-work").json()["items"]
    )
    document = member.get(path).json()["document"]
    assert member.put(path + "/publication", json=document).status_code == 409
    assert (
        member.post(f"/api/competitions/1/resources/notebooks/{fork}").status_code
        == 409
    )
    assert member.post(path + "/commits", json={"competition_id": 1}).status_code == 403
    member.post("/api/competitions/1/join")
    response = member.post(path + "/commits", json={"competition_id": 1})
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    assert member.post(path + "/commits", json={"competition_id": 1}).status_code == 409
    with commit_db() as db:
        job = db.get(NotebookCommit, job_id)
        assert json.loads(job.document) == document
        job.status = "running"
        # Edits after queueing cannot change the committed snapshot.
        working = db.get(NotebookWorkingCopy, fork)
        newer = json.loads(working.document)
        newer["cells"][0]["source"] = 'print("private next draft")'
        working.document = json.dumps(newer)
        db.commit()
    with pytest.raises(ValueError):
        notebook_commits.complete_commit(job_id, document, b"id,prediction\n999,0\n")
    assert (
        member.get("/api/code?competition_id=1&filter=your-work").json()["items"] == []
    )
    notebook_commits.complete_commit(
        job_id, document, b"id,prediction\n7,240\n8,100\n9,300\n"
    )
    latest = member.get(path + "/commits/latest").json()
    assert latest["status"] == "succeeded" and latest["score"] == 0
    assert [
        row["id"]
        for row in member.get("/api/code?competition_id=1&filter=your-work").json()[
            "items"
        ]
    ] == [fork]
    assert member.get(path).json()["document"]["cells"] == document["cells"]
    # Completion is idempotent; no duplicate scoring or links.
    notebook_commits.complete_commit(
        job_id, document, b"id,prediction\n7,240\n8,100\n9,300\n"
    )
    with commit_db() as db:
        assert (
            len(list(db.scalars(select(Submission).where(Submission.user_id == 2))))
            == 1
        )
        assert (
            len(
                list(
                    db.scalars(
                        select(CompetitionResource).where(
                            CompetitionResource.resource_id == fork,
                            CompetitionResource.kind == "notebooks",
                        )
                    )
                )
            )
            == 1
        )
        assert "private next draft" in db.get(NotebookWorkingCopy, fork).document


def test_uncommitted_fork_not_exposed_to_other_users(member, commit_db):
    fork = member.post("/api/code/1/fork?competition_id=1").json()["id"]
    member.post("/api/auth/logout")
    assert member.get(f"/api/code/{fork}").status_code == 404
    assert member.get(f"/api/notebooks/{fork}/download").status_code == 404
    assert member.get(f"/api/code/{fork}/comments").status_code == 404
    assert all(row["id"] != fork for row in member.get("/api/notebooks").json())
    member.post(
        "/api/auth/register",
        json={"username": "other_commit_user", "password": "other-password-123"},
    )
    assert member.post(f"/api/code/{fork}/fork").status_code == 404
    assert (
        member.post(f"/api/code/{fork}/commits", json={"competition_id": 1}).status_code
        == 404
    )
    assert member.get(f"/api/code/{fork}/commits/latest").status_code == 404
    from app.notebook_runtime import get_hub
    from test_notebook_runtime import FakeHub

    app.dependency_overrides[get_hub] = lambda: FakeHub()
    assert member.get(f"/api/editor/notebooks/{fork}/document").status_code == 404


def test_legacy_migration_only_removes_competition_fork_links(member, commit_db):
    from app.models import Notebook, NotebookPublication
    from app.notebook_runtime import notebook_document

    with commit_db() as db:
        source = db.get(Notebook, 1)
        fork_ids = []
        for linked in (False, True):
            fork = Notebook(owner_id=2, title="Legacy fork", code=source.code)
            db.add(fork)
            db.flush()
            fork_ids.append(fork.id)
            db.add(
                NotebookPublication(
                    notebook_id=fork.id,
                    forked_from=source.id,
                    document=json.dumps(notebook_document(source)),
                )
            )
            if linked:
                db.add(
                    CompetitionResource(
                        competition_id=1, kind="notebooks", resource_id=fork.id
                    )
                )
        db.commit()
        notebook_commits.migrate_forks(db)
        assert db.get(NotebookWorkingCopy, fork_ids[0]) is None
        assert db.get(NotebookWorkingCopy, fork_ids[1]).private == 1
        assert db.get(NotebookWorkingCopy, fork_ids[1]).competition_id == 1
        assert (
            db.scalar(
                select(CompetitionResource.id).where(
                    CompetitionResource.resource_id == fork_ids[1],
                    CompetitionResource.kind == "notebooks",
                )
            )
            is None
        )
        notebook_commits.migrate_forks(db)
        assert db.get(NotebookPublication, fork_ids[0]) is not None


def test_commit_rejects_closed_competitions_and_unsafe_filenames(member, commit_db):
    from app.models import Competition

    fork = member.post("/api/code/1/fork?competition_id=1").json()["id"]
    member.post("/api/competitions/1/join")
    path = f"/api/code/{fork}/commits"
    assert (
        member.post(
            path, json={"competition_id": 1, "output_filename": "../submission.csv"}
        ).status_code
        == 422
    )
    from app.models import Entry

    with commit_db() as db:
        other = Competition(
            title="Other competition",
            description="Separate test set",
            deadline="2027-12-31T23:59:59+00:00",
            solution="{}",
        )
        db.add(other)
        db.flush()
        other_id = other.id
        db.add(Entry(user_id=2, competition_id=other_id))
        db.commit()
    assert member.post(path, json={"competition_id": other_id}).status_code == 409
    with commit_db() as db:
        db.get(Competition, 1).deadline = "2020-01-01T00:00:00+00:00"
        db.commit()
    assert member.post(path, json={"competition_id": 1}).status_code == 409


def test_runner_waits_for_shell_and_iopub_before_executing(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    class Socket:
        def __init__(self):
            self.messages = []
            self.info_requests = 0
            self.executions = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def send(self, raw):
            request = json.loads(raw)
            id = request["header"]["msg_id"]

            def message(kind, content):
                return json.dumps(
                    {
                        "parent_header": {"msg_id": id},
                        "header": {"msg_type": kind},
                        "content": content,
                    }
                )

            if request["content"].get("code") == "":
                self.info_requests += 1
                self.messages.append(message("execute_reply", {}))
                if self.info_requests > 1:
                    self.messages.append(message("status", {"execution_state": "idle"}))
            else:
                assert self.info_requests == 2
                self.executions += 1
                self.messages += [
                    message("execute_input", {"execution_count": 1}),
                    message("stream", {"name": "stdout", "text": "ready\n"}),
                    message("status", {"execution_state": "idle"}),
                ]

        async def recv(self):
            if not self.messages:
                raise asyncio.TimeoutError()
            return self.messages.pop(0)

    socket = Socket()
    monkeypatch.setattr(notebook_commits, "connect", lambda *args, **kwargs: socket)
    outputs, count = asyncio.run(
        notebook_commits.run_cell(
            SimpleNamespace(proxy_url="http://hub", token="test"),
            SimpleNamespace(id=2),
            "kernel",
            'print("ready")',
        )
    )
    assert outputs[0]["text"] == "ready\n" and count == 1
    assert socket.executions == 1


def test_cancelled_commit_never_publishes(member, commit_db):
    fork = member.post("/api/code/1/fork?competition_id=1").json()["id"]
    path = f"/api/code/{fork}"
    member.post("/api/competitions/1/join")
    job = member.post(path + "/commits", json={"competition_id": 1}).json()
    with commit_db() as db:
        row = db.get(NotebookCommit, job["id"])
        row.status = "running"
        db.commit()
    cancelled = member.post(f"{path}/commits/{job['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    document = member.get(path).json()["document"]
    notebook_commits.complete_commit(
        job["id"], document, b"id,prediction\n7,240\n8,100\n9,300\n"
    )
    assert member.get(path).json()["private"] is True
    assert (
        member.get("/api/code?competition_id=1&filter=your-work").json()["items"] == []
    )
    member.post("/api/auth/logout")
    member.post(
        "/api/auth/register",
        json={"username": "other", "password": "good-password-123"},
    )
    assert member.post(f"{path}/commits/{job['id']}/cancel").status_code == 404
