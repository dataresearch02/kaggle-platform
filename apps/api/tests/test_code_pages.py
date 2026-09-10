import json
from sqlalchemy import select
from app.main import app
from app.db import get_db
from app.models import (
    Notebook,
    NotebookBookmark,
    NotebookShare,
    NotebookPublication,
    CompetitionResource,
)
from test_notebook_runtime import hub


def create(client, title="Published experiment"):
    response = client.post(
        "/api/notebooks",
        json={"title": title, "description": "Source description", "code": "print(42)"},
    )
    assert response.status_code == 201
    return response.json()


def register(client, username):
    client.post("/api/auth/logout")
    assert (
        client.post(
            "/api/auth/register",
            json={"username": username, "password": "code-library-password"},
        ).status_code
        == 201
    )


def document():
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {},
        "cells": [
            {
                "id": "notes",
                "cell_type": "markdown",
                "source": "# Experiment notes",
                "metadata": {},
            },
            {
                "id": "code",
                "cell_type": "code",
                "source": "print(42)",
                "metadata": {},
                "execution_count": 1,
                "outputs": [
                    {"output_type": "stream", "name": "stdout", "text": "42\n"}
                ],
            },
        ],
    }


def test_cursor_pages_are_bounded_scoped_and_exclude_source(member):
    with next(app.dependency_overrides[get_db]()) as db:
        owner_id = member.get("/api/auth/me").json()["id"]
        notebooks = [
            Notebook(
                owner_id=owner_id,
                title=f"Pagination example {n}",
                description="Details",
                code="DO_NOT_INCLUDE_SOURCE",
            )
            for n in range(45)
        ]
        db.add_all(notebooks)
        db.flush()
        for row in notebooks:
            db.add(
                CompetitionResource(
                    competition_id=1, kind="notebooks", resource_id=row.id
                )
            )
        db.commit()
    params = {"competition_id": 1, "q": "Pagination example", "limit": 20}
    first = member.get("/api/code", params=params).json()
    assert len(first["items"]) == 20 and first["next_cursor"]
    assert "DO_NOT_INCLUDE_SOURCE" not in json.dumps(first)
    assert "document" not in first["items"][0] and "code" not in first["items"][0]
    added = create(member, "Pagination example inserted later")
    member.post(f"/api/competitions/1/resources/notebooks/{added['id']}")
    all_ids = [row["id"] for row in first["items"]]
    cursor = first["next_cursor"]
    while cursor:
        page = member.get("/api/code", params={**params, "cursor": cursor}).json()
        all_ids.extend(row["id"] for row in page["items"])
        cursor = page["next_cursor"]
    assert len(all_ids) == len(set(all_ids)) == 45
    assert added["id"] not in all_ids
    assert member.get("/api/code?limit=1000").status_code == 422
    assert member.get("/api/code?competition_id=999999").status_code == 404


def test_personal_bookmarks_sharing_and_revocation(member):
    row = create(member)
    id = row["id"]
    member.post(f"/api/competitions/1/resources/notebooks/{id}")
    register(member, "recipient")
    recipient_id = member.get("/api/auth/me").json()["id"]
    assert member.get("/api/code?filter=shared").json()["items"] == []
    member.put(f"/api/code/{id}/bookmark")
    member.put(f"/api/code/{id}/bookmark")
    assert [
        row["id"] for row in member.get("/api/code?filter=bookmarks").json()["items"]
    ] == [id]
    assert (
        member.post(f"/api/code/{id}/shares", json={"username": "learner"}).status_code
        == 403
    )
    member.post("/api/auth/logout")
    assert member.get("/api/code?filter=bookmarks").status_code == 401
    member.post(
        "/api/auth/login", json={"username": "learner", "password": "good-password-123"}
    )
    assert member.get("/api/code?filter=bookmarks").json()["items"] == []
    assert (
        member.post(
            f"/api/code/{id}/shares", json={"username": "recipient"}
        ).status_code
        == 201
    )
    assert (
        member.post(
            f"/api/code/{id}/shares", json={"username": "recipient"}
        ).status_code
        == 201
    )
    assert member.get(f"/api/code/{id}/shares").json() == [
        {"id": recipient_id, "username": "recipient"}
    ]
    member.post("/api/auth/logout")
    member.post(
        "/api/auth/login",
        json={"username": "recipient", "password": "code-library-password"},
    )
    assert [
        row["id"] for row in member.get("/api/code?filter=shared").json()["items"]
    ] == [id]
    assert (
        member.get("/api/code?filter=your-work&competition_id=1").json()["items"] == []
    )
    member.delete(f"/api/code/{id}/bookmark")
    assert member.get("/api/code?filter=bookmarks").json()["items"] == []
    member.post("/api/auth/logout")
    member.post(
        "/api/auth/login", json={"username": "learner", "password": "good-password-123"}
    )
    assert member.delete(f"/api/code/{id}/shares/{recipient_id}").status_code == 200


