from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.db import get_db
from app.main import app
from app.models import Competition
from test_challenges import publish


def test_competition_search_filters_and_sort(member):
    late = publish(
        member,
        data={
            "title": "Zebra study",
            "description": "Unique astronomy project",
            "category": "Research",
        },
    ).json()
    soon = publish(
        member,
        data={
            "title": "Alpha study",
            "category": "Research",
            "deadline": (datetime.now(timezone.utc) + timedelta(days=10)).isoformat(),
        },
    ).json()
    closed = publish(
        member, data={"title": "Closed study", "category": "Research"}
    ).json()
    publish(
        member,
        "benchmarks",
        data={"title": "Benchmark study", "category": "Benchmark only"},
    )
    with next(app.dependency_overrides[get_db]()) as db:
        db.get(Competition, closed["id"]).deadline = "2020-01-01T12:00:00+09:00"
        db.commit()
    query = "/api/competitions?category=Research"
    assert [
        i["id"] for i in member.get(query + "&status=open&sort=closing").json()
    ] == [soon["id"], late["id"]]
    assert [i["id"] for i in member.get(query + "&status=closed").json()] == [
        closed["id"]
    ]
    assert [i["id"] for i in member.get(query + "&sort=title").json()] == [
        soon["id"],
        closed["id"],
        late["id"],
    ]
    assert [i["id"] for i in member.get(query + "&q=ASTRONOMY").json()] == [late["id"]]
    assert member.get(query + "&q=no-match").json() == []
    categories = member.get("/api/competitions/filters").json()["categories"]
    assert "Research" in categories and "Benchmark only" not in categories
    assert member.get("/api/competitions?status=invalid").status_code == 422
    assert member.get("/api/competitions?sort=invalid").status_code == 422
    member.post("/api/auth/logout")
    assert member.get(query + "&status=closed").status_code == 200
