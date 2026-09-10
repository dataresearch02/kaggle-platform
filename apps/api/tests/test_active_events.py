from app.db import get_db
from app.main import app
from app.models import NotebookCommit, User
from sqlalchemy import select


def test_active_events_are_owned_and_in_progress(member):
    notebook = member.post(
        "/api/notebooks", json={"title": "Event notebook", "code": "print(1)"}
    ).json()
    with next(app.dependency_overrides[get_db]()) as db:
        owner = db.scalar(select(User).where(User.username == "learner"))
        for state in ["queued", "running", "succeeded", "failed"]:
            db.add(
                NotebookCommit(
                    notebook_id=notebook["id"],
                    owner_id=owner.id,
                    competition_id=1,
                    document="{}",
                    output_filename="submission.csv",
                    status=state,
                )
            )
        db.commit()
    events = member.get("/api/active-events").json()
    assert {event["status"] for event in events} == {"queued", "running"}
    assert all(event["title"] == "Event notebook" for event in events)
    member.post("/api/auth/logout")
    assert member.get("/api/active-events").status_code == 401
    member.post(
        "/api/auth/register",
        json={"username": "another", "password": "good-password-123"},
    )
    assert member.get("/api/active-events").json() == []
