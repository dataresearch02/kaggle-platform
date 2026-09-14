import asyncio
import json

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import compute_worker, runtime_jobs
from app.db import get_db
from app.main import app
from app.models import AuditLog, CourseExercise, ExerciseAttempt, User
from app.notebook_runtime import get_hub
from test_notebook_runtime import FakeHub

PASSWORD = "good-password-123"
COURSE = {"title": "Plotting basics", "summary": "Draw your first charts."}
CHECKER = (
    "SECRET_CHECK = 41\nassert answer == SECRET_CHECK + 1, 'answer should be 42'\n"
)
EXERCISE = {
    "title": "The answer",
    "prompt": "Set `answer` to 42.",
    "starter_code": "answer = None\n",
    "hints": ["It is a number.", "It is 6 × 7."],
    "solution": "answer = 6 * 7  # SOLUTION-MARK\n",
    "checker": CHECKER,
    "reveal_after": 2,
    "inputs": ["wine-cultivar"],
}


def database():
    return next(app.dependency_overrides[get_db]())


def become(client, username, role="user"):
    client.post("/api/auth/logout")
    response = client.post(
        "/api/auth/login", json={"username": username, "password": PASSWORD}
    )
    if response.status_code != 200:
        assert (
            client.post(
                "/api/auth/register", json={"username": username, "password": PASSWORD}
            ).status_code
            == 201
        )
    if role != "user":
        with database() as db:
            db.scalar(select(User).where(User.username == username)).role = role
            db.commit()


@pytest.fixture
def worker_db(monkeypatch):
    with database() as db:
        factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(compute_worker, "SessionLocal", factory)
    return factory


@pytest.fixture
def hub():
    hub = FakeHub()
    app.dependency_overrides[get_hub] = lambda: hub
    yield hub
    app.dependency_overrides.pop(get_hub, None)


def authored_course(client, exercise=EXERCISE):
    become(client, "author", "host")
    course = client.post("/api/courses", json=COURSE).json()
    lesson = client.post(
        f"/api/courses/{course['id']}/lessons",
        json={"title": "Charts", "body": "## Charts\n\nUse `matplotlib`."},
    ).json()
    created = client.post(
        f"/api/courses/{course['id']}/lessons/{lesson['id']}/exercises", json=exercise
    )
    assert created.status_code == 201, created.text
    assert client.post(f"/api/courses/{course['id']}/publish").status_code == 200
    return course["id"], lesson["id"], created.json()["id"]


def test_seeded_courses_are_upgraded_with_graded_exercises(client):
    courses = client.get("/api/courses").json()
    assert [row["title"] for row in courses] == [
        "Python foundations",
        "Intro to machine learning",
        "Pandas essentials",
    ]
    assert all(
        row["status"] == "published" and row["exercise_count"] >= 3 for row in courses
    )
    course = client.get(f"/api/courses/{courses[0]['id']}").json()
    lesson = client.get(
        f"/api/courses/{course['id']}/lessons/{course['lessons'][0]['id']}"
    ).json()
    assert "```python" in lesson["body"] and lesson["next_id"]
    exercise = lesson["exercises"][0]
    assert exercise["solution"] is None and exercise["hints"] == []
    assert "checker" not in exercise and exercise["hint_count"] == 2
    with database() as db:
        checkers = list(db.scalars(select(CourseExercise.checker)))
        assert len(checkers) >= 9
        pandas = db.scalar(
            select(CourseExercise).where(CourseExercise.title == "Filter and sort")
        )
        assert json.loads(pandas.inputs) == ["wine-cultivar"]
    for path in ("/api/courses", f"/api/courses/{course['id']}"):
        assert all(checker[:60] not in client.get(path).text for checker in checkers)
    assert client.get(f"/api/exercises/{exercise['id']}/source").status_code == 401
    assert client.get("/api/search?q=python&type=courses").json()[0]["url"] == (
        f"#courses/{course['id']}"
    )


