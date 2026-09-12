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
    published = member.get(f"/api/code/{notebook_id}").json()["document"]
    assert published["cells"][0]["outputs"] == doc["cells"][0]["outputs"]
    assert published["cells"][1]["cell_type"] == "markdown"
    assert published["cells"][1]["source"] == ["# Notes"]
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


def test_competition_draft_requires_join_and_save_stays_private(member, hub):
    assert member.post("/api/notebook-drafts?competition_id=1").status_code == 403
    assert member.post("/api/notebook-drafts?competition_id=999999").status_code == 404
    id, path = new_draft(member)
    assert (
        member.post(
            f"/api/notebook-drafts/{id}/save",
            json={"title": "Competition code", "competition_id": 1},
        ).status_code
        == 403
    )
    member.post("/api/competitions/1/join")
    created = member.post("/api/notebook-drafts?competition_id=1")
    assert created.status_code == 201
    draft_id = created.json()["id"]
    assert member.post(f"/api/notebook-drafts/{draft_id}/open").status_code == 200
    before = member.get("/api/code?competition_id=1&filter=your-work").json()["items"]
    assert before == []
    response = member.post(
        f"/api/notebook-drafts/{draft_id}/save",
        json={"title": "Competition code", "competition_id": 1},
    )
    assert response.status_code == 200
    notebook_id = response.json()["id"]
    again = member.post(
        f"/api/notebook-drafts/{draft_id}/save",
        json={"title": "Updated competition code", "competition_id": 1},
    )
    assert again.json()["id"] == notebook_id
    codes = member.get("/api/code?competition_id=1&filter=your-work").json()["items"]
    assert codes == []
    assert member.get(f"/api/code/{notebook_id}").json()["private"] is True
    assert member.delete(f"/api/notebook-drafts/{draft_id}").status_code == 204
    assert (
        member.get("/api/code?competition_id=1&filter=your-work").json()["items"] == []
    )
    assert any(
        row["id"] == notebook_id
        for row in member.get("/api/code?filter=your-work").json()["items"]
    )
    unsaved = member.post("/api/notebook-drafts?competition_id=1").json()["id"]
    member.delete(f"/api/notebook-drafts/{unsaved}")
    assert (
        member.get("/api/code?competition_id=1&filter=your-work").json()["items"] == []
    )


def test_competition_draft_cannot_bypass_evaluation_by_omitting_context(member, hub):
    from app.models import Notebook, NotebookWorkingCopy, CompetitionResource
    from app.code_pages import store_publication
    from app.notebook_editor import Document

    member.post("/api/competitions/1/join")
    draft_id, path = new_draft(member)
    saved = member.post(
        f"/api/notebook-drafts/{draft_id}/save",
        json={"title": "Evaluated notebook", "competition_id": 1},
    ).json()
    notebook_id = saved["id"]
    # Represent the published state of a successfully evaluated commit.
    with next(app.dependency_overrides[get_db]()) as db:
        store_publication(
            db,
            db.get(Notebook, notebook_id),
            Document.model_validate(hub.files[path]["content"]),
        )
        db.get(NotebookWorkingCopy, notebook_id).private = 0
        db.add(
            CompetitionResource(
                competition_id=1, kind="notebooks", resource_id=notebook_id
            )
        )
        db.commit()
    published = member.get(f"/api/code/{notebook_id}").json()["document"]
    hub.files[path]["content"]["cells"][0]["source"] = ['print("unevaluated edit")']
    response = member.post(
        f"/api/notebook-drafts/{draft_id}/save", json={"title": "Bypass commit"}
    )
    assert response.status_code == 409
    assert member.get(f"/api/code/{notebook_id}").json()["document"] == published
    # Ordinary competition saves still update only the private working document.
    assert (
        member.post(
            f"/api/notebook-drafts/{draft_id}/save",
            json={"title": "Saved edit", "competition_id": 1},
        ).status_code
        == 200
    )
    assert member.get(f"/api/code/{notebook_id}").json()["document"] == published

    member.post("/api/auth/logout")
    for url in ["/api/notebooks", "/api/competitions/1/resources/notebooks"]:
        row = next(item for item in member.get(url).json() if item["id"] == notebook_id)
        assert "unevaluated edit" not in row["code"]


