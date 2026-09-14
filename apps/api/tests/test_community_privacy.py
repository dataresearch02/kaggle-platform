"""Community features never reveal private or moderator-hidden content."""

from app.models import Notebook
from test_community import activity, dataset, forum_topic, general, notebook
from test_operations import account, browser, database

HIDE = {"hidden": True, "reason": "Moderated in a privacy test"}


def ids(client, path):
    return [row["id"] for row in client.get(path).json()["items"]]


def test_notifications_never_reveal_content_the_recipient_cannot_see(member):
    bob = account("bob_p")
    admin = account("chief", role="admin")
    # A mention in a private notebook's comments is not delivered.
    private = notebook(member, "Secret notebook alpha", public=False)
    member.post(f"/api/code/{private}/comments", json={"body": "cc @bob_p"})
    # Neither is a mention in a private dataset's discussion.
    data = dataset(member, "Secret dataset beta", public=False)
    assert (
        member.post(
            "/api/competition-discussions",
            json={
                "scope": "dataset",
                "scope_id": data,
                "title": "Secret topic gamma",
                "body": "@bob_p please look",
            },
        ).status_code
        == 201
    )
    # A watcher of a topic that was hidden gets no watch or mention notification.
    topic = forum_topic(member, "Hidden topic delta", "Visible at first")
    assert (
        bob.put(
            f"/api/competition-discussions/{topic}/watch", json={"enabled": True}
        ).status_code
        == 200
    )
    admin.put(f"/api/admin/moderation/competition-post/{topic}", json=HIDE)
    assert (
        member.post(
            f"/api/competition-discussions/{topic}/comments",
            json={"body": "Owner reply for @bob_p"},
        ).status_code
        == 201
    )
    assert activity(bob) == []
    # Only the welcome service notice is unread.
    assert bob.get("/api/notifications/unread-count").json() == {"count": 1}

    # Notifications for content that later becomes hidden or private are redacted.
    shown = forum_topic(member, "Epsilon title", "Epsilon body for @bob_p")
    code = notebook(member, "Zeta notebook")
    member.post(f"/api/code/{code}/comments", json={"body": "Zeta comment for @bob_p"})
    rows = activity(bob)
    assert len(rows) == 2 and all(row["url"] and row["available"] for row in rows)
    assert {row["title"] for row in rows} == {
        "Epsilon title",
        "Comment on Zeta notebook",
    }
    admin.put(f"/api/admin/moderation/competition-post/{shown}", json=HIDE)
    assert (
        member.put(
            f"/api/code/{code}/visibility", json={"visibility": "private"}
        ).status_code
        == 200
    )
    listing = bob.get("/api/notifications")
    for secret in ("Epsilon", "Zeta", "@bob_p", "Secret", "delta"):
        assert secret not in listing.text
    rows = activity(bob)
    assert len(rows) == 2
    assert all(
        (row["available"], row["url"], row["title"]) == (False, None, None)
        for row in rows
    )


def test_votes_on_invisible_items_are_refused_and_do_not_leak(member):
    outsider, friend = account("outsider_v"), account("friend_v")
    admin = account("chief", role="admin")
    anonymous = browser()
    code = notebook(member, "Private voted notebook", public=False)
    data = dataset(member, "Private voted data", public=False)
    model = member.post(
        "/api/models",
        json={
            "title": "Hidden voted model",
            "description": "Card",
            "framework": "sk",
            "license": "MIT",
        },
    ).json()["id"]
    assert (
        member.post(
            f"/api/code/{code}/shares", json={"username": "friend_v"}
        ).status_code
        == 201
    )
    assert (
        member.post(
            f"/api/datasets/{data}/shares", json={"username": "friend_v"}
        ).status_code
        == 201
    )
    # People the item is shared with can see it, so they can vote.
    assert friend.put(f"/api/votes/code/{code}").json() == {"votes": 1, "voted": True}
    assert friend.put(f"/api/votes/dataset/{data}").json()["votes"] == 1
    assert friend.put(f"/api/votes/model/{model}").json()["votes"] == 1
    comment = member.post(f"/api/code/{code}/comments", json={"body": "Note"}).json()
    assert friend.put(f"/api/votes/notebook-comment/{comment['id']}").status_code == 200
    admin.put(f"/api/admin/moderation/model/{model}", json=HIDE)
    targets = [
        ("code", code),
        ("dataset", data),
        ("model", model),
        ("notebook-comment", comment["id"]),
    ]
    for kind, id in targets:
        path = f"/api/votes/{kind}/{id}"
        assert anonymous.get(path).status_code == 404
        for method in ("get", "put", "delete"):
            assert getattr(outsider, method)(path).status_code == 404, (kind, method)
    assert friend.get(f"/api/votes/model/{model}").status_code == 404

    # A topic hidden by a moderator: its comments' votes are unreachable too.
    topic = forum_topic(member, "Vote privacy topic")
    reply = member.post(
        f"/api/competition-discussions/{topic}/comments", json={"body": "Reply"}
    ).json()
    friend.put(f"/api/votes/reply/{reply['id']}")
    admin.put(f"/api/admin/moderation/competition-post/{topic}", json=HIDE)
    for path in (
        f"/api/votes/competition-post/{topic}",
        f"/api/votes/reply/{reply['id']}",
    ):
        assert outsider.get(path).status_code == 404
        assert outsider.put(path).status_code == 404

    # Public lists sorted by votes never include the invisible items.
    for client in (outsider, anonymous):
        listed = client.get("/api/code?sort=votes&limit=50").json()["items"]
        assert code not in [row["id"] for row in listed]
        for path, id in (("/api/datasets", data), ("/api/models", model)):
            response = client.get(f"{path}?sort=votes")
            assert id not in [row["id"] for row in response.json()]
            assert int(response.headers["X-Total-Count"]) == len(response.json())
        feed = client.get("/api/competition-discussions?sort=votes").json()["items"]
        assert topic not in [row["id"] for row in feed]


