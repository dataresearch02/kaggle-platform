from test_challenges import publish


def test_work_lists_only_owned_persistent_content(member):
    assert member.get("/api/work").json() == []
    notebook = member.post(
        "/api/notebooks", json={"title": "My notebook", "code": "print(42)"}
    ).json()
    member.post("/api/notebook-drafts")
    dataset = member.post(
        "/api/datasets",
        data={"title": "My dataset", "description": "Original CSV"},
        files={"file": ("sample.csv", b"x,y\n1,2\n")},
    ).json()
    model = member.post(
        "/api/models",
        json={
            "title": "My model",
            "description": "Model reference",
            "framework": "PyTorch",
            "license": "MIT",
            "url": "https://example.com/model",
        },
    ).json()
    competition = publish(member).json()
    benchmark = publish(member, "benchmarks").json()
    items = member.get("/api/work").json()
    assert {(i["work_kind"], i["id"]) for i in items} == {
        ("notebooks", notebook["id"]),
        ("datasets", dataset["id"]),
        ("models", model["id"]),
        ("competitions", competition["id"]),
        ("benchmarks", benchmark["id"]),
    }
    assert all(
        "solution" not in i and "storage_key" not in i and "test_csv" not in i
        for i in items
    )
    for item in items:
        path = f"/api/work/{item['work_kind']}/{item['id']}"
        response = member.patch(
            path, json={"title": "Renamed work", "description": "Updated description"}
        )
        assert response.status_code == 200
        assert response.json()["title"] == "Renamed work"
    assert (
        member.get(f"/api/datasets/{dataset['id']}/download").content == b"x,y\n1,2\n"
    )
    assert (
        next(
            i for i in member.get("/api/work").json() if i["work_kind"] == "notebooks"
        )["code"]
        == "print(42)"
    )
    member.post("/api/auth/logout")
    assert member.get("/api/work").status_code == 401
    assert (
        member.patch(
            f"/api/work/notebooks/{notebook['id']}",
            json={"title": "Unauthorized", "description": ""},
        ).status_code
        == 401
    )
    member.post(
        "/api/auth/register",
        json={"username": "anothercreator", "password": "another-password"},
    )
    assert member.get("/api/work").json() == []
    for item in items:
        assert (
            member.patch(
                f"/api/work/{item['work_kind']}/{item['id']}",
                json={"title": "Unauthorized", "description": ""},
            ).status_code
            == 404
        )


def test_work_metadata_validation(member):
    notebook = member.post(
        "/api/notebooks", json={"title": "My notebook", "code": "print(42)"}
    ).json()
    path = f"/api/work/notebooks/{notebook['id']}"
    assert (
        member.patch(path, json={"title": "   ", "description": ""}).status_code == 422
    )
    assert (
        member.patch(path, json={"title": "ok", "description": ""}).status_code == 422
    )
    assert (
        member.patch(
            "/api/work/users/1", json={"title": "Invalid", "description": ""}
        ).status_code
        == 404
    )


