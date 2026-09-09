import pytest


def publish(client, kind="competitions", **overrides):
    data = {
        "title": "Community regression",
        "description": "Predict demand from temperature.",
        "deadline": "2099-01-01T00:00:00Z",
    }
    data.update(overrides.pop("data", {}))
    return client.post(
        f"/api/{kind}",
        data=data,
        files={
            "test_file": (
                "test.csv",
                overrides.get("test", "id,temperature\na,20\nb,30\n"),
            ),
            "solution_file": (
                "answers.csv",
                overrides.get("answers", "id,prediction\na,123.45\nb,678.9\n"),
            ),
        },
    )


@pytest.mark.parametrize("kind", ["competitions", "benchmarks"])
def test_creator_can_publish_and_participant_can_score(member, kind):
    response = publish(member, kind)
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["owner"] == "learner"
    assert "solution" not in created and "test_csv" not in created
    id = created["id"]
    assert id in [item["id"] for item in member.get(f"/api/{kind}").json()]
    other = "benchmarks" if kind == "competitions" else "competitions"
    assert id not in [item["id"] for item in member.get(f"/api/{other}").json()]
    detail = member.get(f"/api/{kind}/{id}").json()
    assert (
        detail["deadline"] is None
        if kind == "benchmarks"
        else detail["deadline"] is not None
    )
    assert "123.45" not in str(detail)
    assert member.get(f"/api/{kind}/{id}/test").text == "id,temperature\na,20\nb,30\n"
    assert member.get(f"/api/{kind}/{id}/sample").text == "id,prediction\na,0\nb,0\n"
    member.post("/api/auth/logout")
    member.post(
        "/api/auth/register",
        json={"username": "participant", "password": "participant-password"},
    )
    assert member.post(f"/api/{kind}/{id}/join").status_code == 200
    result = member.post(
        f"/api/{kind}/{id}/submissions",
        files={"file": ("predictions.csv", "id,prediction\na,123.45\nb,678.9\n")},
    )
    assert result.status_code == 201
    assert result.json()["score"] == 0
    assert (
        member.get(f"/api/{kind}/{id}").json()["leaderboard"][0]["username"]
        == "participant"
    )


def test_creation_requires_login(client):
    assert publish(client).status_code == 401
    assert publish(client, "benchmarks").status_code == 401


@pytest.mark.parametrize(
    "overrides",
    [
        {"data": {"deadline": "2020-01-01T00:00:00Z"}},
        {"data": {"deadline": "2099-01-01"}},
        {"answers": "id,prediction\na,nan\nb,4\n"},
        {"answers": "id,prediction\na,1\na,2\n"},
        {"answers": "id,prediction\na,1\nc,2\n"},
        {"test": "id,temperature\na,1\na,2\n"},
        {"test": "id,temperature\n"},
    ],
)
def test_invalid_challenge_is_not_published(member, overrides):
    before = member.get("/api/competitions").json()
    assert publish(member, **overrides).status_code == 422
    assert member.get("/api/competitions").json() == before
