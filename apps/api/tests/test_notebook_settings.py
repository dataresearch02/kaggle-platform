from test_code_pages import document


def test_version_labels_sharing_and_comment_permissions(member):
    notebook = member.post(
        "/api/notebooks", json={"title": "Settings example", "code": "print(1)"}
    ).json()
    base = f"/api/code/{notebook['id']}"
    version = member.get(base + "/versions").json()[0]
    before = member.get(base + f"/versions/{version['id']}").json()
    assert (
        member.patch(
            base + f"/versions/{version['id']}",
            json={"name": "Baseline", "tags": ["cpu", "baseline"]},
        ).status_code
        == 200
    )
    after = member.get(base + f"/versions/{version['id']}").json()
    assert before["cells"] == after["cells"]
    assert member.get(base + "/versions").json()[0]["label"]["name"] == "Baseline"
    assert (
        member.patch(
            base + f"/versions/{version['id']}", json={"name": " ", "tags": []}
        ).status_code
        == 422
    )
    member.post("/api/auth/logout")
    member.post(
        "/api/auth/register",
        json={"username": "viewer", "password": "good-password-123"},
    )
    assert member.get(base + "/share-settings").status_code == 404
    member.post("/api/auth/logout")
    member.post(
        "/api/auth/login", json={"username": "learner", "password": "good-password-123"}
    )
    settings = {
        "visibility": "private",
        "usernames": ["viewer"],
        "allow_comments": True,
    }
    assert member.put(base + "/share-settings", json=settings).status_code == 200
    assert member.get(base + "/share-settings").json()["usernames"] == ["viewer"]
    assert (
        member.put(
            base + "/share-settings", json={**settings, "usernames": ["missing-user"]}
        ).status_code
        == 422
    )
    assert member.get(base + "/share-settings").json()["usernames"] == ["viewer"]
    comment = member.post(base + "/comments", json={"body": "Before disabling"}).json()
    settings["allow_comments"] = False
    assert member.put(base + "/share-settings", json=settings).status_code == 200
    assert member.post(base + "/comments", json={"body": "Blocked"}).status_code == 403
    assert (
        member.post(
            f"/api/engagement/notebook-comment/{comment['id']}/replies",
            json={"body": "Blocked reply"},
        ).status_code
        == 403
    )
    member.post("/api/auth/logout")
    member.post(
        "/api/auth/login", json={"username": "viewer", "password": "good-password-123"}
    )
    assert member.get(base).status_code == 200
    assert member.put(base + "/share-settings", json=settings).status_code == 404
    assert (
        member.patch(
            base + f"/versions/{version['id']}", json={"name": "Stolen"}
        ).status_code
        == 404
    )
    member.post("/api/auth/logout")
    member.post(
        "/api/auth/login", json={"username": "learner", "password": "good-password-123"}
    )
    assert (
        member.put(
            base + "/share-settings", json={**settings, "usernames": []}
        ).status_code
        == 200
    )
    assert (
        member.put(
            base + "/share-settings",
            json={**settings, "visibility": "public", "usernames": []},
        ).status_code
        == 200
    )
    member.post("/api/auth/logout")
    assert member.get(base).status_code == 200
    assert member.get(base).json()["allow_comments"] is False