def test_delete_work_checks_owner_and_removes_related_records(member):
    from app.main import app
    from app.db import get_db
    from app.models import ChallengeDetails, Entry, Submission, WorkFileDeletion
    from sqlalchemy import select

    model = member.post(
        "/api/models",
        json={
            "title": "Delete model",
            "description": "Reference model",
            "framework": "PyTorch",
            "license": "MIT",
            "url": "https://example.com/model",
        },
    ).json()
    challenge = publish(member).json()
    benchmark = publish(member, "benchmarks").json()
    notebook = member.post(
        "/api/notebooks", json={"title": "Delete notebook", "code": "print(1)"}
    ).json()
    paths = [
        f"/api/work/models/{model['id']}",
        f"/api/work/competitions/{challenge['id']}",
        f"/api/work/benchmarks/{benchmark['id']}",
        f"/api/work/notebooks/{notebook['id']}",
    ]
    member.post("/api/auth/logout")
    for path in paths:
        assert member.delete(path).status_code == 401
    member.post(
        "/api/auth/register",
        json={"username": "deleteother", "password": "another-password"},
    )
    for path in paths:
        assert member.delete(path).status_code == 404
    for kind, id in [
        ("competitions", challenge["id"]),
        ("benchmarks", benchmark["id"]),
    ]:
        member.post(f"/api/{kind}/{id}/join")
        member.post(
            f"/api/{kind}/{id}/submissions",
            files={"file": ("predictions.csv", "id,prediction\na,123.45\nb,678.9\n")},
        )
    member.post("/api/auth/logout")
    member.post(
        "/api/auth/login", json={"username": "learner", "password": "good-password-123"}
    )
    assert member.delete(f"/api/work/benchmarks/{challenge['id']}").status_code == 404
    for path in paths:
        assert member.delete(path).status_code == 204
        assert member.delete(path).status_code == 404
    assert member.get("/api/work").json() == []
    with next(app.dependency_overrides[get_db]()) as db:
        for id in [challenge["id"], benchmark["id"]]:
            assert db.get(ChallengeDetails, id) is None
            assert not list(db.scalars(select(Entry).where(Entry.competition_id == id)))
            assert not list(
                db.scalars(select(Submission).where(Submission.competition_id == id))
            )
        assert len(list(db.scalars(select(WorkFileDeletion)))) == 1


def test_delete_dataset_removes_upload_but_preserves_other_files(member):
    from app.db import DATA_DIR

    first = member.post(
        "/api/datasets",
        data={"title": "Delete dataset", "description": "Original CSV"},
        files={"file": ("delete.csv", b"x,y\n1,2\n")},
    ).json()
    second = member.post(
        "/api/datasets",
        data={"title": "Keep dataset", "description": "Keep this CSV"},
        files={"file": ("keep.csv", b"x,y\n3,4\n")},
    ).json()
    before = set((DATA_DIR / "uploads").iterdir())
    assert member.delete(f"/api/work/datasets/{first['id']}").status_code == 204
    assert len(before - set((DATA_DIR / "uploads").iterdir())) == 1
    assert member.get(f"/api/datasets/{first['id']}/download").status_code == 404
    assert member.get(f"/api/datasets/{second['id']}/download").content == b"x,y\n3,4\n"


def test_deleted_notebook_expires_draft_and_retries_offline_cleanup(member):
    import asyncio
    from app.main import app
    from app.db import get_db
    from app.models import NotebookDraft, WorkFileDeletion
    from app.notebook_runtime import get_hub
    from app.work_cleanup import remove_work_file
    from test_notebook_runtime import FakeHub
    from sqlalchemy import select

    hub = FakeHub()
    hub.state = "ready"
    app.dependency_overrides[get_hub] = lambda: hub
    draft = member.post("/api/notebook-drafts").json()["id"]
    assert member.post(f"/api/notebook-drafts/{draft}/open").status_code == 200
    id = member.post(
        f"/api/notebook-drafts/{draft}/save", json={"title": "Delete saved draft"}
    ).json()["id"]
    other_path = f"/user/arena-3/api/contents/arena-notebook-{id}.ipynb"
    hub.files[other_path] = {"content": "another users copy"}
    assert member.delete(f"/api/work/notebooks/{id}").status_code == 204
    assert (
        member.post(
            f"/api/notebook-drafts/{draft}/save", json={"title": "Cannot recreate"}
        ).status_code
        == 410
    )
    with next(app.dependency_overrides[get_db]()) as db:
        assert db.get(NotebookDraft, draft).notebook_id is None
        task = db.scalar(select(WorkFileDeletion))
        hub.state = "stopped"
        assert not asyncio.run(remove_work_file(task, db, hub))
        assert db.get(WorkFileDeletion, task.id)
        hub.state = "ready"
        assert asyncio.run(remove_work_file(task, db, hub))
        assert db.scalar(select(WorkFileDeletion)) is None
    assert f"/user/arena-2/api/contents/arena-notebook-{id}.ipynb" not in hub.files
    assert other_path in hub.files
