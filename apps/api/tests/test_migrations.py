from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.migrations import MIGRATIONS, run_migrations
from app.models import Competition, Entry, SchemaMigration, Submission, User

OLD_SCHEMA = [
    """CREATE TABLE users (
        id INTEGER PRIMARY KEY,
        username VARCHAR(40) NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        created_at VARCHAR
    )""",
    """CREATE TABLE competitions (
        id INTEGER PRIMARY KEY,
        title VARCHAR(160) NOT NULL,
        description TEXT NOT NULL,
        category VARCHAR(80),
        metric VARCHAR(30),
        deadline VARCHAR NOT NULL,
        solution TEXT NOT NULL,
        prize VARCHAR(80)
    )""",
    """CREATE TABLE datasets (
        id INTEGER PRIMARY KEY,
        owner_id INTEGER NOT NULL,
        title VARCHAR(160) NOT NULL,
        description TEXT NOT NULL,
        tags VARCHAR(300),
        license VARCHAR(80),
        filename VARCHAR(255) NOT NULL,
        storage_key VARCHAR(80) NOT NULL,
        size INTEGER,
        created_at VARCHAR
    )""",
    """CREATE TABLE sessions (
        token_hash VARCHAR(64) PRIMARY KEY,
        user_id INTEGER NOT NULL,
        expires_at FLOAT NOT NULL
    )""",
    """CREATE TABLE entries (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL,
        competition_id INTEGER NOT NULL
    )""",
    """CREATE TABLE submissions (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL,
        competition_id INTEGER NOT NULL,
        filename VARCHAR(255) NOT NULL,
        score FLOAT NOT NULL,
        created_at VARCHAR
    )""",
    "INSERT INTO users (id, username, password_hash) VALUES (1, 'veteran', 'x:y')",
    "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES ('old', 1, 1.0)",
    "INSERT INTO competitions (id, title, description, deadline, solution)"
    " VALUES (1, 'Old', 'Kept', '2030-01-01T00:00:00+00:00', '{\"1\": 2}')",
    "INSERT INTO competitions (id, title, description, deadline, solution)"
    " VALUES (2, 'Practice', 'Kept', '9999-12-31T23:59:59+00:00', '{\"1\": 2}')",
    "INSERT INTO entries (id, user_id, competition_id) VALUES (1, 1, 1)",
    "INSERT INTO submissions (id, user_id, competition_id, filename, score)"
    " VALUES (1, 1, 1, 'old.csv', 0.5)",
    "INSERT INTO datasets (id, owner_id, title, description, filename, storage_key)"
    " VALUES (1, 1, 'Data', 'Kept', 'a.csv', 'a.csv')",
]


def old_database():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as connection:
        for statement in OLD_SCHEMA:
            connection.execute(text(statement))
    return engine


def columns(engine, table):
    return {column["name"] for column in inspect(engine).get_columns(table)}


def test_migrations_upgrade_an_old_schema_and_are_idempotent():
    engine = old_database()
    assert run_migrations(engine) == [id for id, _ in MIGRATIONS]
    assert {"role", "status"} <= columns(engine, "users")
    assert {"hidden", "hidden_reason"} <= columns(engine, "datasets")
    assert "solution_usage" in columns(engine, "competitions")
    # Absent tables are skipped; create_all builds them with every column.
    assert not inspect(engine).has_table("model_cards")

    assert run_migrations(engine) == []
    with sessionmaker(bind=engine)() as db:
        user = db.scalar(select(User))
        assert (user.username, user.role, user.status) == ("veteran", "user", "active")
        competition = db.get(Competition, 1)
        assert competition.description == "Kept"
        assert competition.solution_usage == "{}"
        assert (competition.rules_revision, competition.max_daily_submissions) == (1, 5)
        assert (
            competition.max_final_submissions == 2 and competition.finalized_at is None
        )
        assert db.get(Competition, 2).max_daily_submissions == 20
        # Existing participants count as having accepted the current rules.
        entry = db.get(Entry, 1)
        assert entry.rules_revision == 1 and entry.rules_accepted_at
        # Legacy scores stay public; private scores are empty until rescored.
        submission = db.get(Submission, 1)
        assert (submission.score, submission.private_score) == (0.5, None)
        assert submission.final_selected == 0
        assert len(db.scalars(select(SchemaMigration)).all()) == len(MIGRATIONS)
        # Losing the receipts must not re-add existing columns.
        db.execute(SchemaMigration.__table__.delete())
        db.commit()
    assert len(run_migrations(engine)) == len(MIGRATIONS)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT hidden FROM datasets")) == 0
        assert connection.scalar(text("SELECT auth_method FROM sessions")) == "password"
    engine.dispose()
