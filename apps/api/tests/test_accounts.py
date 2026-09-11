import hashlib
import time
from sqlalchemy import select
from app.main import app
from app.db import get_db
from app.models import ApiToken, ServiceNotice


def login(client, username="learner", password="good-password-123"):
    client.post("/api/auth/logout")
    assert (
        client.post(
            "/api/auth/login", json={"username": username, "password": password}
        ).status_code
        == 200
    )


def test_profile_photo_privacy_and_persistence(member):
    assert member.get("/api/account/profile").json()["username"] == "learner"
    details = {
        "display_name": "Ada Researcher",
        "bio": "Building notebooks",
        "tagline": "Data science",
        "website": "https://example.org",
    }
    assert member.put("/api/account/profile", json=details).status_code == 200
    assert member.get("/api/account/profile").json()["display_name"] == "Ada Researcher"
    assert (
        member.put(
            "/api/account/avatar", files={"file": ("x.svg", b"<svg/>", "image/svg+xml")}
        ).status_code
        == 422
    )
    assert (
        member.put(
            "/api/account/avatar",
            files={"file": ("x.png", b"x" * (2 * 1024 * 1024 + 1))},
        ).status_code
        == 413
    )
    import base64

    photo = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6p1sAAAAASUVORK5CYII="
    )
    assert (
        member.put("/api/account/avatar", files={"file": ("x.png", photo)}).status_code
        == 200
    )
    member.post("/api/auth/logout")
    assert member.get("/api/profiles/learner").json()["bio"] == "Building notebooks"
    assert member.get("/api/profiles/learner/avatar").content == photo
    assert member.put("/api/account/profile", json=details).status_code == 401
    login(member)
    assert (
        member.put("/api/account/settings", json={"visibility": "private"}).status_code
        == 200
    )
    member.post("/api/auth/logout")
    assert member.get("/api/profiles/learner").status_code == 404
    assert member.get("/api/profiles/learner/avatar").status_code == 404
    login(member)
    assert member.get("/api/profiles/learner/avatar").content == photo
    assert member.delete("/api/account/avatar").status_code == 204
    assert member.get("/api/profiles/learner/avatar").status_code == 404


def test_tokens_hash_scopes_expiry_revocation_and_browser_only_management(member):
    readonly = member.post("/api/account/tokens", json={"name": "Reader"}).json()
    secret = readonly["token"]
    with next(app.dependency_overrides[get_db]()) as db:
        record = db.get(ApiToken, readonly["id"])
        assert record.token_hash == hashlib.sha256(secret.encode()).hexdigest()
        assert secret not in repr(record.__dict__)
    assert secret not in member.get("/api/account/tokens").text
    headers = {"Authorization": f"Bearer {secret}"}
    assert member.get("/api/work", headers=headers).status_code == 200
    assert (
        member.post(
            "/api/notebooks",
            headers=headers,
            json={"title": "CLI notebook", "code": "print(1)"},
        ).status_code
        == 403
    )
    assert member.get("/api/account/tokens", headers=headers).status_code == 403
    writer = member.post(
        "/api/account/tokens", json={"name": "CLI", "scope": "read-write", "days": 7}
    ).json()
    write_headers = {"Authorization": f"Bearer {writer['token']}"}
    member.headers.pop("X-Arena-Client")
    assert (
        member.post(
            "/api/notebooks",
            headers=write_headers,
            json={"title": "CLI notebook", "code": "print(1)"},
        ).status_code
        == 201
    )
    assert (
        member.post(
            "/api/account/tokens", headers=write_headers, json={"name": "escalate"}
        ).status_code
        == 403
    )
    member.headers["X-Arena-Client"] = "web"
    assert member.get("/api/account/tokens").json()[0]["last_used_at"]
    assert member.delete(f"/api/account/tokens/{writer['id']}").status_code == 204
    assert member.get("/api/work", headers=write_headers).status_code == 401
    with next(app.dependency_overrides[get_db]()) as db:
        db.get(ApiToken, readonly["id"]).expires_at = time.time() - 1
        db.commit()
    assert member.get("/api/work", headers=headers).status_code == 401


