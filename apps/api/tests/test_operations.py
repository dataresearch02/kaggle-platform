import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import admin_cli
from app.admin import bootstrap_admins
from app.auth import SUSPENDED
from app.db import get_db
from app.main import app
from app.models import AuditLog, Competition, SiteSetting, User

PASSWORD = "good-password-123"


def database():
    return next(app.dependency_overrides[get_db]())


def browser():
    return TestClient(app, headers={"X-Arena-Client": "web"})


def account(username, role=None):
    """A separate signed-in client; optionally with a role set directly."""
    client = browser()
    response = client.post(
        "/api/auth/register", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 201, response.text
    if role:
        with database() as db:
            db.scalar(select(User).where(User.username == username)).role = role
            db.commit()
    return client


def user_id(username):
    with database() as db:
        return db.scalar(select(User.id).where(User.username == username))


def actions(**filters):
    with database() as db:
        query = select(AuditLog).order_by(AuditLog.id)
        return [
            row
            for row in db.scalars(query)
            if all(getattr(row, key) == value for key, value in filters.items())
        ]


def public_dataset(client, title="Shared measurements"):
    row = client.post(
        "/api/datasets",
        data={"title": title, "description": "Community data"},
        files={"file": ("data.csv", b"id,value\n1,2\n")},
    ).json()
    assert (
        client.put(
            f"/api/datasets/{row['id']}/access", json={"visibility": "public"}
        ).status_code
        == 200
    )
    return row["id"]


def test_bootstrap_admins_and_cli(member):
    with database() as db:
        assert bootstrap_admins(db, "Learner, missing ,") == ["learner"]
        assert bootstrap_admins(db, "learner") == []
    me = member.get("/api/auth/me").json()
    assert me["role"] == "admin" and me["can_create_competitions"] is True
    [entry] = actions(action="user.role")
    assert entry.actor_id is None
    assert json.loads(entry.detail)["source"] == "ARENA_ADMIN_USERNAMES"

    account("student")
    with database() as db:
        assert admin_cli.apply(db, "promote", "student", "host").endswith(
            "user -> host"
        )
        assert "active -> suspended" in admin_cli.apply(db, "suspend", "student")
    login = browser().post(
        "/api/auth/login", json={"username": "student", "password": PASSWORD}
    )
    assert login.status_code == 403 and login.json()["detail"] == SUSPENDED
    with database() as db:
        admin_cli.apply(db, "activate", "student")
        admin_cli.apply(db, "demote", "student")
        assert db.scalar(select(User.role).where(User.username == "student")) == "user"
    assert (
        browser()
        .post("/api/auth/login", json={"username": "student", "password": PASSWORD})
        .status_code
        == 200
    )
    assert len(actions(action="user.status")) == 2


def test_suspension_rejects_sessions_tokens_and_login(member):
    admin = account("chief", role="admin")
    token = member.post("/api/account/tokens", json={"name": "cli"}).json()["token"]
    learner = user_id("learner")
    assert member.get("/api/admin/users").status_code == 403
    assert browser().get("/api/admin/users").status_code == 401

    response = admin.put(f"/api/admin/users/{learner}", json={"status": "suspended"})
    assert response.status_code == 200 and response.json()["status"] == "suspended"
    assert member.get("/api/auth/me").json()["detail"] == SUSPENDED
    bearer = browser().get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert bearer.status_code == 403 and bearer.json()["detail"] == SUSPENDED
    # Public pages still work, as for an anonymous visitor.
    assert member.get("/api/datasets").status_code == 200
    relogin = browser().post(
        "/api/auth/login", json={"username": "learner", "password": PASSWORD}
    )
    assert relogin.status_code == 403

    chief = user_id("chief")
    assert (
        admin.put(f"/api/admin/users/{chief}", json={"role": "user"}).status_code == 409
    )
    assert (
        admin.put(f"/api/admin/users/{learner}", json={"status": "active"}).status_code
        == 200
    )
    assert member.get("/api/auth/me").status_code == 200
    assert [row.action for row in actions(actor_id=chief)] == [
        "user.status",
        "user.status",
    ]


def test_admin_user_search_password_reset_and_session_revocation(member):
    admin = account("chief", role="admin")
    account("helper", role="host")
    token = member.post("/api/account/tokens", json={"name": "cli"}).json()["token"]
    page = admin.get("/api/admin/users?limit=2")
    assert page.headers["X-Total-Count"] == "4"  # Includes the internal seed user.
    assert len(page.json()) == 2
    assert [
        row["username"] for row in admin.get("/api/admin/users?role=host").json()
    ] == ["helper"]
    [found] = admin.get("/api/admin/users?q=learn").json()
    assert found["active_sessions"] == 1 and found["api_tokens"] == 1

    reset = admin.post(f"/api/admin/users/{found['id']}/password-reset")
    assert reset.status_code == 200
    assert reset.headers["Cache-Control"] == "no-store"
    temporary = reset.json()["temporary_password"]
    assert len(temporary) >= 20
    assert reset.json()["sessions_revoked"] == 1 and reset.json()["tokens_revoked"] == 1
    assert member.get("/api/auth/me").status_code == 401
    assert (
        browser()
        .get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        .status_code
        == 401
    )
    assert (
        member.post(
            "/api/auth/login", json={"username": "learner", "password": PASSWORD}
        ).status_code
        == 401
    )
    assert (
        member.post(
            "/api/auth/login", json={"username": "learner", "password": temporary}
        ).status_code
        == 200
    )
    revoked = admin.post(f"/api/admin/users/{found['id']}/revoke-sessions")
    assert revoked.json() == {"sessions_revoked": 1}
    assert member.get("/api/auth/me").status_code == 401
    audit = admin.get("/api/admin/audit?action=user.").json()
    assert [row["action"] for row in audit] == [
        "user.sessions_revoked",
        "user.password_reset",
    ]
    assert temporary not in json.dumps(audit)
    assert (
        admin.get("/api/admin/audit?actor=chief&limit=1").headers["X-Total-Count"]
        == "2"
    )
    chief = user_id("chief")
    assert admin.post(f"/api/admin/users/{chief}/password-reset").status_code == 409


def test_site_settings_control_registration_login_and_creation(member):
    assert browser().get("/api/site").json() == {
        "registration_open": True,
        "local_login_enabled": True,
        "announcement": "",
    }
    admin = account("chief", role="admin")
    assert (
        member.put("/api/admin/settings", json={"announcement": "x"}).status_code == 403
    )
    with database() as db:
        db.delete(db.get(SiteSetting, "competition_creation"))
        db.commit()
    assert admin.get("/api/admin/settings").json()["competition_creation"] == "hosts"
    response = admin.put(
        "/api/admin/settings",
        json={
            "registration_open": False,
            "local_login_enabled": False,
            "announcement": "  **Maintenance** on Friday  ",
        },
    )
    assert response.status_code == 200
    assert browser().get("/api/site").json() == {
        "registration_open": False,
        "local_login_enabled": False,
        "announcement": "**Maintenance** on Friday",
    }
    closed = browser().post(
        "/api/auth/register", json={"username": "latecomer", "password": PASSWORD}
    )
    assert closed.status_code == 403
    assert (
        browser()
        .post("/api/auth/login", json={"username": "learner", "password": PASSWORD})
        .status_code
        == 403
    )
    assert (
        browser()
        .post("/api/auth/login", json={"username": "chief", "password": PASSWORD})
        .status_code
        == 200
    )
    [entry] = actions(action="settings.update")
    assert set(json.loads(entry.detail)["changes"]) == {
        "registration_open",
        "local_login_enabled",
        "announcement",
    }

    def create(client):
        return client.post(
            "/api/competitions",
            data={
                "title": "Hosted challenge",
                "description": "Predict values",
                "deadline": "2099-01-01T00:00:00+00:00",
            },
            files={
                "test_file": ("test.csv", b"id,x\n1,2\n"),
                "solution_file": ("answers.csv", b"id,prediction\n1,3\n"),
            },
        )

    assert member.get("/api/auth/me").json()["can_create_competitions"] is False
    signed_in = browser().post(
        "/api/auth/login", json={"username": "chief", "password": PASSWORD}
    )
    assert signed_in.json()["can_create_competitions"] is True
    assert create(member).status_code == 403
    with database() as db:
        db.scalar(select(User).where(User.username == "learner")).role = "host"
        db.commit()
    created = create(member)
    assert created.status_code == 201
    [entry] = actions(action="competition.create")
    assert entry.target_id == str(created.json()["id"])
    assert (
        admin.put(
            "/api/admin/settings", json={"competition_creation": "everyone"}
        ).json()["competition_creation"]
        == "everyone"
    )
    assert (
        admin.put(
            "/api/admin/settings", json={"competition_creation": "all"}
        ).status_code
        == 422
    )


def test_reports_hide_resolve_and_delete_dataset(member):
    admin = account("chief", role="admin")
    critic = account("critic")
    dataset = public_dataset(member)
    report = {"kind": "dataset", "id": dataset, "reason": "Contains personal data"}
    assert member.post("/api/reports", json=report).status_code == 422
    first = critic.post("/api/reports", json=report)
    assert first.status_code == 201
    assert critic.post("/api/reports", json=report).status_code == 409
    assert critic.post("/api/reports", json={**report, "id": 9999}).status_code == 404

    [queued] = admin.get("/api/admin/reports").json()
    assert queued["reporter"] == "critic"
    assert queued["target"]["link"] == f"#datasets/{dataset}"
    assert queued["target"]["owner"] == "learner"

    hide = admin.put(
        f"/api/admin/moderation/dataset/{dataset}",
        json={"hidden": True, "reason": "Under review"},
    )
    assert hide.status_code == 200 and hide.json()["hidden"] is True
    assert (
        admin.put(
            f"/api/admin/moderation/dataset/{dataset}", json={"hidden": True}
        ).status_code
        == 422
    )
    for client in (critic, browser()):
        assert dataset not in [row["id"] for row in client.get("/api/datasets").json()]
        assert client.get(f"/api/datasets/{dataset}").status_code == 404
        assert client.get(f"/api/datasets/{dataset}/download").status_code == 404
    own = member.get(f"/api/datasets/{dataset}").json()
    assert own["hidden"] == 1 and own["hidden_reason"] == "Under review"
    assert admin.get(f"/api/datasets/{dataset}").status_code == 200
    [listed] = admin.get("/api/admin/hidden").json()
    assert (listed["kind"], listed["id"]) == ("dataset", dataset)

    admin.put(f"/api/admin/moderation/dataset/{dataset}", json={"hidden": False})
    assert critic.get(f"/api/datasets/{dataset}").status_code == 200
    resolved = admin.post(
        f"/api/admin/reports/{first.json()['id']}/resolve", json={"note": "Checked"}
    )
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["resolved_by"] == "chief"
    assert (
        admin.post(
            f"/api/admin/reports/{first.json()['id']}/resolve", json={}
        ).status_code
        == 409
    )
    assert critic.post("/api/reports", json=report).status_code == 201
    assert admin.get("/api/admin/reports?status=all").headers["X-Total-Count"] == "2"

    assert critic.delete(f"/api/admin/moderation/dataset/{dataset}").status_code == 403
    assert admin.delete(f"/api/admin/moderation/dataset/{dataset}").status_code == 204
    assert member.get(f"/api/datasets/{dataset}").status_code == 404
    assert admin.get("/api/admin/reports").json() == []
    assert [row.action for row in actions(target_kind="dataset")] == [
        "content.hide",
        "content.unhide",
        "report.resolve",
        "content.delete",
    ]


def test_discussion_code_comment_and_profile_moderation(member):
    admin = account("chief", role="admin")
    critic = account("critic")
    post = member.post(
        "/api/competitions/1/discussion",
        json={"title": "Feature ideas", "body": "Try temperature bins"},
    ).json()
    comment = member.post(
        f"/api/competition-discussions/{post['id']}/comments", json={"body": "Spam"}
    ).json()
    note = member.post("/api/code/1/comments", json={"body": "Rude note"}).json()
    for kind, id in [
        ("competition-post", post["id"]),
        ("reply", comment["id"]),
        ("code", 1),
        ("notebook-comment", note["id"]),
        ("profile", user_id("learner")),
    ]:
        response = critic.post(
            "/api/reports", json={"kind": kind, "id": id, "reason": "Needs review"}
        )
        assert response.status_code == 201, (kind, response.text)
    links = {
        row["kind"]: row["target"]["link"]
        for row in admin.get("/api/admin/reports").json()
    }
    assert links["reply"] == f"#competitions/1/discussion/{post['id']}"
    assert links["notebook-comment"] == "#code/1"
    assert links["profile"] == "#profile/learner"

    def hide(kind, id):
        response = admin.put(
            f"/api/admin/moderation/{kind}/{id}",
            json={"hidden": True, "reason": "Off topic"},
        )
        assert response.status_code == 200, response.text

    hide("reply", comment["id"])
    thread = f"/api/competition-discussions/{post['id']}/comments"
    assert critic.get(thread).json()["items"] == []
    [own] = member.get(thread).json()["items"]
    assert own["hidden"] is True and own["hidden_reason"] == "Off topic"
    assert len(admin.get(thread).json()["items"]) == 1

    hide("competition-post", post["id"])
    feed = "/api/competition-discussions?competition_id=1"
    assert critic.get(feed).json()["items"] == []
    assert critic.get(feed).headers["X-Total-Count"] == "0"
    assert critic.get(f"/api/competition-discussions/{post['id']}").status_code == 404
    assert critic.get("/api/competitions/1/discussion").json() == []
    assert member.get(f"/api/competition-discussions/{post['id']}").json()["hidden"]
    assert len(admin.get(feed).json()["items"]) == 1

    hide("notebook-comment", note["id"])
    assert critic.get("/api/code/1/comments").json()["items"] == []
    hide("code", 1)
    assert critic.get("/api/code/1").status_code == 404
    assert 1 not in [row["id"] for row in critic.get("/api/code").json()["items"]]
    assert 1 not in [row["id"] for row in critic.get("/api/notebooks").json()]
    assert admin.get("/api/code/1").json()["hidden"] is True

    hide("profile", user_id("learner"))
    assert critic.get("/api/profiles/learner").status_code == 404
    assert member.get("/api/profiles/learner").json()["hidden"] is True
    assert admin.get("/api/profiles/learner").status_code == 200
    assert admin.get("/api/admin/hidden").headers["X-Total-Count"] == "5"
    assert len(admin.get("/api/admin/hidden?kind=reply").json()) == 1

    assert (
        admin.delete(f"/api/admin/moderation/reply/{comment['id']}").status_code == 204
    )
    assert admin.get(thread).json()["items"] == []
    assert (
        admin.delete(f"/api/admin/moderation/competition-post/{post['id']}").status_code
        == 204
    )
    assert admin.get(f"/api/competition-discussions/{post['id']}").status_code == 404
    assert (
        admin.delete(f"/api/admin/moderation/notebook-comment/{note['id']}").status_code
        == 204
    )
    assert (
        admin.delete(f"/api/admin/moderation/profile/{user_id('learner')}").status_code
        == 204
    )
    assert admin.delete("/api/admin/moderation/reply/999").status_code == 404
    assert (
        admin.get("/api/admin/audit?action=content.delete").headers["X-Total-Count"]
        == "4"
    )


def test_admins_manage_other_users_content(member):
    admin = account("chief", role="admin")
    dataset = member.post(
        "/api/datasets",
        data={"title": "Private work", "description": "Owner data"},
        files={"file": ("data.csv", b"id,value\n1,2\n")},
    ).json()["id"]
    updated = admin.patch(
        f"/api/work/datasets/{dataset}",
        json={"title": "Renamed by moderator", "description": "Cleaned"},
    )
    assert updated.status_code == 200
    assert [row.action for row in actions(target_kind="dataset")] == ["content.update"]
    assert (
        account("other")
        .patch(
            f"/api/work/datasets/{dataset}", json={"title": "Nope", "description": ""}
        )
        .status_code
        == 404
    )
    competition = member.post(
        "/api/competitions",
        data={
            "title": "Learner challenge",
            "description": "Predict values",
            "deadline": "2099-01-01T00:00:00+00:00",
        },
        files={
            "test_file": ("test.csv", b"id,x\n1,2\n"),
            "solution_file": ("answers.csv", b"id,prediction\n1,3\n"),
        },
    ).json()["id"]
    assert admin.delete(f"/api/work/competitions/{competition}").status_code == 204
    assert member.get(f"/api/competitions/{competition}").status_code == 404
    [entry] = actions(action="competition.delete")
    assert entry.target_id == str(competition)
    # Legacy competitions without creator details are manageable by admins only.
    assert member.delete("/api/work/competitions/1").status_code == 404


def test_pagination_headers_and_limits(member):
    courses = member.get("/api/courses?limit=2")
    assert courses.headers["X-Total-Count"] == "3" and len(courses.json()) == 2
    assert len(member.get("/api/courses?offset=2&limit=2").json()) == 1
    assert member.get("/api/courses?limit=5000").status_code == 200
    for path in [
        "/api/competitions",
        "/api/benchmarks",
        "/api/datasets",
        "/api/models",
        "/api/notebooks",
        "/api/discussions",
        "/api/code",
        "/api/competition-discussions",
        "/api/competitions/1/discussion",
    ]:
        response = member.get(path)
        assert response.status_code == 200, path
        assert "X-Total-Count" in response.headers, path
    assert member.get("/api/datasets?offset=1&limit=1").headers["X-Total-Count"] == "3"
    assert len(member.get("/api/datasets?offset=1&limit=1").json()) == 1

    member.post("/api/competitions/1/join")
    for score in (0, 1, 2):
        member.post(
            "/api/competitions/1/submissions",
            files={"file": ("p.csv", f"id,prediction\n7,{score}\n8,0\n9,0\n".encode())},
        )
    history = member.get("/api/competitions/1/submissions?limit=2")
    assert history.headers["X-Total-Count"] == "3" and len(history.json()) == 2
    assert len(member.get("/api/competitions/1/submissions?offset=2").json()) == 1
    account("rival").post("/api/competitions/1/join")
    board = member.get("/api/competitions/1/leaderboard?limit=1")
    assert board.headers["X-Total-Count"] == "1"
    assert board.json()[0]["rank"] == 1
    assert member.get("/api/competitions/1/leaderboard?offset=1").json() == []


def test_missing_test_features_return_404_and_stats_skip_seed_user(member):
    assert member.get("/api/stats").json()["learners"] == 1
    with database() as db:
        competition = Competition(
            title="Details lost",
            description="No stored features",
            deadline="2099-01-01T00:00:00+00:00",
            solution='{"1": 1}',
        )
        db.add(competition)
        db.commit()
        id = competition.id
    assert member.post(f"/api/competitions/{id}/join").status_code == 200
    assert member.get(f"/api/competitions/{id}/test").status_code == 404
    assert member.get(f"/api/competitions/{id}/data").status_code == 404
    assert member.post("/api/competitions/1/join").status_code == 200
    assert b"temperature" in member.get("/api/competitions/1/test").content
