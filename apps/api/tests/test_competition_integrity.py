import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app import notebook_commits
from app.competition_results import medal_cutoffs, medal_for
from app.db import get_db
from app.main import app
from app.models import (
    AuditLog,
    Competition,
    CompetitionOverview,
    CompetitionResult,
    NotebookCommit,
    Submission,
    SubmissionPrediction,
    User,
)
from test_challenges import publish

ACCEPT = {"accept_rules": True}
PASSWORD = "good-password-123"
# Rows a and b are public, c and d private.
SPLIT = "id,prediction,Usage\na,1,Public\nb,2,Public\nc,3,Private\nd,4,Private\n"


def database():
    return next(app.dependency_overrides[get_db]())


def account(client, username):
    client.post("/api/auth/logout")
    response = client.post(
        "/api/auth/login", json={"username": username, "password": PASSWORD}
    )
    if response.status_code != 200:
        response = client.post(
            "/api/auth/register", json={"username": username, "password": PASSWORD}
        )
    assert response.status_code in (200, 201), response.text
    return client


def user_id(username):
    with database() as db:
        return db.scalar(select(User.id).where(User.username == username))


def post_competition(client, answers=SPLIT, metric="MAE", **data):
    ids = [line.split(",")[0] for line in answers.strip().splitlines()[1:]]
    return client.post(
        "/api/competitions",
        data={
            "title": "Integrity challenge",
            "description": "Scored on public and private rows.",
            "deadline": "2099-01-01T00:00:00Z",
            "metric": metric,
            **data,
        },
        files={
            "test_file": ("test.csv", "id,x\n" + "".join(f"{i},1\n" for i in ids)),
            "solution_file": ("answers.csv", answers),
        },
    )


def create(client, answers=SPLIT, metric="MAE", **data):
    response = post_competition(client, answers, metric, **data)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def predictions(**values):
    return {
        "file": (
            "p.csv",
            "id,prediction\n" + "".join(f"{k},{v}\n" for k, v in values.items()),
        )
    }


def hours(value):
    return (datetime.now(timezone.utc) + timedelta(hours=value)).isoformat()


def shift(id, **fields):
    """Set timeline fields directly, relative to now in hours."""
    with database() as db:
        for key, value in fields.items():
            if key == "starts_at":
                db.get(CompetitionOverview, id).starts_at = hours(value)
            else:
                setattr(db.get(Competition, id), key, hours(value))
        db.commit()


def settings(client, id, **changes):
    state = client.get(f"/api/competitions/{id}/host").json()
    payload = {
        key: state[key]
        for key in (
            "starts_at",
            "entry_deadline",
            "merger_deadline",
            "ends_at",
            "max_daily_submissions",
            "max_final_submissions",
            "metric",
            "metric_k",
        )
    }
    return client.put(
        f"/api/competitions/{id}/host/settings", json={**payload, **changes}
    )


def audit_actions(id):
    with database() as db:
        return [
            row.action
            for row in db.scalars(
                select(AuditLog).where(
                    AuditLog.target_kind == "competition", AuditLog.target_id == str(id)
                )
            )
        ]


