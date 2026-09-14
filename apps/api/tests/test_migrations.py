from sqlalchemy import create_engine, func, inspect, select, text
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


def test_resource_versions_backfill_old_data_once(tmp_path):
    from app.db import DATA_DIR, Base
    from app.models import (
        ModelVariation,
        ResourceVersion,
        ResourceVersionFile,
        StoredFile,
    )
    from app.version_backfill import backfill_resource_versions

    engine = old_database()
    with engine.begin() as connection:
        for statement in (
            """CREATE TABLE model_cards (
                id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL,
                title VARCHAR(160) NOT NULL, description TEXT NOT NULL,
                framework VARCHAR(80) NOT NULL, license VARCHAR(80) NOT NULL,
                url TEXT NOT NULL, created_at VARCHAR)""",
            """CREATE TABLE artifact_versions (
                id INTEGER PRIMARY KEY, kind VARCHAR(20) NOT NULL,
                resource_id INTEGER NOT NULL, path VARCHAR(240) NOT NULL,
                storage_key VARCHAR(80) NOT NULL UNIQUE, size INTEGER NOT NULL,
                sha256 VARCHAR(64) NOT NULL, created_at VARCHAR)""",
            "INSERT INTO model_cards (id, owner_id, title, description, framework,"
            " license, url) VALUES (1, 1, 'Net', 'Kept', 'Torch', 'MIT', ''),"
            " (2, 1, 'Reference', 'Link only', 'Keras', 'MIT', 'https://x')",
            "INSERT INTO artifact_versions (id, kind, resource_id, path, storage_key,"
            " size, sha256) VALUES"
            " (1, 'datasets', 1, 'extra/old.txt', 'artifact-old', 3, 'x'),"
            " (2, 'datasets', 1, 'extra/old.txt', 'artifact-new', 3, 'y'),"
            " (3, 'models', 1, 'weights.pt', 'artifact-weights', 7, 'z')",
        ):
            connection.execute(text(statement))
    (DATA_DIR / "uploads").mkdir(exist_ok=True)
    (DATA_DIR / "uploads" / "a.csv").write_text("x\n1\n")
    Base.metadata.create_all(engine)  # As at startup: new tables, old tables unchanged.
    assert "0014_resource_versions_backfill" in run_migrations(engine)
    assert "card" in columns(engine, "model_cards")

    def snapshot():
        with sessionmaker(bind=engine)() as db:
            versions = db.scalars(
                select(ResourceVersion).order_by(ResourceVersion.id)
            ).all()
            files = db.execute(
                select(
                    ResourceVersionFile.path,
                    StoredFile.store,
                    StoredFile.storage_key,
                    StoredFile.size,
                )
                .join(StoredFile, StoredFile.id == ResourceVersionFile.file_id)
                .order_by(ResourceVersionFile.path)
            ).all()
            variations = db.execute(
                select(
                    ModelVariation.model_id,
                    ModelVariation.framework,
                    ModelVariation.slug,
                )
            ).all()
            return (
                [
                    (v.kind, v.resource_id, v.number, v.status, v.file_count)
                    for v in versions
                ],
                [tuple(row) for row in files],
                sorted(tuple(row) for row in variations),
                db.scalar(select(func.count()).select_from(StoredFile)),
            )

    before = snapshot()
    assert before[0] == [
        ("dataset", 1, 1, "published", 2),
        ("model", 1, 1, "published", 1),
    ]
    # The primary CSV keeps its uploads/ blob; only the newest supplemental file is used.
    assert before[1] == [
        ("a.csv", "uploads", "a.csv", 4),
        ("extra/old.txt", "artifacts", "artifact-new", 3),
        ("weights.pt", "artifacts", "artifact-weights", 7),
    ]
    assert before[2] == [(1, "pytorch", "default"), (2, "tensorflow", "default")]
    with engine.begin() as connection:
        assert backfill_resource_versions(connection) == {"datasets": 0, "models": 0}
    assert run_migrations(engine) == []
    with engine.begin() as connection:
        connection.execute(SchemaMigration.__table__.delete())
    assert len(run_migrations(engine)) == len(MIGRATIONS)
    assert snapshot() == before
    engine.dispose()


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
