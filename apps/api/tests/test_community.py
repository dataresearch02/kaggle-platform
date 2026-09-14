"""Forums, editing, mentions, notifications, votes, follows, feeds, search and progression."""

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.migrations import MIGRATIONS, run_migrations
from app.models import (
    CompetitionPost,
    CompetitionResult,
    ContentReaction,
    ContentReply,
    Forum,
    TopicWatch,
    User,
    UserProgression,
    Vote,
)
from app.progression import tier_for
from test_challenges import publish
from test_code_pages import document
from test_operations import account, database


def dataset(client, title="Community data", public=True):
    row = client.post(
        "/api/datasets",
        data={"title": title, "description": "Shared CSV for the community"},
        files={"file": ("data.csv", b"x,y\n1,2\n")},
    )
    assert row.status_code == 201, row.text
    if public:
        assert (
            client.put(
                f"/api/datasets/{row.json()['id']}/access",
                json={"visibility": "public"},
            ).status_code
            == 200
        )
    return row.json()["id"]


def notebook(client, title="Community notebook", public=True, description=""):
    row = client.post(
        "/api/notebooks",
        json={"title": title, "code": "print(1)", "description": description},
    ).json()
    if public:
        assert (
            client.put(
                f"/api/code/{row['id']}/publication", json=document()
            ).status_code
            == 200
        )
    return row["id"]


def activity(client):
    return [
        row
        for row in client.get("/api/notifications?limit=100").json()
        if row["source"] == "activity"
    ]


def kinds(client):
    return sorted((row["kind"], row["actor"]) for row in activity(client))


def general(client):
    return next(
        row for row in client.get("/api/forums").json() if row["slug"] == "general"
    )