def test_group_permissions_invites_and_membership(member):
    group = member.post(
        "/api/account/groups",
        json={"name": "Research group", "description": "Experiments"},
    ).json()
    row = member.get("/api/account/groups").json()[0]
    owner_id = member.get("/api/auth/me").json()["id"]
    old_code = row["invite_code"]
    new_code = member.post(f"/api/account/groups/{group['id']}/invite").json()[
        "invite_code"
    ]
    member.post("/api/auth/logout")
    member.post(
        "/api/auth/register",
        json={"username": "colleague", "password": "good-password-123"},
    )
    other_id = member.get("/api/auth/me").json()["id"]
    assert member.get("/api/account/groups").json() == []
    assert (
        member.post("/api/account/groups/join", json={"code": old_code}).status_code
        == 404
    )
    assert (
        member.post("/api/account/groups/join", json={"code": new_code}).status_code
        == 200
    )
    assert (
        member.post("/api/account/groups/join", json={"code": new_code}).status_code
        == 200
    )
    assert len(member.get("/api/account/groups").json()[0]["members"]) == 2
    assert member.get("/api/account/groups").json()[0]["invite_code"] is None
    base = f"/api/account/groups/{group['id']}"
    assert member.put(base, json={"name": "Hijacked group"}).status_code == 404
    assert member.delete(base).status_code == 404
    assert member.delete(base + f"/members/{owner_id}").status_code == 404
    login(member)
    assert member.put(base, json={"name": "New research name"}).status_code == 200
    assert member.delete(base + f"/members/{owner_id}").status_code == 409
    assert member.delete(base + f"/members/{other_id}").status_code == 204
    login(member, "colleague")
    assert member.get("/api/account/groups").json() == []
    member.post("/api/account/groups/join", json={"code": new_code})
    assert member.delete(base + f"/members/{other_id}").status_code == 204
    login(member)
    assert member.delete(base).status_code == 204
    assert member.get("/api/account/groups").json() == []


def test_password_rotation_revokes_other_sessions_and_tokens(member):
    old_cookie = member.cookies.get("arena_session")
    token = member.post("/api/account/tokens", json={"name": "Old credential"}).json()[
        "token"
    ]
    assert (
        member.put(
            "/api/account/password",
            json={"current_password": "wrong", "new_password": "new-password-123"},
        ).status_code
        == 403
    )
    assert (
        member.put(
            "/api/account/password",
            json={
                "current_password": "good-password-123",
                "new_password": "new-password-123",
            },
        ).status_code
        == 200
    )
    assert member.get("/api/auth/me").status_code == 200
    assert member.get("/api/account/tokens").json() == []
    assert (
        member.get(
            "/api/work", headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 401
    )
    member.cookies.clear()
    member.cookies.set("arena_session", old_cookie)
    assert member.get("/api/auth/me").status_code == 401
    login(member, password="new-password-123")


def test_service_notifications_targeting_and_read_state(member):
    welcome = member.get("/api/account/notifications").json()[0]
    assert welcome["title"] == "Welcome to Arena"
    assert not welcome["read"]
    assert (
        member.post(f"/api/account/notifications/{welcome['id']}/read").status_code
        == 204
    )
    assert (
        member.post(f"/api/account/notifications/{welcome['id']}/read").status_code
        == 204
    )
    assert member.get("/api/account/notifications").json()[0]["read"]
    with next(app.dependency_overrides[get_db]()) as db:
        db.add(ServiceNotice(title="Maintenance", body="Service announcement"))
        db.commit()
    member.post("/api/auth/logout")
    member.post(
        "/api/auth/register",
        json={"username": "second", "password": "good-password-123"},
    )
    notices = member.get("/api/account/notifications").json()
    assert any(row["title"] == "Maintenance" for row in notices)
    assert welcome["id"] not in [row["id"] for row in notices]
    assert (
        member.post(f"/api/account/notifications/{welcome['id']}/read").status_code
        == 404
    )
