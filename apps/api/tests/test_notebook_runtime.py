import json

import httpx
import pytest

from app.main import app
from app.notebook_runtime import get_hub


class FakeHub:
    """Hub/Contents contract double. Real kernel execution is tested separately."""

    def __init__(self):
        self.state = "stopped"
        self.users = set()
        self.files = {}
        self.calls = []

    async def status(self, user):
        return {"state": self.state}

    @staticmethod
    def expect(response, statuses=(200,)):
        from app.notebook_runtime import HubClient

        return HubClient.expect(response, statuses)

    async def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if path.endswith("/api/sessions"):
            return httpx.Response(200, json=[])
        if "/api/contents/" in path:
            if method == "DELETE":
                self.files.pop(path, None)
                return httpx.Response(204)
            if method == "GET":
                return (
                    httpx.Response(200, json=self.files[path])
                    if path in self.files
                    else httpx.Response(404)
                )
            self.files[path] = kwargs["json"]
            return httpx.Response(201, json=self.files[path])
        if path.endswith("/server"):
            self.state = "starting" if method == "POST" else "stopped"
            return httpx.Response(202 if method == "POST" else 204)
        if method == "POST":
            self.users.add(path)
            return httpx.Response(201, json={})
        return httpx.Response(200 if path in self.users else 404, json={})


@pytest.fixture
def hub():
    hub = FakeHub()
    app.dependency_overrides[get_hub] = lambda: hub
    yield hub
    app.dependency_overrides.pop(get_hub, None)


def test_start_poll_open_save_reopen_download_and_stop(member, hub):
    assert member.get("/api/notebook-session").json() == {"state": "stopped"}
    assert member.post("/api/notebook-session").json() == {"state": "starting"}
    assert member.post("/api/notebooks/1/open").status_code == 409
    hub.state = "ready"
    assert member.get("/api/notebook-session").json() == {"state": "ready"}
    opened = member.post("/api/notebooks/1/open")
    assert opened.status_code == 200
    assert opened.json()["url"].startswith("/jupyter/hub/arena-login?next=")
    assert "token" not in opened.text
    path = "/user/arena-2/api/contents/arena-notebook-1.ipynb"
    assert hub.files[path]["content"]["nbformat"] == 4
    hub.files[path]["content"]["cells"][0]["outputs"] = [
        {"output_type": "stream", "name": "stdout", "text": "42\n"}
    ]
    assert member.post("/api/notebooks/1/open").status_code == 200
    assert len([call for call in hub.calls if call[0] == "PUT"]) == 1
    exported = member.get("/api/notebooks/1/working-copy")
    assert exported.json()["cells"][0]["outputs"][0]["text"] == "42\n"
    assert member.delete("/api/notebook-session").json() == {"state": "stopped"}
    assert member.get("/api/notebooks/1/working-copy").status_code == 409


def test_separate_private_copies_and_no_template_overwrite(member, hub):
    hub.state = "ready"
    assert member.post("/api/notebooks/1/open").status_code == 200
    member.post("/api/auth/logout")
    member.post(
        "/api/auth/register", json={"username": "other", "password": "another-password"}
    )
    assert member.post("/api/notebooks/1/open").status_code == 200
    assert "/user/arena-2/api/contents/arena-notebook-1.ipynb" in hub.files
    assert "/user/arena-3/api/contents/arena-notebook-1.ipynb" in hub.files


@pytest.mark.parametrize(
    "path",
    [
        "/jupyter/user/arena-3/lab",
        "/jupyter/user/arena-3/api/kernels/1/channels",
        "/jupyter/hub/api/users",
        "/jupyter/user/arena-2/../arena-3/lab",
        "/jupyter/user/arena-2/%2e%2e/arena-3/lab",
        "/jupyter/user/arena-2/%252e%252e/arena-3/lab",
        "/jupyter/user/arena-2/\\arena-3/lab",
        "/unrelated",
    ],
)
def test_gateway_rejects_other_users_and_traversal(member, path):
    assert (
        member.get(
            "/api/internal/notebook-access", headers={"X-Original-URI": path}
        ).status_code
        == 403
    )


def test_gateway_session_and_websocket_handshake(member):
    path = "/jupyter/user/arena-2/api/kernels/1/channels?session_id=abc"
    assert (
        member.get(
            "/api/internal/notebook-access", headers={"X-Original-URI": path}
        ).status_code
        == 204
    )
    assert (
        member.get(
            "/api/internal/notebook-access",
            headers={"X-Original-URI": "/jupyter/hub/api/oauth2/authorize"},
        ).status_code
        == 204
    )
    member.post("/api/auth/logout")
    assert (
        member.get(
            "/api/internal/notebook-access", headers={"X-Original-URI": path}
        ).status_code
        == 401
    )


def test_unconfigured_runtime_and_missing_notebook(member, monkeypatch):
    monkeypatch.delenv("JUPYTERHUB_API_URL", raising=False)
    assert member.get("/api/notebook-session").status_code == 503


def test_unauthenticated_runtime(client, hub):
    assert client.get("/api/notebook-session").status_code == 401
    assert client.post("/api/notebook-session").status_code == 401
    assert client.post("/api/notebooks/1/open").status_code == 401
    assert client.delete("/api/notebook-session").status_code == 401
