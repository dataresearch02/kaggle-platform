import pytest


@pytest.mark.parametrize(
    "kind", ["notebook-comment", "discussion-comment", "discussion", "competition-post"]
)
def test_replies_and_reactions_are_persistent_scoped_and_owned(member, kind):
    if kind == "notebook-comment":
        notebook = member.post(
            "/api/notebooks", json={"title": "Threaded code", "code": "print(1)"}
        ).json()
        from test_code_pages import document

        assert (
            member.put(
                f"/api/code/{notebook['id']}/publication", json=document()
            ).status_code
            == 200
        )
        target = member.post(
            f"/api/code/{notebook['id']}/comments", json={"body": "Original comment"}
        ).json()
    elif kind == "competition-post":
        member.post("/api/competitions/1/join")
        target = member.post(
            "/api/competitions/1/discussion",
            json={"title": "Threaded post", "body": "Original post"},
        ).json()
    else:
        target = member.post(
            "/api/discussions",
            json={"title": "Threaded discussion", "body": "Original post"},
        ).json()
        if kind == "discussion-comment":
            target = member.post(
                f"/api/discussions/{target['id']}/comments",
                json={"body": "Original comment"},
            ).json()
    path = f"/api/engagement/{kind}/{target['id']}"
    assert member.get(path).status_code == 200
    assert member.post(path + "/replies", json={"body": "  "}).status_code == 422
    reply = member.post(path + "/replies", json={"body": "A helpful reply"})
    assert reply.status_code == 201, reply.text
    reply_id = reply.json()["id"]
    assert member.get(path).json()["replies"][0]["body"] == "A helpful reply"
    for _ in range(2):
        reaction = member.put(path + "/reactions/like")
        assert reaction.status_code == 200
        assert reaction.json()[0] == {"reaction": "like", "count": 1, "reacted": True}
    assert member.delete(path + "/reactions/like").json()[0]["count"] == 0
    member.put(path + "/reactions/helpful")
    member.post("/api/auth/logout")
    assert member.get(path).json()["reactions"][1] == {
        "reaction": "helpful",
        "count": 1,
        "reacted": False,
    }
    assert member.post(path + "/replies", json={"body": "Anonymous"}).status_code == 401
    assert member.put(path + "/reactions/like").status_code == 401
    member.post(
        "/api/auth/register",
        json={"username": "other_replier", "password": "other-password-123"},
    )
    assert member.delete(path + f"/replies/{reply_id}").status_code == 403
    own = member.post(path + "/replies", json={"body": "Own reply"}).json()
    assert member.delete(path + f"/replies/{own['id']}").status_code == 204
    assert len(member.get(path).json()["replies"]) == 1
    assert member.get(f"/api/engagement/{kind}/999999").status_code == 404
    assert member.put(path + "/reactions/unknown").status_code == 422