def test_rules_acceptance_and_material_changes(member):
    id = create(member, rules="Be kind.")
    base = f"/api/competitions/{id}"
    assert member.get(base).json()["rules"] == "Be kind."
    account(member, "alice")
    assert member.post(base + "/join").status_code == 422
    assert member.post(base + "/join", json={"accept_rules": False}).status_code == 422
    stale = member.post(base + "/join", json={**ACCEPT, "rules_revision": 2})
    assert stale.status_code == 409
    assert member.get(base + "/membership").json()["joined"] is False
    assert (
        member.post(base + "/join", json={**ACCEPT, "rules_revision": 1}).status_code
        == 200
    )
    state = member.get(base + "/membership").json()
    assert state["accepted_rules_revision"] == 1
    assert state["rules_accepted_at"] and not state["needs_rules_acceptance"]
    assert (
        member.put(base + "/rules", json={"content": "Mine", "material": True})
    ).status_code == 403

    account(member, "learner")
    typo = member.put(base + "/rules", json={"content": "Be kind!", "material": False})
    assert typo.json()["rules_revision"] == 1
    material = member.put(
        base + "/rules", json={"content": "Do not share code.", "material": True}
    )
    assert material.json()["rules_revision"] == 2

    account(member, "alice")
    assert member.get(base + "/membership").json()["needs_rules_acceptance"] is True
    blocked = member.post(base + "/submissions", files=predictions(a=1, b=2, c=3, d=4))
    assert blocked.status_code == 409 and "rules" in blocked.json()["detail"]
    assert member.post(base + "/join", json=ACCEPT).status_code == 200
    assert (
        member.post(
            base + "/submissions", files=predictions(a=1, b=2, c=3, d=4)
        ).status_code
        == 201
    )
    assert audit_actions(id).count("competition.rules") == 2


def test_timeline_limits_entry_teams_and_submissions(member):
    id = create(member)
    base = f"/api/competitions/{id}"
    assert (
        settings(member, id, entry_deadline="2100-01-01T00:00:00Z").status_code == 422
    )
    assert (
        settings(member, id, starts_at=hours(2), entry_deadline=hours(1)).status_code
        == 422
    )
    assert settings(member, id, starts_at="2099-01-01T00:00:00").status_code == 422
    assert settings(member, id, starts_at=hours(1)).status_code == 200
    benchmark = publish(member, "benchmarks").json()["id"]
    assert settings(member, benchmark, starts_at=hours(1)).status_code == 422

    account(member, "alice")
    assert member.post(base + "/join", json=ACCEPT).status_code == 200
    early = member.post(base + "/submissions", files=predictions(a=1, b=2, c=3, d=4))
    assert early.status_code == 409 and "starts" in early.json()["detail"]

    shift(id, starts_at=-3, entry_deadline=-1, merger_deadline=5)
    assert (
        member.post(
            base + "/submissions", files=predictions(a=1, b=2, c=3, d=4)
        ).status_code
        == 201
    )
    assert member.post(base + "/team", json={"name": "Late"}).status_code == 409
    timeline = member.get(base).json()["timeline"]
    assert timeline["entry_open"] is False and timeline["team_changes_open"] is True
    account(member, "bob")
    late = member.post(base + "/join", json=ACCEPT)
    assert late.status_code == 409 and "entry deadline" in late.json()["detail"]

    shift(id, entry_deadline=2, merger_deadline=-1)
    assert member.post(base + "/join", json=ACCEPT).status_code == 200
    assert member.post(base + "/team", json={"name": "Merged"}).status_code == 409
    assert member.delete(base + "/team").status_code == 409

    shift(id, entry_deadline=-3, merger_deadline=-2, deadline=-1)
    closed = member.post(base + "/submissions", files=predictions(a=1, b=2, c=3, d=4))
    assert closed.status_code == 409
    assert member.get(base).json()["timeline"]["ended"] is True