def test_authors_manage_drafts_that_only_authors_and_admins_see(client):
    become(client, "plain")
    assert client.post("/api/courses", json=COURSE).status_code == 403
    become(client, "author", "host")
    course = client.post("/api/courses", json=COURSE).json()
    path = f"/api/courses/{course['id']}"
    assert course["status"] == "draft" and course["can_edit"]
    assert client.post(path + "/publish").status_code == 409
    first = client.post(
        path + "/lessons", json={"title": "One", "body": "# One"}
    ).json()
    second = client.post(path + "/lessons", json={"title": "Two"}).json()
    lessons = f"{path}/lessons/{first['id']}/exercises"
    assert client.post(lessons, json={**EXERCISE, "checker": "if :"}).status_code == 422
    assert (
        client.post(lessons, json={**EXERCISE, "inputs": ["../secrets"]}).status_code
        == 422
    )
    source = client.post(lessons, json=EXERCISE).json()
    assert source["checker"] == CHECKER and source["solution"] == EXERCISE["solution"]
    reordered = client.put(
        path + "/lessons/order", json={"ids": [second["id"], first["id"]]}
    )
    assert [row["id"] for row in reordered.json()["lessons"]] == [
        second["id"],
        first["id"],
    ]
    assert (
        client.put(path + "/lessons/order", json={"ids": [first["id"]]}).status_code
        == 422
    )
    assert "Plotting" not in client.get("/api/search?q=plotting&type=courses").text

    for viewer in (None, "other_host"):
        client.post("/api/auth/logout")
        if viewer:
            become(client, viewer, "host")
        assert client.get(path).status_code == 404
        assert all(
            row["id"] != course["id"] for row in client.get("/api/courses").json()
        )
        assert client.get(f"/api/exercises/{source['id']}").status_code == 404
    assert client.put(path, json=COURSE).status_code == 404
    assert client.get(f"/api/exercises/{source['id']}/source").status_code == 404

    become(client, "boss", "admin")
    assert client.get(path).json()["can_edit"] is True
    assert (
        client.put(path, json={**COURSE, "difficulty": "advanced"}).status_code == 200
    )
    with database() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.action == "course.update"))

    become(client, "author")
    assert client.post(path + "/publish").json()["status"] == "published"
    client.post("/api/auth/logout")
    assert client.get(path).json()["difficulty"] == "advanced"
    assert all(CHECKER[:20] not in client.get(p).text for p in (path, "/api/courses"))
    become(client, "author")
    assert client.delete(path).status_code == 409
    assert client.post(path + "/unpublish").json()["status"] == "draft"
    assert client.delete(path).status_code == 204
    assert client.get(path).status_code == 404


