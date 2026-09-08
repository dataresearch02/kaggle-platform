import json
import math
import pytest
from app.scoring import score_csv


def test_account_session_lifecycle(client):
    assert client.get("/api/auth/me").status_code == 401
    assert (
        client.post(
            "/api/auth/register",
            json={"username": "Alice", "password": "great-password"},
        ).status_code
        == 201
    )
    assert client.get("/api/auth/me").json()["username"] == "alice"
    assert (
        client.post(
            "/api/auth/register",
            json={"username": "alice", "password": "great-password"},
        ).status_code
        == 409
    )
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    assert (
        client.post(
            "/api/auth/login", json={"username": "alice", "password": "wrong-password"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/auth/login", json={"username": "alice", "password": "great-password"}
        ).status_code
        == 200
    )


def test_csrf(client):
    payload = {"username": "learner", "password": "a-long-password"}
    assert (
        client.post(
            "/api/auth/register",
            json=payload,
            headers={"Origin": "https://foreign.example"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/auth/register", json=payload, headers={"X-Arena-Client": ""}
        ).status_code
        == 403
    )


def test_dataset_upload_preview_download(member):
    content = b"id,value\n1,3\n2,5\n"
    result = member.post(
        "/api/datasets",
        data={"title": "My dataset", "description": "Test data"},
        files={"file": ("data.csv", content, "text/csv")},
    )
    assert result.status_code == 201, result.text
    data = result.json()
    assert "storage_key" not in data
    assert member.get(f"/api/datasets/{data['id']}").json()["preview"][0] == {
        "id": "1",
        "value": "3",
    }
    assert member.get(f"/api/datasets/{data['id']}/download").content == content
    assert len(member.get("/api/datasets?q=My%20dataset").json()) == 1
    bad = member.post(
        "/api/datasets",
        data={"title": "Bad dataset", "description": "Invalid data"},
        files={"file": ("bad.csv", b"a,a\n1,2\n")},
    )
    assert bad.status_code == 422


def test_competition_submission_and_best_score(member):
    assert "solution" not in member.get("/api/competitions/1").json()
    assert "solution" not in member.get("/api/competitions").json()[0]
    content = b"id,prediction\n7,240\n8,100\n9,300\n"
    assert (
        member.post(
            "/api/competitions/1/submissions", files={"file": ("p.csv", content)}
        ).status_code
        == 403
    )
    assert member.post("/api/competitions/1/join").json() == {"joined": True}
    assert member.post("/api/competitions/1/join").status_code == 200
    assert (
        member.post(
            "/api/competitions/1/submissions", files={"file": ("p.csv", content)}
        ).json()["score"]
        == 0
    )
    assert (
        member.post(
            "/api/competitions/1/submissions",
            files={"file": ("p.csv", b"id,prediction\n7,0\n8,0\n9,0\n")},
        ).status_code
        == 201
    )
    board = member.get("/api/competitions/1").json()
    assert board["participants"] == 1
    assert board["leaderboard"] == [{"rank": 1, "username": "learner", "score": 0.0}]
    assert len(member.get("/api/competitions/1/submissions").json()) == 2
    assert b"prediction" in member.get("/api/competitions/1/sample").content
    assert b"temperature" in member.get("/api/competitions/1/test").content


@pytest.mark.parametrize(
    "content",
    [
        b"id,prediction\n1,nan\n",
        b"id,prediction\n1,inf\n",
        b"id,prediction\n1,2\n1,3\n",
        b"id,prediction\n2,3\n",
        b"id,value\n1,3\n",
        b"id,prediction\n1,3,4\n",
        b"id,prediction\n1,1e100\n",
    ],
)
def test_scoring_rejects_invalid_predictions(content):
    with pytest.raises(ValueError):
        score_csv(content, {"1": 3})


def test_rmse_calculation():
    assert score_csv(b"id,prediction\na,3\nb,5\n", {"a": 1, "b": 1}) == pytest.approx(
        math.sqrt(10)
    )


def test_notebook_ownership_and_export(member):
    payload = {
        "title": "Experiment",
        "description": "My first model",
        "code": "print(42)",
    }
    assert member.put("/api/notebooks/1", json=payload).status_code == 403
    notebook = member.post("/api/notebooks", json=payload).json()
    path = f"/api/notebooks/{notebook['id']}"
    assert member.put(path, json={**payload, "code": "print(43)"}).status_code == 200
    exported = json.loads(member.get(path + "/download").content)
    assert exported["nbformat"] == 4
    assert exported["cells"][0]["source"] == ["print(43)"]
    member.post("/api/auth/logout")
    member.post(
        "/api/auth/register",
        json={"username": "another", "password": "another-password"},
    )
    assert member.put(path, json=payload).status_code == 403


def test_learning_discussions_and_models(member):
    course = member.get("/api/courses").json()[0]
    path = f"/api/courses/{course['id']}"
    assert member.post(path + "/lessons/0/complete").status_code == 200
    assert member.post(path + "/lessons/0/complete").status_code == 200
    assert member.get(path + "/progress").json() == [0]
    assert member.post(path + "/lessons/100/complete").status_code == 404
    thread = member.post(
        "/api/discussions", json={"title": "A question", "body": "How do I train?"}
    ).json()
    reply = member.post(
        f"/api/discussions/{thread['id']}/comments",
        json={"body": "Start with a baseline."},
    )
    assert reply.status_code == 201
    assert (
        member.get(f"/api/discussions/{thread['id']}/comments").json()[0]["owner"]
        == "learner"
    )
    card = {
        "title": "My baseline",
        "description": "A reference model",
        "framework": "sklearn",
        "license": "MIT",
        "url": "https://example.com/model",
    }
    assert member.post("/api/models", json=card).status_code == 201
    assert (
        member.post(
            "/api/models", json={**card, "url": "javascript:alert(1)"}
        ).status_code
        == 422
    )


def test_mutations_require_login(client):
    assert (
        client.post(
            "/api/notebooks", json={"title": "No owner", "code": ""}
        ).status_code
        == 401
    )
    assert client.post("/api/competitions/1/join").status_code == 401
    assert client.get("/api/competitions/999").status_code == 404
