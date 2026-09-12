import base64
import httpx
from app.main import app
from app.notebook_runtime import get_hub


class Hub:
    calls = []

    async def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if method == "GET":
            if path.endswith("predictions.csv"):
                data = {
                    "type": "file",
                    "size": 18,
                    "content": base64.b64encode(b"value\n42\n").decode(),
                }
                return httpx.Response(200, json=data)
            return httpx.Response(404)
        return httpx.Response(201, json={})

    def expect(self, response, codes=(200,)):
        assert response.status_code in codes
        return response


def test_output_exports_permissions_and_attach(member):
    hub = Hub()
    app.dependency_overrides[get_hub] = lambda: hub
    try:
        source = member.post(
            "/api/notebooks", json={"title": "Output producer", "code": "print(1)"}
        ).json()["id"]
        private = member.post(
            f"/api/code/{source}/outputs", json={"path": "outputs/predictions.csv"}
        ).json()
        shared = member.post(
            f"/api/code/{source}/outputs",
            json={"path": "outputs/predictions.csv", "shared": True},
        ).json()
        assert private["sha256"] == shared["sha256"]
        assert private["id"] != shared["id"]
        assert (
            member.post(
                f"/api/code/{source}/outputs", json={"path": "../predictions.csv"}
            ).status_code
            == 422
        )
        assert (
            member.get(f"/api/notebook-outputs/{shared['id']}/download").content
            == b"value\n42\n"
        )
        member.post("/api/auth/logout")
        member.post(
            "/api/auth/register",
            json={"username": "consumer", "password": "good-password-123"},
        )
        assert member.get("/api/notebook-outputs").json()["items"] == []
        assert (
            member.get(f"/api/notebook-outputs/{shared['id']}/download").status_code
            == 404
        )
        target = member.post(
            "/api/notebooks", json={"title": "Output consumer", "code": "print(2)"}
        ).json()["id"]
        member.post("/api/auth/logout")
        member.post(
            "/api/auth/login",
            json={"username": "learner", "password": "good-password-123"},
        )
        assert (
            member.post(
                f"/api/code/{source}/shares", json={"username": "consumer"}
            ).status_code
            == 201
        )
        member.post("/api/auth/logout")
        member.post(
            "/api/auth/login",
            json={"username": "consumer", "password": "good-password-123"},
        )
        assert [
            row["id"] for row in member.get("/api/notebook-outputs").json()["items"]
        ] == [shared["id"]]
        result = member.post(
            f"/api/editor/notebooks/{target}/notebook-inputs/{shared['id']}"
        )
        assert result.status_code == 200
        assert (
            result.json()["path"] == f"input/notebooks/{shared['id']}/predictions.csv"
        )
        assert any(
            call[0] == "PUT" and call[1].endswith(result.json()["path"])
            for call in hub.calls
        )
        assert (
            member.post(
                f"/api/editor/notebooks/{target}/notebook-inputs/{private['id']}"
            ).status_code
            == 404
        )
        assert (
            member.post(
                f"/api/code/{source}/outputs", json={"path": "outputs/predictions.csv"}
            ).status_code
            == 404
        )
    finally:
        app.dependency_overrides.pop(get_hub, None)


def test_committed_outputs_exclude_inputs_hidden_files_and_symlinks(tmp_path):
    from app.notebook_files import collect_job_files

    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "private.csv").write_text("private")
    (tmp_path / "test.csv").write_text("private test")
    (tmp_path / "runner.py").write_text("internal runner")
    (tmp_path / ".secret").write_text("hidden")
    (tmp_path / "arena-input-1.csv").write_text("input")
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "model.txt").write_text("trained")
    (tmp_path / "submission.csv").write_text("prediction")
    (tmp_path / "linked.txt").symlink_to(tmp_path / ".secret")
    assert dict(collect_job_files(tmp_path)) == {
        "models/model.txt": b"trained",
        "submission.csv": b"prediction",
    }