def test_attempts_reveal_hints_and_solution_then_issue_a_certificate(
    client, worker_db, monkeypatch
):
    course_id, lesson_id, exercise_id = authored_course(client)
    become(client, "student")
    exercise_path = f"/api/exercises/{exercise_id}"
    assert client.get(exercise_path).json()["solution"] is None
    assert len(client.post(exercise_path + "/hints").json()["hints"]) == 1
    assert client.post(exercise_path + "/hints").json()["hints"][1] == "It is 6 × 7."
    assert client.post(exercise_path + "/hints").status_code == 409

    outcomes = [
        {
            "status": "failed",
            "message": "answer should be 42",
            "stdout": "\x1b[31mhi\n",
        },
        {"status": "failed", "message": "Still not 42", "stdout": "x" * 30000},
        {"status": "passed", "message": "Correct!", "stdout": ""},
    ]
    staged = []

    async def fake_run(name, work, env, timeout, active, gpus=None):
        assert name.startswith("arena-attempt-") and active() and gpus == 0
        # The checker is staged for the runner, which deletes it before learner code.
        assert (work / "checker.py").read_text() == CHECKER
        assert (work / "input/wine-cultivar/train.csv").is_file()
        assert not (work / "input/wine-cultivar/solution.csv").exists()
        staged.append(work)
        (work / "result.json").write_text(json.dumps(outcomes.pop(0)))

    monkeypatch.setattr(runtime_jobs, "run", fake_run)
    for expected in ("failed", "failed", "passed"):
        attempt = client.post(exercise_path + "/attempts", json={"code": "answer = 1"})
        assert attempt.status_code == 202 and attempt.json()["status"] == "queued"
        assert (
            client.post(exercise_path + "/attempts", json={"code": "x"}).status_code
            == 409
        )
        with worker_db() as db:
            assert compute_worker.claim(db) == ("attempt", attempt.json()["id"])
        asyncio.run(compute_worker.execute_attempt(attempt.json()["id"]))
        compute_worker.release("attempt", attempt.json()["id"])
        detail = client.get(f"/api/exercise-attempts/{attempt.json()['id']}").json()
        assert detail["status"] == expected
        assert "\x1b" not in detail["stdout"] and len(detail["stdout"]) <= 20000
        assert CHECKER[:20] not in json.dumps(detail)
        if expected == "failed" and detail["exercise"]["attempts"] == 1:
            assert detail["exercise"]["solution"] is None
            assert detail["message"] == "answer should be 42"
        else:
            # reveal_after=2: shown after the second finished attempt.
            assert "SOLUTION-MARK" in detail["exercise"]["solution"]
    assert not any(work.exists() for work in staged)
    assert client.get(exercise_path).json()["passed"] is True
    assert len(client.get(exercise_path + "/attempts").json()) == 3

    course = client.get(f"/api/courses/{course_id}").json()
    code = course["progress"]["certificate"]
    assert code and course["progress"]["passed_exercises"] == 1
    assert client.post(f"/api/lessons/{lesson_id}/complete").json() == {
        "completed": True
    }
    assert client.get(f"/api/courses/{course_id}").json()["lessons"][0]["completed"]
    client.post("/api/auth/logout")
    verified = client.get(f"/api/certificates/{code.lower()}").json()
    assert (
        verified["holder"] == "student" and verified["course_title"] == COURSE["title"]
    )
    assert client.get("/api/certificates/NOT-A-CODE").status_code == 404
    assert [
        row["code"] for row in client.get("/api/profiles/student/certificates").json()
    ] == [code]
    become(client, "student")
    client.put("/api/account/settings", json={"visibility": "private"})
    assert len(client.get("/api/profiles/student/certificates").json()) == 1
    client.post("/api/auth/logout")
    assert client.get("/api/profiles/student/certificates").status_code == 404


def test_worker_failures_and_timeouts_are_reported_without_losing_attempts(
    client, worker_db, monkeypatch
):
    _, _, exercise_id = authored_course(client)
    become(client, "student")
    ids = []
    for outcome in (ValueError("cluster unavailable"), asyncio.TimeoutError()):
        attempt = client.post(
            f"/api/exercises/{exercise_id}/attempts", json={"code": "1"}
        )
        with worker_db() as db:
            compute_worker.claim(db)
        compute_worker.fail("attempt", attempt.json()["id"], outcome)
        ids.append(attempt.json()["id"])
    first, second = (client.get(f"/api/exercise-attempts/{id}").json() for id in ids)
    assert first["status"] == "failed" and "cluster unavailable" in first["message"]
    assert "did not finish" in second["message"]
    # Infrastructure failures do not count; timeouts do.
    assert second["exercise"]["attempts"] == 1
    with worker_db() as db:
        row = db.get(ExerciseAttempt, ids[1])
        row.status = "running"
        db.commit()
        compute_worker.recover(db)
        assert db.get(ExerciseAttempt, ids[1]).status == "failed"


