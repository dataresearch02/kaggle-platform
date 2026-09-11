from datetime import datetime, timedelta, timezone

from app.db import get_db
from app.main import app
from app.models import Competition
from test_challenges import publish


def test_team_membership_and_captain_transfer(member):
    competition = publish(member).json()["id"]
    other = publish(member).json()["id"]
    base = f"/api/competitions/{competition}"
    assert member.get(base + "/team").json() is None
    assert member.post(base + "/team", json={"name": "Team"}).status_code == 403
    member.post(base + "/join")
    assert member.post(base + "/team", json={"name": "  "}).status_code == 422
    response = member.post(base + "/team", json={"name": " Team Arena "})
    assert response.status_code == 201
    team = response.json()
    assert team["name"] == "Team Arena"
    assert len(team["members"]) == 1
    assert member.post(base + "/team", json={"name": "Duplicate"}).status_code == 409
    member.post("/api/auth/logout")
    assert member.get(base + "/team").status_code == 401
    member.post(
        "/api/auth/register",
        json={"username": "teammate", "password": "good-password-123"},
    )
    assert member.get(base + "/team").json() is None
    member.post(base + "/join")
    member.post(f"/api/competitions/{other}/join")
    assert (
        member.post(
            f"/api/competitions/{other}/team/join",
            json={"invite_code": team["invite_code"]},
        ).status_code
        == 404
    )
    assert (
        member.post(base + "/team/join", json={"invite_code": "invalid"}).status_code
        == 404
    )
    response = member.post(
        base + "/team/join", json={"invite_code": team["invite_code"]}
    )
    assert response.status_code == 200
    assert len(response.json()["members"]) == 2
    assert (
        member.post(
            base + "/team/join", json={"invite_code": team["invite_code"]}
        ).status_code
        == 409
    )
    member.post("/api/auth/logout")
    member.post(
        "/api/auth/login", json={"username": "learner", "password": "good-password-123"}
    )
    assert member.delete(base + "/team").status_code == 204
    assert member.get(base + "/team").json() is None
    member.post("/api/auth/logout")
    member.post(
        "/api/auth/login",
        json={"username": "teammate", "password": "good-password-123"},
    )
    remaining = member.get(base + "/team").json()
    assert len(remaining["members"]) == 1
    assert remaining["owner_id"] == remaining["members"][0]["id"]
    assert member.delete(base + "/team").status_code == 204
    assert (
        member.post(
            base + "/team/join", json={"invite_code": team["invite_code"]}
        ).status_code
        == 404
    )


def test_closed_and_deleted_competition_teams(member):
    competition = publish(member).json()["id"]
    base = f"/api/competitions/{competition}"
    member.post(base + "/join")
    assert (
        member.post(base + "/team", json={"name": "Persistent team"}).status_code == 201
    )
    with next(app.dependency_overrides[get_db]()) as db:
        db.get(Competition, competition).deadline = (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).isoformat()
        db.commit()
    assert member.get(base + "/team").json()["name"] == "Persistent team"
    assert member.delete(base + "/team").status_code == 409
    assert (
        member.post(base + "/team/join", json={"invite_code": "invalid"}).status_code
        == 409
    )
    assert member.delete(f"/api/work/competitions/{competition}").status_code == 204
    assert member.get(base + "/team").status_code == 404


def test_team_submission_history_and_locked_membership(member):
    competition = publish(member).json()["id"]
    base = f"/api/competitions/{competition}"
    member.post(base + "/join")
    team = member.post(base + "/team", json={"name": "Scoring team"}).json()
    response = member.post(
        base + "/submissions", files={"file": ("p.csv", b"id,prediction\na,1\nb,2\n")}
    )
    assert response.status_code == 201, response.text
    board = member.get(base).json()["leaderboard"]
    assert board[0]["team_id"] == team["id"]
    assert "Scoring team" in board[0]["username"]
    assert member.delete(base + "/team").status_code == 409
    member.post("/api/auth/logout")
    member.post(
        "/api/auth/register",
        json={"username": "newteammate", "password": "good-password-123"},
    )
    member.post(base + "/join")
    assert (
        member.post(
            base + "/team/join", json={"invite_code": team["invite_code"]}
        ).status_code
        == 200
    )
    assert len(member.get(base + "/submissions").json()) == 1