def test_view_and_fork_use_published_document_not_private_runtime(member, hub):
    row = create(member)
    id = row["id"]
    doc = document()
    dataset = member.post(
        "/api/datasets",
        data={"title": "Experiment input", "description": "Public example"},
        files={"file": ("input.csv", b"x\n1\n")},
    ).json()
    doc["metadata"] = {
        "arena_inputs": [
            {"id": dataset["id"], "title": "fake title", "path": "../secret"}
        ],
        "runtime_token": "DO_NOT_PUBLISH_RUNTIME_METADATA",
    }
    assert member.put(f"/api/code/{id}/publication", json=doc).status_code == 200
    hub.state = "ready"
    member_id = member.get("/api/auth/me").json()["id"]
    hub.files[f"/user/arena-{member_id}/api/contents/arena-notebook-{id}.ipynb"] = {
        "type": "notebook",
        "content": {"cells": [{"source": "PRIVATE_OUTPUT"}]},
    }
    calls_before = len(hub.calls)
    view = member.get(f"/api/code/{id}").json()
    assert len(hub.calls) == calls_before
    assert view["document"]["cells"][1]["outputs"][0]["text"] == "42\n"
    assert view["inputs"][0]["title"] == "Experiment input"
    assert "PRIVATE_OUTPUT" not in json.dumps(
        view
    ) and "DO_NOT_PUBLISH" not in json.dumps(view)
    member.post(f"/api/competitions/1/resources/notebooks/{id}")
    register(member, "forker")
    assert member.put(f"/api/code/{id}/publication", json=document()).status_code == 403
    fork = member.post(f"/api/code/{id}/fork").json()
    assert fork["id"] != id
    fork_view = member.get(f"/api/code/{fork['id']}").json()
    assert fork_view["document"] == view["document"] and fork_view["forked_from"] == id
    assert (
        member.get("/api/code?filter=your-work&competition_id=1").json()["items"] == []
    )
    assert fork_view["private"] is True
    loaded = member.get(f"/api/editor/notebooks/{fork['id']}/document")
    assert loaded.status_code == 200
    assert loaded.json()["cells"][0]["cell_type"] == "markdown"
    new_owner = member.get("/api/auth/me").json()["id"]
    assert (
        f"/user/arena-{new_owner}/api/contents/arena-input-{dataset['id']}.csv"
        in hub.files
    )
    changed = document()
    changed["cells"][1]["source"] = "print(100)"
    member.put(f"/api/code/{fork['id']}/publication", json=changed)
    assert member.get(f"/api/code/{id}").json()["document"] == view["document"]


def test_source_fallback_and_cleanup(member):
    row = create(member)
    id = row["id"]
    assert member.get(f"/api/code/{id}").json()["published_at"] is None
    assert member.get(f"/api/code/{id}").json()["document"]["cells"][0]["outputs"] == []
    member.put(f"/api/code/{id}/publication", json=document())
    member.put(f"/api/code/{id}/bookmark")
    fork = member.post(f"/api/code/{id}/fork").json()
    assert member.delete(f"/api/work/notebooks/{id}").status_code == 204
    assert member.get(f"/api/code/{id}").status_code == 404
    assert member.get(f"/api/code/{fork['id']}").json()["forked_from"] is None
    with next(app.dependency_overrides[get_db]()) as db:
        assert db.get(NotebookPublication, id) is None
        assert (
            db.scalar(
                select(NotebookBookmark).where(NotebookBookmark.notebook_id == id)
            )
            is None
        )


def test_invalid_publication_metadata_is_rejected(member):
    id = create(member)["id"]
    doc = document()
    doc["metadata"]["arena_inputs"] = "bad"
    assert member.put(f"/api/code/{id}/publication", json=doc).status_code == 422
    doc = document()
    doc["cells"][1]["execution_count"] = {}
    assert member.put(f"/api/code/{id}/publication", json=doc).status_code == 422


def test_work_status_is_small_and_user_scoped(member):
    assert member.get("/api/work/status").json() == {"has_work": False}
    row = create(member)
    assert member.get("/api/work/status").json() == {"has_work": True}
    member.delete(f"/api/work/notebooks/{row['id']}")
    assert member.get("/api/work/status").json() == {"has_work": False}
    member.post("/api/auth/logout")
    assert member.get("/api/work/status").status_code == 401


def test_notebook_comments_persist_and_enforce_ownership(member):
    notebook = member.post(
        "/api/notebooks", json={"title": "Commented code", "code": "print(1)"}
    ).json()
    path = f"/api/code/{notebook['id']}/comments"
    assert member.post(path, json={"body": "   "}).status_code == 422
    created = member.post(path, json={"body": "Useful notebook"})
    assert created.status_code == 201
    comment = created.json()
    assert member.get(path).json()["items"][0]["body"] == "Useful notebook"
    member.post("/api/auth/logout")
    assert member.post(path, json={"body": "Anonymous"}).status_code == 401
    assert member.get(path).status_code == 200
    member.post(
        "/api/auth/register",
        json={"username": "other_commenter", "password": "other-password-123"},
    )
    assert member.delete(f"{path}/{comment['id']}").status_code == 403
    own = member.post(path, json={"body": "My comment"}).json()
    assert member.delete(f"{path}/{own['id']}").status_code == 204
    assert len(member.get(path).json()["items"]) == 1
    assert member.get("/api/code/999999/comments").status_code == 404
