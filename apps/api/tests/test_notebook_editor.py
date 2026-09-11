import json

import httpx
import pytest

from app.main import app
from app.notebook_runtime import get_hub
from test_notebook_runtime import FakeHub


class EditorHub(FakeHub):
    proxy_url = "http://private-runtime/jupyter"
    token = "test-token"

    async def request(self, method, path, **kwargs):
        if path.endswith("/api/sessions"):
            if method == "GET":
                return httpx.Response(200, json=[])
            return httpx.Response(201, json={"kernel": {"id": "kernel-1"}})
        return await super().request(method, path, **kwargs)


@pytest.fixture
def hub():
    hub = EditorHub()
    hub.state = "ready"
    app.dependency_overrides[get_hub] = lambda: hub
    yield hub
    app.dependency_overrides.pop(get_hub, None)


def test_document_scopes_to_current_user_and_rejects_arbitrary_paths(member, hub):
    response = member.get("/api/editor/notebooks/1/document")
    assert response.status_code == 200
    document = response.json()
    document["cells"][0]["source"] = 'print("native")'
    document["cells"].append(
        {"id": "markdown", "cell_type": "markdown", "source": "# Notes", "metadata": {}}
    )
    assert (
        member.put("/api/editor/notebooks/1/document", json=document).status_code == 200
    )
    assert (
        hub.files["/user/arena-2/api/contents/arena-notebook-1.ipynb"]["content"][
            "cells"
        ][1]["source"]
        == "# Notes"
    )
    assert member.get("/api/editor/notebooks/etc/document").status_code == 404
    assert member.get("/api/editor/files/1/document").status_code == 422
    member.post("/api/auth/logout")
    member.post(
        "/api/auth/register",
        json={"username": "othereditor", "password": "other-password"},
    )
    assert (
        member.get("/api/editor/notebooks/1/document").json()["cells"][0]["source"]
        != 'print("native")'
    )


def test_native_draft_access_and_invalid_documents(member, hub):
    id = member.post("/api/notebook-drafts").json()["id"]
    document = member.get(f"/api/editor/drafts/{id}/document").json()
    document["cells"][0]["source"] = {"bad": "source"}
    assert (
        member.put(f"/api/editor/drafts/{id}/document", json=document).status_code
        == 422
    )
    member.post("/api/auth/logout")
    member.post(
        "/api/auth/register",
        json={"username": "otherdraft", "password": "other-password"},
    )
    assert member.get(f"/api/editor/drafts/{id}/document").status_code == 404
    assert (
        member.post(
            f"/api/editor/drafts/{id}/execute", json={"code": "print(1)"}
        ).status_code
        == 404
    )


def test_kernel_messages_are_scoped_and_streamed(member, hub, monkeypatch):
    class Socket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def send(self, raw):
            request = json.loads(raw)
            if request["content"].get("code") == "":
                self.id = request["header"]["msg_id"]
                self.messages = [
                    ("execute_reply", {}),
                    ("status", {"execution_state": "idle"}),
                ]
                self.ready = True
                return
            assert self.ready
            assert request["content"]["code"] == "print(42)"
            assert request["content"]["allow_stdin"] is False
            self.id = request["header"]["msg_id"]
            self.messages = [
                ("stream", {"text": "42\n", "name": "stdout"}),
                ("status", {"execution_state": "idle"}),
            ]

        async def recv(self):
            kind, content = self.messages.pop(0)
            return json.dumps(
                {
                    "header": {"msg_type": kind},
                    "parent_header": {"msg_id": self.id},
                    "content": content,
                }
            )

    def connect(url, **kwargs):
        assert "/user/arena-2/api/kernels/kernel-1/channels" in url
        assert kwargs["additional_headers"]["Authorization"] == "token test-token"
        return Socket()

    monkeypatch.setattr("app.notebook_editor.connect", connect)
    response = member.post(
        "/api/editor/notebooks/1/execute", json={"code": "print(42)"}
    )
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[0]["content"]["text"] == "42\n"
    assert events[-1]["type"] == "done"


def test_native_editor_requires_authentication(client, hub):
    assert client.get("/api/editor/notebooks/1/document").status_code == 401
    assert (
        client.post(
            "/api/editor/notebooks/1/execute", json={"code": "print(1)"}
        ).status_code
        == 401
    )


def test_dataset_inputs_copy_bytes_to_user_workspace(member, hub):
    import base64

    uploaded = member.post(
        "/api/datasets",
        data={"title": "Notebook input", "description": "CSV attached to a notebook"},
        files={"file": ("sample.csv", b"x,y\n1,2\n", "text/csv")},
    ).json()
    dataset_id = uploaded["id"]
    assert (
        member.put(
            f"/api/datasets/{dataset_id}/access", json={"visibility": "public"}
        ).status_code
        == 200
    )
    response = member.post(f"/api/editor/notebooks/1/inputs/{dataset_id}")
    assert response.status_code == 200
    path = response.json()["path"]
    assert path == f"arena-input-{dataset_id}.csv"
    copied = hub.files[f"/user/arena-2/api/contents/{path}"]
    assert base64.b64decode(copied["content"]) == b"x,y\n1,2\n"
    assert member.post("/api/editor/notebooks/1/inputs/99999").status_code == 404
    assert (
        member.post(f"/api/editor/notebooks/missing/inputs/{dataset_id}").status_code
        == 404
    )
    draft = member.post("/api/notebook-drafts").json()["id"]
    member.post("/api/auth/logout")
    assert (
        member.post(f"/api/editor/notebooks/1/inputs/{dataset_id}").status_code == 401
    )
    member.post(
        "/api/auth/register",
        json={"username": "inputother", "password": "other-password"},
    )
    assert (
        member.post(f"/api/editor/drafts/{draft}/inputs/{dataset_id}").status_code
        == 404
    )
    assert (
        member.post(f"/api/editor/notebooks/1/inputs/{dataset_id}").status_code == 200
    )
    assert (
        base64.b64decode(hub.files[f"/user/arena-3/api/contents/{path}"]["content"])
        == b"x,y\n1,2\n"
    )