def forum_topic(client, title="Forum topic", body="A forum question", forum="general"):
    response = client.post(
        f"/api/forums/{forum}/topics", json={"title": title, "body": body}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_forums_admin_management_and_legacy_aliases(member):
    forums = member.get("/api/forums").json()
    assert [row["title"] for row in forums] == [
        "General",
        "Getting Started",
        "Questions & Answers",
        "Datasets",
        "Notebooks",
        "Product Feedback",
    ]
    topic = forum_topic(member, "Which baseline first?")
    detail = member.get(f"/api/competition-discussions/{topic}").json()
    assert (detail["scope"], detail["competition_id"], detail["url"]) == (
        "forum",
        None,
        f"#discussions/{topic}",
    )
    assert detail["scope_title"] == "General" and detail["watching"]
    scoped = member.get(
        f"/api/competition-discussions?scope=forum&scope_id={general(member)['id']}"
    ).json()["items"]
    assert topic in [row["id"] for row in scoped]
    everywhere = member.get("/api/competition-discussions?sort=hot").json()["items"]
    assert any(
        row["id"] == topic and row["scope_title"] == "General" for row in everywhere
    )

    # The legacy endpoints are aliases for General forum topics and their comments.
    legacy = member.post(
        "/api/discussions", json={"title": "Legacy question", "body": "Still works"}
    )
    assert legacy.status_code == 201
    listed = member.get("/api/discussions?q=Legacy question")
    assert listed.headers["X-Total-Count"] == "1"
    assert listed.json()[0]["id"] == legacy.json()["id"]
    comment = member.post(
        f"/api/discussions/{legacy.json()['id']}/comments", json={"body": "Answer"}
    )
    assert comment.status_code == 201
    assert (
        member.get(
            f"/api/competition-discussions/{legacy.json()['id']}/comments"
        ).json()["items"][0]["body"]
        == "Answer"
    )

    assert member.post("/api/admin/forums", json={"title": "Events"}).status_code == 403
    admin = account("chief", role="admin")
    created = admin.post(
        "/api/admin/forums", json={"title": "Kaggle Days", "description": "Meetups"}
    ).json()
    assert created["slug"] == "kaggle-days" and created["position"] == 6
    renamed = admin.put(
        f"/api/admin/forums/{created['id']}",
        json={"title": "Arena Days", "archived": True},
    ).json()
    assert renamed["title"] == "Arena Days" and renamed["archived"]
    assert created["id"] not in [row["id"] for row in member.get("/api/forums").json()]
    assert (
        member.post(
            f"/api/forums/{created['id']}/topics",
            json={"title": "Too late", "body": "Archived forum"},
        ).status_code
        == 409
    )
    ids = [row["id"] for row in admin.get("/api/forums?include_archived=true").json()]
    assert (
        admin.put("/api/admin/forums/order", json={"ids": ids[:2]}).status_code == 422
    )
    reordered = admin.put("/api/admin/forums/order", json={"ids": ids[::-1]}).json()
    assert [row["id"] for row in reordered] == ids[::-1]
    with database() as db:
        forum = db.scalar(select(Forum).where(Forum.slug == "general"))
        forum.archived = 1
        db.commit()
    # Topics in archived forums stay readable but refuse comments.
    assert (
        member.get(f"/api/competition-discussions/{topic}").json()["can_comment"]
        is False
    )
    assert (
        member.post(
            f"/api/competition-discussions/{topic}/comments", json={"body": "Closed"}
        ).status_code
        == 409
    )
    actions = [
        row["action"] for row in admin.get("/api/admin/audit?action=forum.").json()
    ]
    assert sorted(actions) == ["forum.create", "forum.reorder", "forum.update"]


def test_resource_discussions_follow_resource_visibility(member):
    data = dataset(member, "Private survey", public=False)
    created = member.post(
        "/api/competition-discussions",
        json={
            "scope": "dataset",
            "scope_id": data,
            "title": "Data quality",
            "body": "Mentioning @reader about missing values",
        },
    )
    assert created.status_code == 201, created.text
    topic = created.json()["id"]
    reader = account("reader")
    assert activity(reader) == []  # The mentioned reader cannot see the dataset.
    assert (
        reader.get(
            f"/api/competition-discussions?scope=dataset&scope_id={data}"
        ).status_code
        == 404
    )
    assert reader.get(f"/api/competition-discussions/{topic}").status_code == 404
    assert topic not in [
        row["id"] for row in reader.get("/api/competition-discussions").json()["items"]
    ]
    assert reader.get("/api/search?q=Data quality").json() == []
    assert reader.put(f"/api/votes/competition-post/{topic}").status_code == 404
    assert (
        reader.post(
            "/api/reports",
            json={"kind": "competition-post", "id": topic, "reason": "spam"},
        ).status_code
        == 404
    )
    assert (
        reader.post(
            "/api/competition-discussions",
            json={
                "scope": "dataset",
                "scope_id": data,
                "title": "Hello",
                "body": "Hi there",
            },
        ).status_code
        == 404
    )

    member.put(f"/api/datasets/{data}/access", json={"visibility": "public"})
    assert reader.get(f"/api/competition-discussions/{topic}").status_code == 200
    reader_topic = reader.post(
        "/api/competition-discussions",
        json={
            "scope": "dataset",
            "scope_id": data,
            "title": "Units?",
            "body": "Which units?",
        },
    ).json()["id"]
    assert (
        reader.post(
            f"/api/competition-discussions/{topic}/comments", json={"body": "Thanks!"}
        ).status_code
        == 201
    )
    assert kinds(member) == [("comment", "reader"), ("reply", "reader")]

    member.put(f"/api/datasets/{data}/access", json={"visibility": "private"})
    # The reader's own topic is hidden with the dataset, including from notifications.
    assert reader.get(f"/api/competition-discussions/{reader_topic}").status_code == 404
    member.post(
        f"/api/competition-discussions/{reader_topic}/comments", json={"body": "Answer"}
    )
    assert activity(reader) == []
    assert all(row["url"] for row in activity(member))
    member.delete(f"/api/work/datasets/{data}")
    with database() as db:
        assert (
            db.scalar(select(CompetitionPost).where(CompetitionPost.id == topic))
            is None
        )
    assert all(not row["available"] and row["url"] is None for row in activity(member))


def test_editing_revisions_locking_and_deleted_placeholders(member):
    competition = publish(member).json()["id"]
    rival = account("rival")
    topic = rival.post(
        f"/api/competitions/{competition}/discussion",
        json={"title": "Original title", "body": "Original body"},
    ).json()["id"]
    base = f"/api/competition-discussions/{topic}"
    assert (
        member.put(base, json={"title": "Hijacked", "body": "Nope"}).status_code == 403
    )
    edited = rival.put(
        base, json={"title": "Better title", "body": "Better body"}
    ).json()
    assert edited["title"] == "Better title" and edited["edited_at"]
    assert (
        member.get("/api/admin/revisions/competition-post/%d" % topic).status_code
        == 403
    )
    admin = account("chief", role="admin")
    revisions = admin.get(f"/api/admin/revisions/competition-post/{topic}").json()
    assert [(row["title"], row["body"]) for row in revisions] == [
        ("Original title", "Original body")
    ]

    comment = member.post(base + "/comments", json={"body": "First"}).json()
    reply_base = f"/api/engagement/competition-comment/{comment['id']}"
    assert rival.put(base + "/lock", json={"enabled": True}).status_code == 403
    assert member.put(base + "/lock", json={"enabled": True}).json() == {"locked": True}
    assert rival.post(base + "/comments", json={"body": "Blocked"}).status_code == 409
    assert (
        rival.post(reply_base + "/replies", json={"body": "Blocked"}).status_code == 409
    )
    detail = rival.get(base).json()
    assert detail["locked"] and not detail["can_comment"]
    feed = rival.get(
        f"/api/competition-discussions?competition_id={competition}"
    ).json()
    assert feed["items"][0]["locked"]
    member.put(base + "/lock", json={"enabled": False})
    assert member.put(base + "/pin", json={"enabled": True}).status_code == 200
    assert rival.get(base).json()["pinned"] and not rival.get(base).json()["locked"]
    reply = rival.post(reply_base + "/replies", json={"body": "Now open"}).json()
    changed = rival.put(
        f"{reply_base}/replies/{reply['id']}", json={"body": "Now open, edited"}
    ).json()
    assert changed["edited_at"] and changed["body"] == "Now open, edited"
    assert (
        member.put(
            f"{reply_base}/replies/{reply['id']}", json={"body": "x"}
        ).status_code
        == 403
    )

    # Deleted topics with comments stay as placeholders and leave the feed.
    assert rival.delete(base).status_code == 204
    placeholder = member.get(base).json()
    assert placeholder["deleted"] and placeholder["body"] == ""
    assert placeholder["title"] == "Deleted topic" and not placeholder["can_comment"]
    assert member.get(base + "/comments").json()["items"][0]["body"] == "First"
    assert topic not in [
        row["id"]
        for row in member.get(
            f"/api/competition-discussions?competition_id={competition}"
        ).json()["items"]
    ]
    assert member.put(f"/api/votes/competition-post/{topic}").status_code == 409
    empty = rival.post(
        f"/api/competitions/{competition}/discussion",
        json={"title": "Short lived", "body": "No comments"},
    ).json()["id"]
    assert rival.delete(f"/api/competition-discussions/{empty}").status_code == 204
    assert rival.get(f"/api/competition-discussions/{empty}").status_code == 404

    # Notebook comments follow the same rules.
    code = notebook(member)
    alice = account("alice_c")
    first = alice.post(f"/api/code/{code}/comments", json={"body": "Nice"}).json()
    updated = alice.put(
        f"/api/code/{code}/comments/{first['id']}", json={"body": "Nicer"}
    )
    assert updated.json()["edited_at"] and updated.json()["body"] == "Nicer"
    member.post(
        f"/api/engagement/notebook-comment/{first['id']}/replies",
        json={"body": "Thanks"},
    )
    assert alice.delete(f"/api/code/{code}/comments/{first['id']}").status_code == 204
    listed = member.get(f"/api/code/{code}/comments").json()["items"]
    assert listed[0]["deleted"] and listed[0]["body"] == ""
    assert admin.get(f"/api/admin/revisions/notebook-comment/{first['id']}").json()[0][
        "body"
    ] in ("Nice", "Nicer")


def test_mentions_notifications_preferences_and_service_notices(member):
    alice, bob = account("alice"), account("bob")
    topic = forum_topic(
        alice,
        "Mentions",
        "Hi @bob and @Nobody_here, see `@learner` and\n```\n@learner\n```",
    )
    assert alice.get(f"/api/competition-discussions/{topic}").json()["mentions"] == [
        "bob"
    ]
    assert kinds(bob) == [("mention", "alice")]
    assert kinds(member) == []
    assert member.put(
        f"/api/competition-discussions/{topic}/watch", json={"enabled": True}
    ).json() == {"watching": True}
    # One notification per recipient per event: a mention wins over a reply.
    comment = bob.post(
        f"/api/competition-discussions/{topic}/comments", json={"body": "Thanks @alice"}
    ).json()
    assert comment["mentions"] == ["alice"]
    assert kinds(alice) == [("mention", "bob")]
    assert kinds(member) == [("watch", "bob")]
    bob.post(f"/api/competition-discussions/{topic}/comments", json={"body": "More"})
    assert kinds(alice) == [("mention", "bob"), ("reply", "bob")]
    # Edits notify only newly mentioned users.
    edit_path = f"/api/engagement/competition-post/{topic}/replies/{comment['id']}"
    bob.put(edit_path, json={"body": "Thanks @alice and @learner"})
    bob.put(edit_path, json={"body": "Thanks @alice and @learner!"})
    assert kinds(member).count(("mention", "bob")) == 1

    # No notification about content the recipient cannot see.
    private = notebook(member, "Private work", public=False)
    member.post(f"/api/code/{private}/comments", json={"body": "cc @alice"})
    assert ("mention", "learner") not in kinds(alice)

    assert (
        alice.put(
            "/api/account/notification-preferences", json={"reply": False, "x": True}
        ).status_code
        == 422
    )
    prefs = alice.put(
        "/api/account/notification-preferences", json={"reply": False, "watch": False}
    ).json()["preferences"]
    assert {row["kind"]: row["enabled"] for row in prefs}["reply"] is False
    before = len(activity(alice))
    bob.post(f"/api/competition-discussions/{topic}/comments", json={"body": "Quiet"})
    assert len(activity(alice)) == before

    bob.put("/api/profiles/alice/follow")
    assert ("follow", "bob") in kinds(alice)
    code = notebook(member, "Forkable")
    assert bob.post(f"/api/code/{code}/fork").status_code == 201
    assert ("fork", "bob") in kinds(member)
    data = dataset(member)
    alice.put(f"/api/votes/dataset/{data}")
    bob.put(f"/api/votes/dataset/{data}")
    votes = [row for row in activity(member) if row["kind"] == "vote"]
    assert len(votes) == 1 and votes[0]["count"] == 2
    assert votes[0]["message"].startswith("bob and 1 other upvoted")

    report = bob.post(
        "/api/reports",
        json={"kind": "competition-post", "id": topic, "reason": "Off topic"},
    ).json()
    admin = account("chief", role="admin")
    admin.post(f"/api/admin/reports/{report['id']}/resolve", json={"note": "Fine"})
    assert ("report", "chief") in kinds(bob)

    # Service notices share the bell, counts and read-all.
    everything = member.get("/api/notifications")
    assert int(everything.headers["X-Total-Count"]) == len(everything.json())
    assert any(row["source"] == "service" for row in everything.json())
    unread = member.get("/api/notifications/unread-count").json()["count"]
    first = activity(member)[0]
    after = member.post(f"/api/notifications/activity/{first['id']}/read").json()[
        "count"
    ]
    assert after == unread - 1
    assert (
        bob.post(f"/api/notifications/activity/{first['id']}/read").status_code == 404
    )
    member.post("/api/notifications/read-all")
    assert member.get("/api/notifications/unread-count").json() == {"count": 0}
    assert all(row["read"] for row in member.get("/api/account/notifications").json())


def test_competition_result_notifications_and_leaderboard_tiers(member):
    competition = publish(member).json()["id"]
    racer = account("racer")
    racer.post(f"/api/competitions/{competition}/join", json={"accept_rules": True})
    assert (
        racer.post(
            f"/api/competitions/{competition}/submissions",
            files={"file": ("p.csv", "id,prediction\na,123\nb,678\n")},
        ).status_code
        == 201
    )
    board = member.get(f"/api/competitions/{competition}/leaderboard").json()
    assert board[0]["username"] == "racer" and board[0]["tier"] == "Contributor"
    with database() as db:
        from app.models import Competition

        db.get(Competition, competition).deadline = "2020-01-01T00:00:00+00:00"
        db.commit()
    member.get(f"/api/competitions/{competition}")
    result = [row for row in activity(racer) if row["kind"] == "result"]
    assert len(result) == 1 and result[0]["detail"]["rank"] == 1
    assert result[0]["url"] == f"#competitions/{competition}/leaderboard"
    member.post(f"/api/competitions/{competition}/host/finalize")
    assert len([row for row in activity(racer) if row["kind"] == "result"]) == 1


def test_votes_rules_counts_and_most_voted_sorting(member):
    fan = account("fan")
    older, newer = dataset(member, "Older data"), dataset(member, "Newer data")
    assert member.put(f"/api/votes/dataset/{older}").status_code == 422
    for _ in range(2):
        assert fan.put(f"/api/votes/dataset/{older}").json() == {
            "votes": 1,
            "voted": True,
        }
    by_votes = fan.get("/api/datasets?sort=votes").json()
    assert by_votes[0]["id"] == older and by_votes[0]["voted"]
    assert fan.get("/api/datasets").json()[0]["id"] == newer
    assert fan.get(f"/api/datasets/{older}").json()["votes"] == 1
    assert fan.delete(f"/api/votes/dataset/{older}").json() == {
        "votes": 0,
        "voted": False,
    }

    hidden_code = notebook(member, "Secret", public=False)
    public_code = notebook(member, "Shown")
    assert fan.put(f"/api/votes/code/{hidden_code}").status_code == 404
    assert fan.get(f"/api/votes/code/{hidden_code}").status_code == 404
    fan.put(f"/api/votes/code/{public_code}")
    listing = fan.get("/api/code?sort=votes&limit=1").json()
    assert listing["items"][0]["id"] == public_code and listing["items"][0]["voted"]
    assert listing["next_offset"] == 1 and listing["next_cursor"] is None
    assert fan.get(f"/api/code/{public_code}").json()["votes"] == 1

    model = member.post(
        "/api/models",
        json={
            "title": "Voted model",
            "description": "Card",
            "framework": "sk",
            "license": "MIT",
        },
    ).json()["id"]
    fan.put(f"/api/votes/model/{model}")
    assert fan.get("/api/models?sort=votes").json()[0]["id"] == model
    admin = account("chief", role="admin")
    admin.put(
        f"/api/admin/moderation/model/{model}", json={"hidden": True, "reason": "spam"}
    )
    assert fan.get(f"/api/votes/model/{model}").status_code == 404
    assert fan.put(f"/api/votes/model/{model}").status_code == 404

    topic = forum_topic(member, "Vote on me")
    comment = member.post(
        f"/api/competition-discussions/{topic}/comments", json={"body": "And me"}
    ).json()
    # Reactions stay separate from votes.
    fan.put(f"/api/engagement/competition-post/{topic}/reactions/like")
    feed = fan.get("/api/competition-discussions?sort=votes").json()["items"]
    assert next(row for row in feed if row["id"] == topic)["votes"] == 0
    fan.put(f"/api/votes/competition-post/{topic}")
    fan.put(f"/api/votes/reply/{comment['id']}")
    feed = fan.get("/api/competition-discussions?sort=votes").json()["items"]
    assert feed[0]["id"] == topic and feed[0]["votes"] == 1 and feed[0]["voted"]
    comments = fan.get(f"/api/competition-discussions/{topic}/comments").json()["items"]
    assert (comments[0]["votes"], comments[0]["voted"]) == (1, True)
    assert fan.put("/api/votes/unknown/1").status_code == 422


def test_follows_respect_profile_visibility_and_feeds_show_public_activity(member):
    alice, bob = account("alice_f"), account("bob_f")
    assert bob.put("/api/profiles/bob_f/follow").status_code == 422
    assert bob.put("/api/profiles/alice_f/follow").json()["followers"] == 1
    member.put("/api/profiles/alice_f/follow")
    assert member.get("/api/profiles/alice_f/follows").json() == {
        "followers": 2,
        "following": 0,
        "is_following": True,
        "can_follow": True,
    }
    bob.put("/api/account/settings", json={"visibility": "private"})
    listed = member.get("/api/profiles/alice_f/followers")
    assert [row["username"] for row in listed.json()] == ["learner"]
    assert listed.headers["X-Total-Count"] == "1"
    assert member.get("/api/profiles/alice_f/follows").json()["followers"] == 1
    assert member.get("/api/profiles/bob_f/following").status_code == 404
    assert [
        row["username"] for row in bob.get("/api/profiles/bob_f/following").json()
    ] == ["alice_f"]
    assert member.put("/api/profiles/bob_f/follow").status_code == 404

    shown = notebook(alice, "Alice public notebook")
    notebook(alice, "Alice private notebook", public=False)
    dataset(alice, "Alice private data", public=False)
    public_data = dataset(alice, "Alice public data")
    topic = forum_topic(alice, "Alice hidden topic")
    admin = account("chief", role="admin")
    admin.put(
        f"/api/admin/moderation/competition-post/{topic}",
        json={"hidden": True, "reason": "spam"},
    )
    forum_topic(member, "Learner topic")
    feed = member.get("/api/feed")
    titles = [row["title"] for row in feed.json()]
    assert set(titles) == {
        "Alice public notebook",
        "Alice public data",
        "Learner topic",
    }
    assert feed.headers["X-Total-Count"] == "3"
    assert [row["url"] for row in feed.json() if row["kind"] == "notebook"] == [
        f"#code/{shown}"
    ]
    activity_titles = [
        row["title"] for row in bob.get("/api/profiles/alice_f/activity").json()
    ]
    assert set(activity_titles) == {"Alice public notebook", "Alice public data"}
    assert len(member.get("/api/feed?limit=1").json()) == 1
    alice.put("/api/account/settings", json={"visibility": "private"})
    assert member.get("/api/profiles/alice_f/activity").status_code == 404
    # Followed users with restricted profiles leave the feed.
    assert [row["title"] for row in member.get("/api/feed").json()] == ["Learner topic"]
    assert member.delete("/api/profiles/alice_f/follow").status_code == 200
    assert member.get("/api/feed").json()[0]["title"] == "Learner topic"
    assert public_data


def test_search_ranks_titles_and_applies_visibility(member):
    dataset(member, "Zebracorn measurements")
    dataset(member, "Zebracorn secrets", public=False)
    notebook(member, "Striped horses", description="A zebracorn walkthrough")
    notebook(member, "Zebracorn private notebook", public=False)
    hidden_model = member.post(
        "/api/models",
        json={
            "title": "Zebracorn model",
            "description": "Card",
            "framework": "sk",
            "license": "MIT",
        },
    ).json()["id"]
    forum_topic(member, "Zebracorn questions", "Where do they live?")
    hidden_topic = forum_topic(member, "Hidden zebracorn", "Spam")
    account("zebracorn_fan").put(
        "/api/account/settings", json={"visibility": "private"}
    )
    account("zebracorn")
    admin = account("chief", role="admin")
    for kind, id in (("model", hidden_model), ("competition-post", hidden_topic)):
        assert (
            admin.put(
                f"/api/admin/moderation/{kind}/{id}",
                json={"hidden": True, "reason": "spam"},
            ).status_code
            == 200
        )
    visitor = account("visitor")
    response = visitor.get("/api/search?q=zebracorn")
    results = [(row["type"], row["title"]) for row in response.json()]
    assert response.headers["X-Total-Count"] == str(len(results)) == "4"
    assert results[0] == ("users", "zebracorn")  # exact match first
    assert results[-1] == ("notebooks", "Striped horses")  # description match last
    assert set(results[1:3]) == {
        ("datasets", "Zebracorn measurements"),
        ("topics", "Zebracorn questions"),
    }
    counts = visitor.get("/api/search/counts?q=zebracorn").json()
    assert counts == {
        "competitions": 0,
        "datasets": 1,
        "notebooks": 1,
        "models": 0,
        "topics": 1,
        "courses": 0,
        "users": 1,
    }
    only = visitor.get("/api/search?q=zebracorn&type=datasets&limit=1&offset=0").json()
    assert [row["url"] for row in only][0].startswith("#datasets/")
    assert (
        visitor.get("/api/search?q=zebracorn&offset=3").json()[0]["type"] == "notebooks"
    )
    mine = {row["title"] for row in member.get("/api/search?q=zebracorn").json()}
    assert {"Zebracorn secrets", "Zebracorn private notebook"} <= mine
    assert {"Zebracorn model", "Hidden zebracorn"} & mine
    assert visitor.get("/api/search?q=%20").json() == []
    assert (
        visitor.get("/api/search?q=python&type=courses").json()[0]["type"] == "courses"
    )


def test_tier_rules_count_higher_medals_toward_lower_requirements():
    assert tier_for("competitions", 0, 0, 0) == 0
    assert tier_for("competitions", 0, 0, 0, contributor=True) == 1
    assert tier_for("competitions", 0, 1, 1) == 2
    assert tier_for("competitions", 1, 2, 0) == 3
    assert tier_for("competitions", 3, 0, 0) == 3  # gold counts toward the silver slots
    assert tier_for("competitions", 5, 0, 0) == 3  # no solo gold
    assert tier_for("competitions", 5, 0, 0, solo_gold=1) == 4
    assert tier_for("datasets", 0, 0, 2) == 1
    assert tier_for("datasets", 0, 3, 0) == 2
    assert tier_for("datasets", 1, 4, 0) == 3
    assert tier_for("datasets", 5, 4, 0) == 3
    assert tier_for("datasets", 10, 0, 0) == 4
    assert tier_for("notebooks", 0, 0, 5) == 2
    assert tier_for("notebooks", 4, 6, 0) == 3
    assert tier_for("notebooks", 15, 0, 0) == 4
    assert tier_for("discussions", 0, 0, 50) == 2
    assert tier_for("discussions", 0, 50, 149) == 2
    assert tier_for("discussions", 0, 50, 150) == 3
    assert tier_for("discussions", 50, 0, 450) == 4


def progression_rows():
    """Cache rows, ignoring Novice rows without medals (the same as a missing row)."""
    with database() as db:
        return sorted(
            (
                row.user_id,
                row.category,
                row.tier,
                row.gold,
                row.silver,
                row.bronze,
                row.achieved_at,
            )
            for row in db.scalars(select(UserProgression))
            if row.tier or row.gold or row.silver or row.bronze
        )


def test_medals_tiers_rankings_and_recalculation(member):
    admin = account("chief", role="admin")
    # As at startup after an upgrade, the cache starts from a full calculation.
    admin.post("/api/admin/progression/recalculate")
    voters = [account(f"voter{index}") for index in range(5)]
    data, code = dataset(member), notebook(member)
    topic = forum_topic(member, "Helpful answer")
    for voter in voters:
        voter.put(f"/api/votes/dataset/{data}")
        voter.put(f"/api/votes/code/{code}")
    voters[0].put(f"/api/votes/competition-post/{topic}")
    progression = member.get("/api/profiles/learner/progression").json()
    categories = {row["category"]: row for row in progression["categories"]}
    assert (categories["datasets"]["bronze"], categories["datasets"]["tier_name"]) == (
        1,
        "Contributor",
    )
    assert (
        categories["notebooks"]["bronze"] == 1
        and categories["discussions"]["bronze"] == 1
    )
    assert categories["competitions"]["tier_name"] == "Novice"
    assert progression["tier_name"] == "Contributor"
    ranking = member.get("/api/rankings/datasets")
    assert ranking.headers["X-Total-Count"] == "1"
    assert ranking.json()[0]["username"] == "learner" and ranking.json()[0]["rank"] == 1
    feed = member.get("/api/competition-discussions?q=Helpful answer").json()["items"]
    assert feed[0]["owner_tier"] == "Contributor"
    assert member.get("/api/rankings/unknown").status_code == 404

    # Making the dataset private removes its medal; the cache follows the change.
    member.put(f"/api/datasets/{data}/access", json={"visibility": "private"})
    assert member.get("/api/rankings/datasets").json() == []
    voters[0].delete(f"/api/votes/competition-post/{topic}")
    incremental = progression_rows()
    with database() as db:
        db.query(UserProgression).delete()
        db.commit()
    assert member.post("/api/admin/progression/recalculate").status_code == 403
    assert admin.post("/api/admin/progression/recalculate").json()["users"] >= 8
    assert progression_rows() == incremental

    names = ("grand", "almost", "master_user", "hidden_master")
    clients = {name: account(name) for name in names}
    with database() as db:
        ids = {
            name: db.scalar(select(User.id).where(User.username == name))
            for name in names
        }
        rows = [
            (
                ids["grand"],
                1000 + index,
                None if index == 0 else index,
                "gold",
                "2026-01-01",
            )
            for index in range(5)
        ]
        rows += [
            (ids["almost"], 1000 + index, index + 1, "gold", "2026-02-01")
            for index in range(5)
        ]
        rows += [(ids["master_user"], 1000, 1, "gold", "2026-01-01")]
        rows += [
            (ids["master_user"], 1001 + index, 1, "silver", "2026-01-01")
            for index in range(2)
        ]
        rows += [
            (ids["hidden_master"], 1000 + index, 1, "gold", "2025-01-01")
            for index in range(6)
        ]
        for user_id, competition_id, team_id, medal, created_at in rows:
            db.add(
                CompetitionResult(
                    competition_id=competition_id,
                    user_id=user_id,
                    team_id=team_id,
                    rank=1,
                    team_count=50,
                    medal=medal,
                    score=1.0,
                    created_at=created_at,
                )
            )
        db.commit()
    clients["hidden_master"].put(
        "/api/account/settings", json={"visibility": "private"}
    )
    admin.post("/api/admin/progression/recalculate")
    board = member.get("/api/rankings/competitions")
    assert [(row["username"], row["tier_name"]) for row in board.json()] == [
        ("grand", "Grandmaster"),
        ("almost", "Master"),
        ("master_user", "Master"),
    ]
    assert board.headers["X-Total-Count"] == "3"
    assert (
        member.get("/api/rankings/competitions?offset=1&limit=1").json()[0]["rank"] == 2
    )
    assert (
        member.get("/api/profiles/grand/progression").json()["tier_name"]
        == "Grandmaster"
    )
    medals = member.get("/api/profiles/grand/activity").json()
    assert {row["message"] for row in medals} == {"won a gold medal"}
    assert member.get("/api/profiles/hidden_master/progression").status_code == 404


def test_community_migrations_upgrade_topics_and_copy_legacy_discussions():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as connection:
        for statement in [
            "CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(40) NOT NULL"
            " UNIQUE, password_hash TEXT NOT NULL, created_at VARCHAR)",
            "CREATE TABLE competitions (id INTEGER PRIMARY KEY, title VARCHAR(160) NOT NULL,"
            " description TEXT NOT NULL, category VARCHAR(80), metric VARCHAR(30),"
            " deadline VARCHAR NOT NULL, solution TEXT NOT NULL, prize VARCHAR(80))",
            "CREATE TABLE competition_posts (id INTEGER NOT NULL, competition_id INTEGER"
            " NOT NULL, owner_id INTEGER NOT NULL, title VARCHAR(160) NOT NULL, body TEXT"
            " NOT NULL, created_at VARCHAR, PRIMARY KEY (id), FOREIGN KEY(competition_id)"
            " REFERENCES competitions (id), FOREIGN KEY(owner_id) REFERENCES users (id))",
            "CREATE INDEX ix_old_posts_owner ON competition_posts (owner_id)",
            "CREATE TABLE content_replies (id INTEGER PRIMARY KEY, target_kind VARCHAR(32)"
            " NOT NULL, target_id INTEGER NOT NULL, owner_id INTEGER NOT NULL, body TEXT"
            " NOT NULL, created_at VARCHAR)",
            "CREATE TABLE content_reactions (id INTEGER PRIMARY KEY, target_kind"
            " VARCHAR(32) NOT NULL, target_id INTEGER NOT NULL, user_id INTEGER NOT NULL,"
            " reaction VARCHAR(20) NOT NULL)",
            "CREATE TABLE discussions (id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL,"
            " title VARCHAR(160) NOT NULL, body TEXT NOT NULL, created_at VARCHAR)",
            "CREATE TABLE comments (id INTEGER PRIMARY KEY, discussion_id INTEGER NOT NULL,"
            " owner_id INTEGER NOT NULL, body TEXT NOT NULL, created_at VARCHAR)",
            "INSERT INTO users (id, username, password_hash) VALUES (1, 'veteran', 'x:y'),"
            " (2, 'fan', 'x:y')",
            "INSERT INTO competitions (id, title, description, deadline, solution)"
            " VALUES (1, 'Old', 'Kept', '2030-01-01T00:00:00+00:00', '{}')",
            "INSERT INTO competition_posts VALUES (4, 1, 1, 'Old topic', 'Kept', '2025')",
            "INSERT INTO content_reactions (target_kind, target_id, user_id, reaction)"
            " VALUES ('competition-post', 4, 2, 'like'), ('competition-post', 4, 1, 'like'),"
            " ('discussion', 7, 2, 'helpful')",
            "INSERT INTO discussions VALUES (7, 1, 'Old question', 'Legacy body', '2024')",
            "INSERT INTO comments VALUES (3, 7, 2, 'Legacy answer', '2024')",
            "INSERT INTO content_replies (target_kind, target_id, owner_id, body)"
            " VALUES ('discussion-comment', 3, 1, 'Nested legacy reply')",
        ]:
            connection.execute(text(statement))
    Base.metadata.create_all(engine)
    assert run_migrations(engine) == [id for id, _ in MIGRATIONS]
    inspector = inspect(engine)
    columns = {row["name"]: row for row in inspector.get_columns("competition_posts")}
    assert columns["competition_id"]["nullable"]
    assert {"scope", "scope_id", "edited_at", "deleted_at", "hidden"} <= set(columns)
    assert {"ix_old_posts_owner", "ix_competition_posts_scope"} <= {
        row["name"] for row in inspector.get_indexes("competition_posts")
    }
    Session = sessionmaker(bind=engine)

    def snapshot():
        with Session() as db:
            topics = {
                row.title: (row.scope, row.scope_id, row.competition_id, row.body)
                for row in db.scalars(select(CompetitionPost))
            }
            return (
                topics,
                sorted(
                    (r.target_kind, r.body) for r in db.scalars(select(ContentReply))
                ),
                sorted(
                    (r.target_kind, r.reaction)
                    for r in db.scalars(select(ContentReaction))
                ),
                sorted(
                    (v.target_kind, v.target_id, v.user_id)
                    for v in db.scalars(select(Vote))
                ),
                len(db.scalars(select(TopicWatch)).all()),
                len(db.scalars(select(Forum)).all()),
            )

    topics, replies, reactions, votes, watches, forums = snapshot()
    with Session() as db:
        general_id = db.scalar(select(Forum.id).where(Forum.slug == "general"))
        copied = db.scalar(
            select(CompetitionPost).where(CompetitionPost.title == "Old question")
        )
        answer = db.scalar(
            select(ContentReply).where(ContentReply.body == "Legacy answer")
        )
        nested = db.scalar(
            select(ContentReply).where(ContentReply.body == "Nested legacy reply")
        )
        assert (answer.target_kind, answer.target_id) == ("competition-post", copied.id)
        assert (nested.target_kind, nested.target_id) == (
            "competition-comment",
            answer.id,
        )
        moved = db.scalar(
            select(ContentReaction).where(ContentReaction.reaction == "helpful")
        )
        assert (moved.target_kind, moved.target_id) == ("competition-post", copied.id)
    assert topics["Old topic"] == ("competition", 1, 1, "Kept")
    assert topics["Old question"] == ("forum", general_id, None, "Legacy body")
    assert votes == [("competition-post", 4, 2)]  # the author's own like is not a vote
    assert (watches, forums) == (2, 6)

    with Session() as db:
        db.execute(text("DELETE FROM schema_migrations"))
        db.commit()
    assert len(run_migrations(engine)) == len(MIGRATIONS)
    assert snapshot() == (topics, replies, reactions, votes, watches, forums)
    with Session() as db:
        db.add(
            CompetitionPost(
                scope="forum", scope_id=general_id, owner_id=2, title="New", body="Body"
            )
        )
        db.commit()
    engine.dispose()