def test_private_and_hidden_content_earns_no_medals(member):
    admin = account("chief", role="admin")
    voters = [account(f"medal_voter{index}") for index in range(5)]
    bob = account("bob_m")
    public_code = notebook(member, "Medal notebook")
    private_data = dataset(member, "Medal private data", public=False)
    for index, voter in enumerate(voters):
        member.post(
            f"/api/datasets/{private_data}/shares",
            json={"username": f"medal_voter{index}"},
        )
        assert voter.put(f"/api/votes/code/{public_code}").status_code == 200
        assert voter.put(f"/api/votes/dataset/{private_data}").status_code == 200

    def medals(username="learner"):
        return {
            row["category"]: (row["gold"], row["silver"], row["bronze"])
            for row in member.get(f"/api/profiles/{username}/progression").json()[
                "categories"
            ]
        }

    def ranked(category):
        return [
            row["username"] for row in member.get(f"/api/rankings/{category}").json()
        ]

    assert medals()["notebooks"] == (0, 0, 1)
    # Five votes on a private dataset earn nothing.
    assert medals()["datasets"] == (0, 0, 0) and ranked("datasets") == []
    assert ranked("notebooks") == ["learner"]

    topic = forum_topic(member, "Medal topic")
    comment = bob.post(
        f"/api/competition-discussions/{topic}/comments", json={"body": "Helpful"}
    ).json()
    voters[0].put(f"/api/votes/reply/{comment['id']}")
    voters[1].put(f"/api/votes/competition-post/{topic}")
    assert medals("bob_m")["discussions"] == (0, 0, 1)
    assert medals()["discussions"] == (0, 0, 1)
    assert set(ranked("discussions")) == {"learner", "bob_m"}
    # Hiding a topic removes its medal and its comments' medals.
    admin.put(f"/api/admin/moderation/competition-post/{topic}", json=HIDE)
    assert medals("bob_m")["discussions"] == (0, 0, 0)
    assert medals()["discussions"] == (0, 0, 0)
    assert ranked("discussions") == []
    assert voters[2].put(f"/api/votes/reply/{comment['id']}").status_code == 404

    # A change made outside the API leaves the cache stale until recalculation.
    with database() as db:
        db.get(Notebook, public_code).hidden = 1
        db.commit()
    assert ranked("notebooks") == ["learner"]
    assert admin.post("/api/admin/progression/recalculate").status_code == 200
    assert ranked("notebooks") == [] and medals()["notebooks"] == (0, 0, 0)
    assert medals("bob_m")["discussions"] == (0, 0, 0)
    # Moderation keeps the cache current without a recalculation.
    admin.put(f"/api/admin/moderation/code/{public_code}", json={"hidden": False})
    assert medals()["notebooks"] == (0, 0, 1) and ranked("notebooks") == ["learner"]
    admin.put(f"/api/admin/moderation/code/{public_code}", json=HIDE)
    assert ranked("notebooks") == []


def test_hidden_topics_disappear_for_everyone_but_owner_and_admins(member):
    owner, follower = account("topic_owner"), account("topic_follower")
    admin = account("chief", role="admin")
    anonymous = browser()
    follower.put("/api/profiles/topic_owner/follow")
    forum_id = general(member)["id"]
    shown = forum_topic(owner, "Quokka visible")
    hidden = forum_topic(owner, "Quokka hidden")
    count = general(member)["topic_count"]
    assert (
        admin.put(
            f"/api/admin/moderation/competition-post/{hidden}", json=HIDE
        ).status_code
        == 200
    )
    feeds = [
        f"/api/competition-discussions?scope=forum&scope_id={forum_id}",
        "/api/competition-discussions",
        "/api/competition-discussions?q=Quokka&sort=hot",
    ]
    for client in (member, follower, anonymous):
        for path in feeds:
            listed = ids(client, path)
            assert shown in listed and hidden not in listed, path
        titles = [row["title"] for row in client.get("/api/search?q=quokka").json()]
        assert titles == ["Quokka visible"]
        assert client.get("/api/search/counts?q=quokka").json()["topics"] == 1
        assert general(client)["topic_count"] == count - 1
        assert client.get(f"/api/competition-discussions/{hidden}").status_code == 404
        assert hidden not in [
            row["id"] for row in client.get("/api/discussions").json()
        ]
        activity_titles = [
            row["title"]
            for row in client.get("/api/profiles/topic_owner/activity").json()
        ]
        assert "Quokka visible" in activity_titles
        assert "Quokka hidden" not in activity_titles
    feed_titles = [row["title"] for row in follower.get("/api/feed").json()]
    assert "Quokka visible" in feed_titles and "Quokka hidden" not in feed_titles
    for client in (owner, admin):
        assert hidden in ids(client, feeds[0])
        assert "Quokka hidden" in [
            row["title"] for row in client.get("/api/search?q=quokka").json()
        ]
        assert client.get(f"/api/competition-discussions/{hidden}").json()["hidden"]
        assert general(client)["topic_count"] == count