def test_private_scores_final_selection_and_finalization(member):
    id = create(member)
    base = f"/api/competitions/{id}"

    def final(submission, selected=True):
        return member.put(
            f"{base}/submissions/{submission}/final", json={"selected": selected}
        )

    account(member, "alice")
    member.post(base + "/join", json=ACCEPT)
    # Public error 0 / private 10, public 10 / private 0, public 1 / private 1.
    first, second, third = (
        member.post(base + "/submissions", files=predictions(**values)).json()
        for values in (
            dict(a=1, b=2, c=13, d=14),
            dict(a=11, b=12, c=3, d=4),
            dict(a=2, b=3, c=4, d=5),
        )
    )
    assert first["score"] == 0 and "private_score" not in first
    assert all(
        "private_score" not in row for row in member.get(base + "/submissions").json()
    )
    assert member.get(base + "/leaderboard").json()[0]["score"] == 0
    assert member.get(base + "/leaderboard?board=private").status_code == 403
    detail = member.get(base).json()
    assert detail["leaderboard_split"] is True
    assert "solution" not in detail and "solution_usage" not in detail
    assert "Private" not in json.dumps(detail)
    assert final(second["id"]).json()["final_selected"] is True
    assert final(third["id"]).status_code == 200
    assert final(first["id"]).status_code == 409
    assert member.get(base + "/membership").json()["final_selected"] == 2
    assert final(third["id"], False).status_code == 200

    account(member, "bob")
    member.post(base + "/join", json=ACCEPT)
    assert final(second["id"]).status_code == 404
    # No selection: the two best public submissions count (private 2 and 1.5).
    for values in (
        dict(a=1, b=2, c=5, d=6),
        dict(a=2, b=2, c=4.5, d=5.5),
        dict(a=5, b=6, c=3, d=4),
    ):
        assert (
            member.post(base + "/submissions", files=predictions(**values)).status_code
            == 201
        )

    account(member, "learner")
    preview = member.get(base + "/leaderboard?board=private").json()
    assert [(row["username"], row["score"]) for row in preview] == [
        ("alice", 0.0),
        ("bob", 1.5),
    ]
    assert preview[1]["automatic_selection"] is True
    host_rows = member.get(base + "/host/submissions").json()
    assert {row["private_score"] for row in host_rows} >= {0.0, 10.0, 1.5}

    shift(id, deadline=-1)
    account(member, "alice")
    assert final(first["id"]).status_code == 409
    assert member.get(base + "/submissions").json()[0]["private_score"] == 1.0
    board = member.get(base + "/leaderboard?board=private").json()
    assert [(r["username"], r["score"], r["public_rank"]) for r in board] == [
        ("alice", 0.0, 1),
        ("bob", 1.5, 2),
    ]
    # Two ranked teams are too few for any medal.
    assert all(row["medal"] is None for row in board)
    with database() as db:
        results = db.scalars(
            select(CompetitionResult).where(CompetitionResult.competition_id == id)
        ).all()
        assert sorted((row.rank, row.team_count) for row in results) == [(1, 2), (2, 2)]
        finalized = db.get(Competition, id).finalized_at
    assert finalized
    member.get(base + "/leaderboard?board=private")
    member.get(base)
    with database() as db:
        assert db.get(Competition, id).finalized_at == finalized
    assert audit_actions(id).count("competition.finalize") == 1


def test_daily_limit_is_shared_by_team_and_skips_rejected_uploads(member):
    id = create(member)
    base = f"/api/competitions/{id}"
    assert settings(member, id, max_daily_submissions=2).status_code == 200
    valid = dict(a=1, b=2, c=3, d=4)
    account(member, "alice")
    member.post(base + "/join", json=ACCEPT)
    team = member.post(base + "/team", json={"name": "Pair"}).json()
    account(member, "bob")
    member.post(base + "/join", json=ACCEPT)
    member.post(base + "/team/join", json={"invite_code": team["invite_code"]})
    rejected = member.post(base + "/submissions", files=predictions(a=1))
    assert rejected.status_code == 422 and "missing" in rejected.json()["detail"]
    assert member.get(base + "/membership").json()["remaining_submissions_today"] == 2
    assert (
        member.post(base + "/submissions", files=predictions(**valid)).status_code
        == 201
    )

    account(member, "alice")
    assert (
        member.post(base + "/submissions", files=predictions(**valid)).status_code
        == 201
    )
    state = member.get(base + "/membership").json()
    assert (state["submissions_today"], state["remaining_submissions_today"]) == (2, 0)
    limited = member.post(base + "/submissions", files=predictions(**valid))
    assert limited.status_code == 429 and "team" in limited.json()["detail"]
    with database() as db:
        for row in db.scalars(
            select(Submission).where(Submission.competition_id == id)
        ):
            row.created_at = (
                datetime.now(timezone.utc) - timedelta(days=1)
            ).isoformat()
        db.commit()
    assert (
        member.post(base + "/submissions", files=predictions(**valid)).status_code
        == 201
    )

    account(member, "carol")
    member.post(base + "/join", json=ACCEPT)
    with database() as db:
        for _ in range(2):
            db.add(
                NotebookCommit(
                    notebook_id=1,
                    competition_id=id,
                    owner_id=user_id("carol"),
                    document="{}",
                    output_filename="p.csv",
                    status="queued",
                )
            )
        db.commit()
    assert (
        member.post(base + "/submissions", files=predictions(**valid)).status_code
        == 429
    )


