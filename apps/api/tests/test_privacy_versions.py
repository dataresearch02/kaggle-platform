from app.main import app
from app.db import get_db
from app.models import Notebook, NotebookVersion
from app.notebook_versions import save_version
from test_code_pages import document


def test_private_notebook_sharing_revocation_and_history(member):
    row = member.post(
        "/api/notebooks", json={"title": "Private experiment", "code": "print(1)"}
    ).json()
    base = f"/api/code/{row['id']}"
    initial = member.get(base + "/versions").json()
    assert len(initial) == 1
    with next(app.dependency_overrides[get_db]()) as db:
        notebook = db.get(Notebook, row["id"])
        save_version(db, notebook, document())
        db.commit()
        save_version(db, notebook, document())
        db.commit()
    assert len(member.get(base + "/versions").json()) == 2
    assert member.get(base + f"/versions/{initial[0]['id']}").json()["cells"][0][
        "source"
    ] == ["print(1)"]
    member.post("/api/auth/logout")
    assert member.get(base).status_code == 404
    member.post(
        "/api/auth/register",
        json={"username": "recipient", "password": "good-password-123"},
    )
    recipient = member.get("/api/auth/me").json()["id"]
    assert member.get(base).status_code == 404
    member.post("/api/auth/logout")
    member.post(
        "/api/auth/login", json={"username": "learner", "password": "good-password-123"}
    )
    assert (
        member.post(base + "/shares", json={"username": "recipient"}).status_code == 201
    )
    member.post("/api/auth/logout")
    member.post(
        "/api/auth/login",
        json={"username": "recipient", "password": "good-password-123"},
    )
    assert member.get(base).status_code == 200
    assert member.get(base + "/versions").status_code == 404
    assert member.put(base + "/publication", json=document()).status_code == 403
    member.post("/api/auth/logout")
    member.post(
        "/api/auth/login", json={"username": "learner", "password": "good-password-123"}
    )
    member.delete(base + f"/shares/{recipient}")
    member.post("/api/auth/logout")
    member.post(
        "/api/auth/login",
        json={"username": "recipient", "password": "good-password-123"},
    )
    assert member.get(base).status_code == 404


def test_dataset_private_endpoints_and_publication(member):
    row = member.post(
        "/api/datasets",
        data={"title": "Private input", "description": "Private records"},
        files={"file": ("x.csv", b"x\n1\n")},
    ).json()
    base = f"/api/datasets/{row['id']}"
    assert member.get(base + "/access").json()["visibility"] == "private"
    member.post("/api/auth/logout")
    for suffix in ["", "/download", "/metadata"]:
        assert member.get(base + suffix).status_code == 404
    assert row["id"] not in [item["id"] for item in member.get("/api/datasets").json()]
    member.post(
        "/api/auth/login", json={"username": "learner", "password": "good-password-123"}
    )
    assert (
        member.put(base + "/access", json={"visibility": "public"}).status_code == 200
    )
    member.post("/api/auth/logout")
    for suffix in ["", "/download", "/metadata"]:
        assert member.get(base + suffix).status_code == 200


def test_explicit_publication_updates_new_notebook_working_copy(member):
    from app.models import NotebookWorkingCopy
    import json

    row = member.post(
        "/api/notebooks", json={"title": "Publish new content", "code": "print(1)"}
    ).json()
    snapshot = document()
    snapshot["cells"][0]["source"] = "# Published heading"
    assert (
        member.put(f"/api/code/{row['id']}/publication", json=snapshot).status_code
        == 200
    )
    with next(app.dependency_overrides[get_db]()) as db:
        working = db.get(NotebookWorkingCopy, row["id"])
        assert not working.private
        assert (
            json.loads(working.document)["cells"][0]["source"] == "# Published heading"
        )
