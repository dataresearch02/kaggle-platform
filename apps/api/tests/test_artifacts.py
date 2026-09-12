from app.db import get_db
from app.main import app
from app.models import WorkFileDeletion
from sqlalchemy import select


def test_dataset_file_versions_permissions_and_deletion(member):
    dataset = member.post(
        "/api/datasets",
        data={"title": "Versioned data", "description": "Test files"},
        files={"file": ("x.csv", b"x\n1\n")},
    ).json()
    base = f"/api/assets/datasets/{dataset['id']}"
    versions = []
    for content in (b"first", b"second"):
        response = member.post(
            base,
            data={"path": "images/example.bin"},
            files={"file": ("example.bin", content)},
        )
        assert response.status_code == 201
        versions.append(response.json()["id"])
    assert len(member.get(base).json()) == 2
    for id, content in zip(versions, (b"first", b"second")):
        response = member.get(f"{base}/{id}/download")
        assert response.content == content
        assert response.headers["content-type"] == "application/octet-stream"
    for path in ("../escape", "/absolute", "nested//file", "nested/./file", "a\\b"):
        assert (
            member.post(
                base, data={"path": path}, files={"file": ("a", b"x")}
            ).status_code
            == 422
        )
    member.post("/api/auth/logout")
    assert member.get(base).status_code == 404
    assert member.get(f"{base}/{versions[0]}/download").status_code == 404
    member.post(
        "/api/auth/register",
        json={"username": "other", "password": "good-password-123"},
    )
    assert (
        member.post(base, data={"path": "x"}, files={"file": ("a", b"x")}).status_code
        == 404
    )
    member.post("/api/auth/logout")
    member.post(
        "/api/auth/login", json={"username": "learner", "password": "good-password-123"}
    )
    assert member.delete(f"/api/work/datasets/{dataset['id']}").status_code == 204
    with next(app.dependency_overrides[get_db]()) as db:
        assert (
            len(
                list(
                    db.scalars(
                        select(WorkFileDeletion).where(
                            WorkFileDeletion.kind == "artifact"
                        )
                    )
                )
            )
            == 2
        )


def test_hosted_model_without_reference_url(member):
    response = member.post(
        "/api/models",
        json={
            "title": "Hosted model",
            "description": "Versioned weights",
            "framework": "PyTorch",
            "license": "MIT",
        },
    )
    assert response.status_code == 201
    detail_url = f"/api/models/{response.json()['id']}"
    assert member.get(detail_url).json()["input_available"] is False
    assert member.get("/api/models/999999").status_code == 404
    base = f"/api/assets/models/{response.json()['id']}"
    artifact = member.post(
        base, data={"path": "weights.bin"}, files={"file": ("weights.bin", b"weights")}
    )
    assert artifact.status_code == 201
    assert member.get(detail_url).json()["input_available"] is True
    member.post("/api/auth/logout")
    assert member.get(f"{base}/{artifact.json()['id']}/download").content == b"weights"