def test_host_tools_rescore_disqualify_export_and_audit(member):
    id = create(member)
    base = f"/api/competitions/{id}"
    account(member, "alice")
    member.post(base + "/join", json=ACCEPT)
    member.post(base + "/submissions", files=predictions(a=2, b=2, c=3, d=4))
    account(member, "bob")
    member.post(base + "/join", json=ACCEPT)
    member.post(base + "/submissions", files=predictions(a=1, b=2, c=3, d=5))
    for path in ("/host", "/host/submissions", "/host/leaderboard.csv"):
        assert member.get(base + path).status_code == 403
    assert member.post(base + "/host/rescore").status_code == 403
    assert member.post(base + "/host/finalize").status_code == 403

    account(member, "learner")
    with database() as db:  # A legacy row: no stored predictions to rescore.
        db.add(
            Submission(
                user_id=user_id("alice"),
                competition_id=id,
                filename="legacy.csv",
                score=9.0,
            )
        )
        db.commit()
    changed = settings(member, id, metric="RMSE")
    assert changed.status_code == 200, changed.text
    assert changed.json()["rescore"] == {"rescored": 2, "skipped": 1, "failed": 0}
    rows = member.get(base + "/host/submissions?q=ali").json()
    assert len(rows) == 2
    legacy = next(row for row in rows if row["filename"] == "legacy.csv")
    assert legacy["private_score"] is None and legacy["has_predictions"] is False
    scored = next(row for row in rows if row["filename"] == "p.csv")
    assert scored["score"] == pytest.approx(0.5**0.5) and scored["private_score"] == 0
    page = member.get(base + "/host/submissions?limit=1")
    assert page.headers["X-Total-Count"] == "3" and len(page.json()) == 1
    assert member.post(base + "/host/rescore").json() == {
        "rescored": 2,
        "skipped": 1,
        "failed": 0,
    }
    assert settings(member, id, metric="AUC").status_code == 422
    assert settings(member, id, metric="Unknown").status_code == 422

    bob = user_id("bob")
    reason = {"user_id": bob, "reason": "no"}
    assert member.post(base + "/host/disqualifications", json=reason).status_code == 422
    reason["reason"] = "Shared private answers"
    disqualified = member.post(base + "/host/disqualifications", json=reason)
    assert disqualified.status_code == 201
    assert member.post(base + "/host/disqualifications", json=reason).status_code == 409
    public = member.get(base + "/leaderboard")
    assert [row["username"] for row in public.json()] == ["alice"]
    assert public.headers["X-Total-Count"] == "1"
    private = member.get(base + "/leaderboard?board=private").json()
    assert [row["username"] for row in private] == ["alice"]
    exported = member.get(base + "/host/leaderboard.csv?board=private").text
    assert (
        exported.splitlines()[0]
        == "rank,participant,team_id,score,entries,public_rank,medal"
    )
    assert "alice" in exported and "bob" not in exported
    assert member.get(base + "/host/disqualifications").json()[0]["name"] == "bob"
    assert (
        member.delete(
            f"{base}/host/disqualifications/{disqualified.json()['id']}"
        ).status_code
        == 204
    )
    assert len(member.get(base + "/leaderboard").json()) == 2

    replaced = member.put(
        base + "/host/solution",
        files={"solution_file": ("a.csv", "id,prediction\na,2\nb,2\nc,3\nd,4\n")},
        data={"public_fraction": "0.5"},
    )
    assert replaced.status_code == 200, replaced.text
    assert (replaced.json()["public_rows"], replaced.json()["private_rows"]) == (2, 2)
    wrong_ids = member.put(
        base + "/host/solution",
        files={"solution_file": ("a.csv", "id,prediction\na,2\n")},
    )
    assert wrong_ids.status_code == 422
    assert {
        "competition.settings",
        "competition.rescore",
        "competition.disqualify",
        "competition.reinstate",
        "competition.solution",
    } <= set(audit_actions(id))


