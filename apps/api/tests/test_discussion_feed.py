def test_feed_uses_competition_threads_and_shared_replies(member):
    post = member.post(
        "/api/competitions/1/discussion",
        json={
            "title": "Shared discussion thread",
            "body": "A question about training.",
        },
    )
    assert post.status_code == 201, post.text
    id = post.json()["id"]
    feed = member.get("/api/competition-discussions?q=Shared discussion thread").json()
    assert [row["id"] for row in feed["items"]] == [id]
    detail = member.get(f"/api/competition-discussions/{id}").json()
    assert detail["body"] == "A question about training."
    assert detail["competition_id"] == 1
    assert (
        member.post(
            f"/api/engagement/competition-post/{id}/replies",
            json={"body": "Shared reply"},
        ).status_code
        == 201
    )
    assert (
        member.get(f"/api/engagement/competition-post/{id}").json()["replies"][0][
            "body"
        ]
        == "Shared reply"
    )
    assert member.get("/api/competition-discussions/999999").status_code == 404
    assert not member.get(
        f"/api/competition-discussions?q=Shared discussion thread&before={id}"
    ).json()["items"]


def test_topics_pins_bookmarks_filters_sort_and_many_comments(member):
    from test_challenges import publish

    competition = publish(member).json()["id"]

    def create(title):
        return member.post(
            f"/api/competitions/{competition}/discussion",
            json={"title": title, "body": "Topic description"},
        ).json()["id"]

    first, second = create("Pinned older topic"), create("Newer topic")
    base = "/api/competition-discussions"
    assert member.put(f"{base}/{first}/pin", json={"enabled": True}).status_code == 200
    assert (
        member.put(f"{base}/{second}/bookmark", json={"enabled": True}).status_code
        == 200
    )
    for body in ("First comment", "Second comment"):
        assert (
            member.post(f"{base}/{second}/comments", json={"body": body}).status_code
            == 201
        )
    rows = member.get(f"{base}?competition_id={competition}&sort=newest").json()[
        "items"
    ]
    assert [row["id"] for row in rows] == [first, second]
    assert rows[0]["pinned"] and rows[1]["comment_count"] == 2
    assert [
        row["id"]
        for row in member.get(
            f"{base}?competition_id={competition}&filter=bookmarks"
        ).json()["items"]
    ] == [second]
    assert [
        row["id"]
        for row in member.get(
            f"{base}?competition_id={competition}&unanswered=true"
        ).json()["items"]
    ] == [first]
    comments = member.get(f"{base}/{second}/comments").json()
    assert [comment["body"] for comment in comments["items"]] == [
        "First comment",
        "Second comment",
    ]
    assert (
        member.get(
            f'{base}/{second}/comments?after={comments["items"][0]["id"]}'
        ).json()["items"][0]["body"]
        == "Second comment"
    )
    member.put(f"{base}/{first}/pin", json={"enabled": False})
    assert (
        member.get(f"{base}?competition_id={competition}&sort=comments").json()[
            "items"
        ][0]["id"]
        == second
    )
    member.post("/api/auth/logout")
    member.post(
        "/api/auth/register",
        json={"username": "other_reader", "password": "good-password-123"},
    )
    assert member.put(f"{base}/{first}/pin", json={"enabled": True}).status_code == 403
    assert (
        member.get(f"{base}?competition_id={competition}&filter=bookmarks").json()[
            "items"
        ]
        == []
    )
    assert (
        member.get(f"{base}?competition_id={competition}&filter=owned").json()["items"]
        == []
    )


def test_discussion_image_upload_persists_and_rejects_html(member):
    import base64

    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
    )
    result = member.post(
        "/api/competition-discussions/images?competition_id=1",
        files={"file": ("plot.png", png, "image/png")},
    )
    assert result.status_code == 201
    image = member.get(result.json()["url"])
    assert image.content == png and image.headers["content-type"] == "image/png"
    assert image.headers["x-content-type-options"] == "nosniff"
    assert (
        member.post(
            "/api/competition-discussions/images?competition_id=1",
            files={"file": ("bad.png", b"<script>alert(1)</script>", "image/png")},
        ).status_code
        == 422
    )
    assert (
        member.post(
            "/api/competition-discussions/images?competition_id=1",
            files={"file": ("large.png", b"x" * (5 * 1024 * 1024 + 1), "image/png")},
        ).status_code
        == 413
    )
    member.post("/api/auth/logout")
    assert (
        member.post(
            "/api/competition-discussions/images?competition_id=1",
            files={"file": ("plot.png", png, "image/png")},
        ).status_code
        == 401
    )
