import base64
import httpx
from app.main import app
from app.notebook_runtime import get_hub
from app.input_sources import safe_path
import pytest
from fastapi import HTTPException


class Hub:
    def __init__(self):
        self.files = {}

    async def request(self, method, path, **kwargs):
        if method == "GET":
            return (
                httpx.Response(200, json=[])
                if path.endswith("/api/sessions")
                else httpx.Response(404)
            )
        if method == "DELETE":
            self.files.pop(path, None)
            return httpx.Response(204)
        data = kwargs.get("json", {})
        if data.get("type") == "file":
            self.files[path] = base64.b64decode(data["content"])
        return httpx.Response(201)

    def expect(self, response, codes=(200,)):
        assert response.status_code in codes
        return response


def test_competition_folder_join_and_remove(member):
    hub = Hub()
    app.dependency_overrides[get_hub] = lambda: hub
    notebook = member.post(
        "/api/notebooks", json={"title": "Grouped inputs", "code": "print(1)"}
    ).json()["id"]
    base = f"/api/editor/notebooks/{notebook}"
    assert member.get("/api/input-sources?kind=competition").json()["items"]
    assert member.post(base + "/input-sources/competition/1").status_code == 403
    member.post("/api/competitions/1/join")
    response = member.post(base + "/input-sources/competition/1")
    assert response.status_code == 200, response.text
    source = response.json()
    assert source["path"].startswith("input/")
    assert source["files"]
    assert len(hub.files) == len(source["files"])
    assert all("/workspaces/arena-notebook-" in path for path in hub.files)
    assert member.post(base + "/remove-input-source", json=source).status_code == 200
    assert hub.files == {}
    assert member.get("/api/competitions/1/files").json()
    assert member.post(base + "/input-sources/competition/1").status_code == 200
    source["path"] = "../private"
    assert member.post(base + "/remove-input-source", json=source).status_code == 422


@pytest.mark.parametrize(
    "path", ["../secret", "/absolute", "foo/../../secret", "foo\\bar"]
)
def test_reject_unsafe_input_paths(path):
    with pytest.raises(HTTPException):
        safe_path(path)


def test_notebook_source_pins_latest_files_and_enforces_visibility(member):
    from app.db import get_db, DATA_DIR
    from app.models import Notebook, NotebookOutput
    from app.input_sources import resolve_attachment
    from app.models import User

    hub = Hub()
    app.dependency_overrides[get_hub] = lambda: hub
    source = member.post(
        "/api/notebooks", json={"title": "Model outputs", "code": "print(1)"}
    ).json()["id"]
    target = member.post(
        "/api/notebooks", json={"title": "Model consumer", "code": "print(1)"}
    ).json()["id"]
    generator = app.dependency_overrides[get_db]()
    db = next(generator)
    try:
        owner = db.get(Notebook, source).owner_id
        root = DATA_DIR / "notebook-outputs"
        root.mkdir(exist_ok=True)
        for key, name in [
            ("old", "predictions.csv"),
            ("latest", "predictions.csv"),
            ("weights", "models/weights.bin"),
        ]:
            (root / key).write_bytes(key.encode())
            db.add(
                NotebookOutput(
                    notebook_id=source,
                    owner_id=owner,
                    filename=name,
                    storage_key=key,
                    size=len(key),
                    sha256=key,
                    shared=1,
                )
            )
        db.commit()
        result = member.post(
            f"/api/editor/notebooks/{target}/input-sources/notebook/{source}"
        )
        assert result.status_code == 200, result.text
        attachment = result.json()
        assert len(attachment["files"]) == 2
        assert set(hub.files.values()) == {b"latest", b"weights"}
        (root / "newer").write_bytes(b"newer")
        db.add(
            NotebookOutput(
                notebook_id=source,
                owner_id=owner,
                filename="predictions.csv",
                storage_key="newer",
                size=5,
                sha256="newer",
                shared=1,
            )
        )
        db.commit()
        _, pinned = resolve_attachment(db, db.get(User, owner), attachment)
        assert {file.read(db) for file in pinned} == {b"latest", b"weights"}
        member.post("/api/auth/logout")
        member.post(
            "/api/auth/register",
            json={"username": "stranger", "password": "good-password-123"},
        )
        own = member.post(
            "/api/notebooks", json={"title": "Own notebook", "code": "print(1)"}
        ).json()["id"]
        assert (
            member.post(
                f"/api/editor/notebooks/{own}/input-sources/notebook/{source}"
            ).status_code
            == 404
        )
    finally:
        generator.close()


def test_dataset_uses_named_folder(member):
    hub = Hub()
    app.dependency_overrides[get_hub] = lambda: hub
    dataset = member.post(
        "/api/datasets",
        data={
            "title": "Training measurements",
            "description": "Reusable training measurements",
        },
        files={"file": ("measurements.csv", b"value\n42\n", "text/csv")},
    )
    assert dataset.status_code == 201, dataset.text
    notebook = member.post(
        "/api/notebooks", json={"title": "Dataset consumer", "code": "print(1)"}
    ).json()["id"]
    result = member.post(
        f'/api/editor/notebooks/{notebook}/input-sources/dataset/{dataset.json()["id"]}'
    )
    assert result.status_code == 200, result.text
    attachment = result.json()
    assert attachment["path"].startswith("input/training-measurements-dataset-")
    assert attachment["files"][0]["filename"] == "measurements.csv"
    assert list(hub.files.values()) == [b"value\n42\n"]


def test_input_preview_requires_membership_and_returns_table(member):
    files = member.get("/api/competitions/1/files").json()
    file_id = files[0]["id"]
    path = f"/api/input-sources/competition/1/files/{file_id}/preview"
    assert member.get(path).status_code == 403
    member.post("/api/competitions/1/join")
    response = member.get(path)
    assert response.status_code == 200
    assert response.json()["format"] == "table"
    assert response.json()["columns"]
    assert response.json()["rows"]
    assert len(response.json()["rows"]) <= 50
    assert (
        member.get("/api/input-sources/competition/1/files/999999/preview").status_code
        == 404
    )