def test_medal_thresholds():
    assert medal_cutoffs(5) == (0, 1, 2)
    assert medal_cutoffs(10) == (1, 2, 4)
    assert medal_cutoffs(99) == (9, 19, 39)
    assert medal_cutoffs(100) == (10, 20, 40)
    assert medal_cutoffs(249) == (10, 49, 99)
    assert medal_cutoffs(250) == (10, 50, 100)
    assert medal_cutoffs(999) == (11, 50, 100)
    assert medal_cutoffs(1000) == (12, 50, 100)
    assert medal_cutoffs(3000) == (16, 150, 300)
    assert [medal_for(rank, 10) for rank in range(1, 6)] == [
        "gold",
        "silver",
        "bronze",
        "bronze",
        None,
    ]


def test_finalization_awards_team_medals_and_profile(member):
    id = create(member)
    base = f"/api/competitions/{id}"
    account(member, "captain")
    member.post(base + "/join", json=ACCEPT)
    team = member.post(base + "/team", json={"name": "Podium"}).json()
    account(member, "mate")
    member.post(base + "/join", json=ACCEPT)
    member.post(base + "/team/join", json={"invite_code": team["invite_code"]})
    member.post(base + "/submissions", files=predictions(a=1, b=2, c=3, d=4))
    for index in range(1, 6):
        account(member, f"solo{index}")
        member.post(base + "/join", json=ACCEPT)
        member.post(
            base + "/submissions", files=predictions(a=1, b=2, c=3 + index, d=4)
        )

    account(member, "learner")
    member.post(
        base + "/host/disqualifications",
        json={"user_id": user_id("solo1"), "reason": "Duplicate account"},
    )
    assert member.post(base + "/host/finalize").status_code == 409
    shift(id, deadline=-1)
    summary = member.post(base + "/host/finalize").json()
    # Five ranked teams: no gold (10%), one silver (20%), two bronze places (40%).
    assert summary["teams"] == 5
    assert summary["medals"] == {"gold": 0, "silver": 1, "bronze": 1}
    again = member.post(base + "/host/finalize").json()
    assert (again["teams"], again["medals"]) == (summary["teams"], summary["medals"])
    with database() as db:
        results = {
            db.get(User, row.user_id).username: (row.rank, row.medal, row.team_count)
            for row in db.scalars(
                select(CompetitionResult).where(CompetitionResult.competition_id == id)
            )
        }
    assert results == {
        "captain": (1, "silver", 5),
        "mate": (1, "silver", 5),
        "solo2": (2, "bronze", 5),
        "solo3": (3, None, 5),
        "solo4": (4, None, 5),
        "solo5": (5, None, 5),
    }

    member.post("/api/auth/logout")
    board = member.get(base + "/leaderboard?board=private").json()
    assert (board[0]["team_id"], board[0]["medal"]) == (team["id"], "silver")
    assert "solo1" not in [row["username"] for row in board]
    profile = member.get("/api/profiles/mate/competitions").json()
    assert [
        (row["competition_id"], row["rank"], row["medal"], row["team_count"])
        for row in profile
    ] == [(id, 1, "silver", 5)]
    assert profile[0]["team_name"] == "Podium"
    assert member.get("/api/profiles/solo1/competitions").json() == []

    account(member, "learner")
    benchmark = publish(member, "benchmarks").json()["id"]
    assert member.post(f"/api/benchmarks/{benchmark}/host/finalize").status_code == 404
    assert (
        member.post(f"/api/competitions/{benchmark}/host/finalize").status_code == 409
    )