def test_open_exercise_in_notebook_uses_starter_code_and_practice_data(member, hub):
    with database() as db:
        exercise = db.scalar(
            select(CourseExercise).where(CourseExercise.title == "Filter and sort")
        )
        starter, checker = exercise.starter_code, exercise.checker
    assert (
        member.post(
            f"/api/notebook-drafts?exercise_id={exercise.id}&competition_id=1"
        ).status_code
        == 422
    )
    assert member.post("/api/notebook-drafts?exercise_id=999999").status_code == 404
    draft = member.post(f"/api/notebook-drafts?exercise_id={exercise.id}").json()["id"]
    hub.state = "ready"
    assert member.post(f"/api/notebook-drafts/{draft}/open").status_code == 200
    document = hub.files[f"/user/arena-2/api/contents/arena-draft-{draft}.ipynb"][
        "content"
    ]
    assert document["cells"][1]["source"] == starter
    assert document["metadata"]["arena_practice_inputs"] == ["wine-cultivar"]
    assert checker[:40] not in json.dumps(document)
    folder = (
        f"/user/arena-2/api/contents/workspaces/arena-draft-{draft}/input/wine-cultivar"
    )
    assert f"{folder}/train.csv" in hub.files
    assert f"{folder}/solution.csv" not in hub.files


def test_legacy_courses_and_progress_upgrade_in_place():
    from app.db import Base
    from app.migrations import run_migrations
    from app.models import ContentReceipt, CourseLesson, LessonProgress
    from app.seed import seed

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    lessons = json.dumps(
        [
            {"title": "Variables and types", "body": "Values.", "code": "x = 1"},
            {"title": "Lists and loops", "body": "Loops.", "code": ""},
            {"title": "Functions", "body": "Reuse.", "code": "def f(): pass"},
        ]
    )
    with engine.begin() as connection:
        for statement in (
            "CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(40) NOT NULL"
            " UNIQUE, password_hash TEXT NOT NULL, created_at VARCHAR)",
            "CREATE TABLE courses (id INTEGER PRIMARY KEY, title VARCHAR(160) NOT NULL,"
            " description TEXT NOT NULL, duration VARCHAR(40) NOT NULL,"
            " lessons TEXT NOT NULL)",
            "CREATE TABLE progress (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,"
            " course_id INTEGER NOT NULL, lesson_index INTEGER NOT NULL,"
            " UNIQUE (user_id, course_id, lesson_index))",
            "INSERT INTO users (id, username, password_hash) VALUES (1, 'arena', 'x:y'),"
            " (2, 'veteran', 'x:y')",
            "INSERT INTO progress (user_id, course_id, lesson_index) VALUES"
            " (2, 1, 0), (2, 1, 2), (2, 1, 9)",
        ):
            connection.execute(text(statement))
        connection.execute(
            text(
                "INSERT INTO courses VALUES (1, 'Python foundations', 'Kept', '25 min',"
                " :lessons)"
            ),
            {"lessons": lessons},
        )
    Base.metadata.create_all(engine)
    run_migrations(engine)
    columns = {column["name"] for column in inspect(engine).get_columns("courses")}
    assert {"status", "difficulty", "position", "owner_id"} <= columns
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    for _ in range(2):
        with factory() as db:
            seed(db)
    with factory() as db:
        rows = list(db.scalars(select(CourseLesson).order_by(CourseLesson.position)))
        assert [row.title for row in rows] == [
            "Variables and types",
            "Lists and loops",
            "Functions",
        ]
        assert rows[0].body.endswith("```python\nx = 1\n```")
        assert {row.lesson_id for row in db.scalars(select(LessonProgress))} == {
            rows[0].id,
            rows[2].id,
        }
        assert (
            len(
                list(
                    db.scalars(
                        select(CourseExercise).where(
                            CourseExercise.lesson_id.in_([row.id for row in rows])
                        )
                    )
                )
            )
            == 3
        )
        assert db.get(ContentReceipt, "learn-exercises-python-foundations-v1")
        status = db.execute(text("SELECT status, position FROM courses")).one()
        assert tuple(status) == ("published", 1)
    engine.dispose()