def test_competition_creation_attaches_files_and_retains_link_without_client_context(
    member, hub
):
    member.post("/api/competitions/1/join")
    draft = member.post("/api/notebook-drafts?competition_id=1").json()["id"]
    response = member.get(f"/api/editor/drafts/{draft}/document")
    assert response.status_code == 200, response.text
    document = response.json()
    assert document["metadata"]["arena_competition_id"] == 1
    source = document["metadata"]["arena_input_sources"][0]
    assert source["kind"] == "competition" and source["id"] == 1
    assert source["files"]
    for file in source["files"]:
        assert any(
            path.endswith(f'workspaces/arena-draft-{draft}/{file["path"]}')
            for path in hub.files
        )
    saved = member.post(
        f"/api/notebook-drafts/{draft}/save",
        json={"title": "Linked competition notebook"},
    )
    assert saved.status_code == 200, saved.text
    id = saved.json()["id"]
    detail = member.get(f"/api/code/{id}").json()
    assert detail["working_competition_id"] == 1
    assert detail["document"]["metadata"]["arena_input_sources"] == [source]
    assert (
        member.post(
            f"/api/notebook-drafts/{draft}/save",
            json={"title": "Wrong link", "competition_id": 2},
        ).status_code
        == 409
    )
    # Saving remains private and does not publish to the competition code catalog.
    assert not any(
        row["id"] == id
        for row in member.get("/api/code?competition_id=1").json()["items"]
    )


@pytest.mark.parametrize("kind", ["dataset", "model"])
def test_resource_draft_pins_input_and_preserves_it_on_save(member, hub, kind):
    from app.models import NotebookDraftInput

    if kind == "dataset":
        response = member.post(
            "/api/datasets",
            data={"title": "Source data", "description": "Original"},
            files={"file": ("train.csv", b"x\n1\n")},
        )
    else:
        response = member.post(
            "/api/models",
            json={
                "title": "Source model",
                "description": "Weights",
                "framework": "PyTorch",
                "license": "MIT",
            },
        )
    assert response.status_code == 201, response.text
    source_id = response.json()["id"]
    asset_url = f"/api/assets/{kind}s/{source_id}"
    old = member.post(
        asset_url,
        data={"path": "weights.bin"},
        files={"file": ("weights.bin", b"original")},
    )
    assert old.status_code == 201
    created = member.post(
        f"/api/notebook-drafts?source_kind={kind}&source_id={source_id}"
    )
    assert created.status_code == 201, created.text
    draft_id = created.json()["id"]
    member.post(
        asset_url,
        data={"path": "weights.bin"},
        files={"file": ("weights.bin", b"newer")},
    )
    opened = member.post(f"/api/notebook-drafts/{draft_id}/open")
    assert opened.status_code == 200, opened.text
    document = hub.files[f"/user/arena-2/api/contents/arena-draft-{draft_id}.ipynb"][
        "content"
    ]
    source = document["metadata"]["arena_input_sources"][0]
    assert source["kind"] == kind
    assert source["id"] == source_id
    assert source["path"].startswith("input/")
    assert "resource-inputs" in [cell["id"] for cell in document["cells"]]
    # File content was copied from the pinned version, not the newer upload.
    import base64

    copied = [
        base64.b64decode(file["content"])
        for file in hub.files.values()
        if file.get("type") == "file"
    ]
    assert b"original" in copied
    assert b"newer" not in copied
    saved = member.post(
        f"/api/notebook-drafts/{draft_id}/save", json={"title": "Consumer"}
    )
    assert saved.status_code == 200, saved.text
    persisted = member.get(f"/api/code/{saved.json()['id']}").json()
    assert persisted["document"]["metadata"]["arena_input_sources"] == [source]
    assert member.delete(f"/api/notebook-drafts/{draft_id}").status_code == 204
    with next(app.dependency_overrides[get_db]()) as db:
        assert db.get(NotebookDraftInput, draft_id) is None


def test_resource_draft_checks_access_and_invalid_sources(member, hub):
    dataset = member.post(
        "/api/datasets",
        data={"title": "Private source", "description": "Private"},
        files={"file": ("x.csv", b"x\n1\n")},
    ).json()
    assert member.post("/api/notebook-drafts?source_kind=dataset").status_code == 422
    assert (
        member.post("/api/notebook-drafts?source_kind=unknown&source_id=1").status_code
        == 422
    )
    member.post("/api/auth/logout")
    member.post(
        "/api/auth/register",
        json={"username": "source_outsider", "password": "good-password-123"},
    )
    assert (
        member.post(
            f"/api/notebook-drafts?source_kind=dataset&source_id={dataset['id']}"
        ).status_code
        == 404
    )