@pytest.fixture
def commit_db(monkeypatch):
    with database() as db:
        factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(notebook_commits, "SessionLocal", factory)
    return factory


def test_notebook_commits_share_limits_and_score_private_rows(member, commit_db):
    with commit_db() as db:
        competition = db.get(Competition, 1)
        competition.solution_usage = json.dumps(
            {"7": "Public", "8": "Public", "9": "Private"}
        )
        competition.max_daily_submissions = 1
        db.commit()
    fork = member.post("/api/code/1/fork?competition_id=1").json()["id"]
    member.post("/api/competitions/1/join", json=ACCEPT)
    queued = member.post(f"/api/code/{fork}/commits", json={"competition_id": 1})
    assert queued.status_code == 202, queued.text
    answers = {"file": ("p.csv", "id,prediction\n7,240\n8,100\n9,300\n")}
    assert (
        member.post("/api/competitions/1/submissions", files=answers).status_code == 429
    )
    with commit_db() as db:
        job = db.get(NotebookCommit, queued.json()["id"])
        job.status = "running"
        document = json.loads(job.document)
        db.commit()
    notebook_commits.complete_commit(
        queued.json()["id"], document, b"id,prediction\n7,240\n8,100\n9,310\n"
    )
    latest = member.get(f"/api/code/{fork}/commits/latest").json()
    assert latest["status"] == "succeeded" and latest["score"] == 0
    assert "private" not in json.dumps(latest)
    with commit_db() as db:
        submission = db.scalar(select(Submission).where(Submission.competition_id == 1))
        assert (submission.score, submission.private_score) == (0.0, 10.0)
        assert db.get(SubmissionPrediction, submission.id) is not None
    history = member.get("/api/competitions/1/submissions").json()
    assert history[0]["score"] == 0 and "private_score" not in history[0]
    assert (
        member.post("/api/competitions/1/submissions", files=answers).status_code == 429
    )


def test_creation_uses_metric_registry_and_split_options(member):
    metrics = {row["name"]: row for row in member.get("/api/metrics").json()}
    assert len(metrics) == 13 and metrics["AUC"]["direction"] == "higher"
    id = create(member, "id,prediction\nq1,cat dog\nq2,fish\n", "MAP@K", metric_k="2")
    base = f"/api/competitions/{id}"
    detail = member.get(base).json()
    assert (detail["metric_label"], detail["metric_direction"]) == ("MAP@2", "higher")
    assert (detail["leaderboard_split"], detail["max_daily_submissions"]) == (False, 5)
    assert detail["max_final_submissions"] == 2
    member.post(base + "/join", json=ACCEPT)
    scored = member.post(
        base + "/submissions", files=predictions(q1="dog cat", q2="bird fish")
    )
    # q1: (1/1 + 2/2) / 2 = 1; q2: (1/2) / 1 = 0.5.
    assert scored.json()["score"] == pytest.approx(0.75)

    rows = "id,prediction\n" + "".join(f"r{n},{n % 2}\n" for n in range(10))
    split_id = create(
        member, rows, "F1", public_fraction="0.3", max_daily_submissions="7"
    )
    detail = member.get(f"/api/competitions/{split_id}").json()
    assert detail["leaderboard_split"] is True and detail["max_daily_submissions"] == 7
    state = member.get(f"/api/competitions/{split_id}/host").json()
    assert (state["public_rows"], state["private_rows"]) == (3, 7)

    assert (
        post_competition(member, "id,prediction\nx,1\ny,1\n", "AUC").status_code == 422
    )
    assert post_competition(member, metric="Bogus").status_code == 422
    assert post_competition(member, "id,prediction\nx,0.5\n", "F1").status_code == 422
    assert publish(member, "benchmarks").json()["max_daily_submissions"] == 20
