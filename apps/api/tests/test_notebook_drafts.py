from copy import deepcopy

import pytest

from app.main import app
from app.db import get_db
from app.models import NotebookDraft
from app.notebook_runtime import get_hub
from test_notebook_runtime import FakeHub


@pytest.fixture
def hub():
    hub = FakeHub()
    hub.state = "ready"
    app.dependency_overrides[get_hub] = lambda: hub
    yield hub
    app.dependency_overrides.pop(get_hub, None)


def new_draft(member):
    response = member.post("/api/notebook-drafts")
    assert response.status_code == 201
    id = response.json()["id"]
    assert member.post(f"/api/notebook-drafts/{id}/open").status_code == 200
    return id, f"/user/arena-2/api/contents/arena-draft-{id}.ipynb"


def test_unsaved_draft_is_private_and_deleted(member, hub):
    before = member.get("/api/notebooks").json()
    id, path = new_draft(member)
    assert path in hub.files
    assert member.get("/api/notebooks").json() == before
    assert member.delete(f"/api/notebook-drafts/{id}").status_code == 204
    assert path not in hub.files
    assert member.get("/api/notebooks").json() == before
    assert member.post(f"/api/notebook-drafts/{id}/heartbeat").status_code == 404


def test_save_preserves_outputs_and_repeated_save_updates_same_notebook(member, hub):
    id, path = new_draft(member)
    doc = hub.files[path]["content"]
    doc["cells"][0]["source"] = ["print(42)"]
    doc["cells"][0]["outputs"] = [
        {"output_type": "stream", "name": "stdout", "text": "42\n"}
    ]
    doc["cells"].append(
        {"cell_type": "markdown", "source": ["# Notes"], "metadata": {}}
    )
    response = member.post(
        f"/api/notebook-drafts/{id}/save", json={"title": "Saved experiment"}
    )
    assert response.status_code == 200, response.text
    notebook_id = response.json()["id"]
    permanent = f"/user/arena-2/api/contents/arena-notebook-{notebook_id}.ipynb"
    assert hub.files[permanent]["content"] == doc
    assert (
        member.post(
            f"/api/notebook-drafts/{id}/save", json={"title": "Updated experiment"}
        ).json()["id"]
        == notebook_id
    )
    # Simulate separate remote files, then edit the draft without another explicit save.
    snapshot = deepcopy(hub.files[permanent])
    hub.files[path] = deepcopy(hub.files[path])
    hub.files[path]["content"]["cells"][0]["source"] = ["print('unsaved')"]
    assert member.delete(f"/api/notebook-drafts/{id}").status_code == 204
    assert hub.files[permanent] == snapshot
    assert path not in hub.files
    assert any(n["id"] == notebook_id for n in member.get("/api/notebooks").json())


def test_other_users_cannot_open_save_or_discard_drafts(member, hub):
    id, path = new_draft(member)
    member.post("/api/auth/logout")
    member.post(
        "/api/auth/register",
        json={"username": "other_drafter", "password": "another-password"},
    )
    assert member.post(f"/api/notebook-drafts/{id}/open").status_code == 404
    assert (
        member.post(
            f"/api/notebook-drafts/{id}/save", json={"title": "Stolen notebook"}
        ).status_code
        == 404
    )
    assert member.delete(f"/api/notebook-drafts/{id}").status_code == 204
    assert path in hub.files


def test_expired_draft_cannot_be_revived(member, hub):
    id, path = new_draft(member)
    with next(app.dependency_overrides[get_db]()) as db:
        db.get(NotebookDraft, id).expires_at = 0
        db.commit()
    assert member.post(f"/api/notebook-drafts/{id}/heartbeat").status_code == 410
    assert (
        member.post(
            f"/api/notebook-drafts/{id}/save", json={"title": "Too late"}
        ).status_code
        == 410
    )
    assert member.delete(f"/api/notebook-drafts/{id}").status_code == 204
    assert path not in hub.files


def test_anonymous_draft_creation_is_rejected(client):
    assert client.post("/api/notebook-drafts").status_code == 401
