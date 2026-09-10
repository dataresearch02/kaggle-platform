from app.main import app
from app.db import get_db
from app.models import CompetitionResource, CompetitionPost
from sqlalchemy import select
from test_challenges import publish


def test_competition_page_resources_and_discussion(member):
    challenge = publish(member).json()
    id = challenge["id"]
    other = publish(member).json()["id"]
    base = f"/api/competitions/{id}"
    data = member.get(base + "/data").json()
    assert data["columns"] == ["id", "temperature"]
    assert data["rows"] == 2
    assert "prediction" not in str(data) and "123.45" not in str(data)
    assert member.get(base + "/membership").json() == {"joined": False}
    member.post(base + "/join")
    assert member.get(base + "/membership").json() == {"joined": True}
    code = member.post(
        "/api/notebooks", json={"title": "Competition analysis", "code": "print(1)"}
    ).json()
    model = member.post(
        "/api/models",
        json={
            "title": "Competition model",
            "description": "Model card",
            "framework": "PyTorch",
            "license": "MIT",
            "url": "https://example.com/model",
        },
    ).json()
    for kind, row in [("models", model)]:
        path = f'{base}/resources/{kind}/{row["id"]}'
        assert member.post(path).status_code == 201
        assert member.post(path).status_code == 201
        assert len(member.get(f"{base}/resources/{kind}").json()) == 1
        assert member.get(f"/api/competitions/{other}/resources/{kind}").json() == []
    assert member.post(base + f'/resources/notebooks/{code["id"]}').status_code == 409
    assert (
        member.post(
            base + "/discussion",
            json={"title": "Question", "body": "How do we get started?"},
        ).status_code
        == 201
    )
    assert len(member.get(base + "/discussion").json()) == 1
    assert member.get(f"/api/competitions/{other}/discussion").json() == []
    assert member.delete(f'/api/work/notebooks/{code["id"]}').status_code == 204
    assert member.get(base + "/resources/notebooks").json() == []
    member.post("/api/auth/logout")
    assert member.get(base + "/data").status_code == 401
    assert member.get(base + "/resources/models").status_code == 200
    assert member.get(base + "/discussion").status_code == 200
    assert member.get(base + "/membership").status_code == 401
    assert (
        member.post(
            base + "/discussion", json={"title": "Question", "body": "Anonymous post"}
        ).status_code
        == 401
    )
    assert member.post(base + f'/resources/models/{model["id"]}').status_code == 401
    member.post(
        "/api/auth/login", json={"username": "learner", "password": "good-password-123"}
    )
    assert member.delete(f"/api/work/competitions/{id}").status_code == 204
    with next(app.dependency_overrides[get_db]()) as db:
        assert not list(
            db.scalars(
                select(CompetitionResource).where(
                    CompetitionResource.competition_id == id
                )
            )
        )
        assert not list(
            db.scalars(
                select(CompetitionPost).where(CompetitionPost.competition_id == id)
            )
        )
    assert member.get(base + "/data").status_code == 404
    assert member.get(base + "/discussion").status_code == 404
