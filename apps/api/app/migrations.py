"""Ordered, idempotent schema migrations run at startup after `create_all`.

`Base.metadata.create_all` creates missing tables but never alters existing ones.
Each migration inspects the live schema and only adds what is absent, so upgrading
an existing database preserves its data and rerunning a migration is a no-op.
Append new migrations to MIGRATIONS; never reorder, rename or remove applied ones.
All DDL must work on SQLite and PostgreSQL.
"""

import logging
import re

from sqlalchemy import inspect, select, text

from .models import SchemaMigration, now

MODERATED_TABLES = (
    "datasets",
    "notebooks",
    "model_cards",
    "competition_posts",
    "content_replies",
    "notebook_comments",
    "user_profiles",
)


def add_columns(connection, table, columns):
    """Add (name, DDL) columns that the table lacks; skip absent tables."""
    inspector = inspect(connection)
    if not inspector.has_table(table):
        return  # create_all builds a new table with every current column.
    existing = {column["name"] for column in inspector.get_columns(table)}
    for name, ddl in columns:
        if name not in existing:
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def user_role_status(connection):
    add_columns(
        connection,
        "users",
        [
            ("role", "VARCHAR(10) NOT NULL DEFAULT 'user'"),
            ("status", "VARCHAR(12) NOT NULL DEFAULT 'active'"),
        ],
    )


def moderation_hidden(connection):
    for table in MODERATED_TABLES:
        add_columns(
            connection,
            table,
            [
                ("hidden", "INTEGER NOT NULL DEFAULT 0"),
                ("hidden_reason", "TEXT NOT NULL DEFAULT ''"),
            ],
        )


def competition_solution_usage(connection):
    add_columns(
        connection, "competitions", [("solution_usage", "TEXT NOT NULL DEFAULT '{}'")]
    )


def session_auth_method(connection):
    add_columns(
        connection,
        "sessions",
        [("auth_method", "VARCHAR(10) NOT NULL DEFAULT 'password'")],
    )


def competition_rules_acceptance(connection):
    add_columns(
        connection,
        "competitions",
        [
            ("rules", "TEXT NOT NULL DEFAULT ''"),
            ("rules_revision", "INTEGER NOT NULL DEFAULT 1"),
            ("rules_updated_at", "VARCHAR"),
        ],
    )
    add_columns(
        connection,
        "entries",
        [("rules_revision", "INTEGER"), ("rules_accepted_at", "VARCHAR")],
    )
    if inspect(connection).has_table("entries"):
        # Existing participants count as having accepted the current rules.
        connection.execute(
            text(
                "UPDATE entries SET rules_revision = (SELECT competitions.rules_revision"
                " FROM competitions WHERE competitions.id = entries.competition_id),"
                " rules_accepted_at = :now WHERE rules_revision IS NULL"
            ),
            {"now": now()},
        )


def competition_timeline_limits(connection):
    add_columns(
        connection,
        "competitions",
        [
            ("entry_deadline", "VARCHAR"),
            ("merger_deadline", "VARCHAR"),
            ("max_daily_submissions", "INTEGER NOT NULL DEFAULT 5"),
            ("max_final_submissions", "INTEGER NOT NULL DEFAULT 2"),
        ],
    )
    if inspect(connection).has_table("competitions"):
        # Practice competitions and CSV benchmarks (no deadline) allow 20 a day.
        connection.execute(
            text(
                "UPDATE competitions SET max_daily_submissions = 20"
                " WHERE deadline LIKE '9999-%'"
            )
        )


def submission_private_scores(connection):
    add_columns(
        connection,
        "competitions",
        [("metric_k", "INTEGER"), ("finalized_at", "VARCHAR")],
    )
    # Legacy scores stay public; private scores stay empty until rescored.
    add_columns(
        connection,
        "submissions",
        [
            ("private_score", "FLOAT"),
            ("final_selected", "INTEGER NOT NULL DEFAULT 0"),
        ],
    )


def drop_not_null(connection, table, column):
    """Make an existing column nullable. SQLite cannot alter columns, so the table
    is rebuilt from its own definition with the constraint removed."""
    inspector = inspect(connection)
    if not inspector.has_table(table):
        return
    columns = [row["name"] for row in inspector.get_columns(table)]
    if column not in columns or next(
        row["nullable"] for row in inspector.get_columns(table) if row["name"] == column
    ):
        return
    if connection.dialect.name != "sqlite":
        connection.execute(
            text(f"ALTER TABLE {table} ALTER COLUMN {column} DROP NOT NULL")
        )
        return
    definition = connection.scalar(
        text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = :name"),
        {"name": table},
    )
    definition, changed = re.subn(
        rf"([\"`]?\b{column}\b[\"`]?\s+\w+)\s+NOT\s+NULL",
        r"\1",
        definition,
        count=1,
        flags=re.IGNORECASE,
    )
    if not changed:
        raise RuntimeError(f"Cannot find the NOT NULL constraint on {table}.{column}")
    indexes = connection.scalars(
        text(
            "SELECT sql FROM sqlite_master WHERE type = 'index'"
            " AND tbl_name = :name AND sql IS NOT NULL"
        ),
        {"name": table},
    ).all()
    rebuilt = f"{table}__rebuild"
    connection.execute(
        text(
            re.sub(
                rf"CREATE TABLE\s+[\"`]?{table}[\"`]?",
                f"CREATE TABLE {rebuilt}",
                definition,
                count=1,
            )
        )
    )
    names = ", ".join(f'"{name}"' for name in columns)
    connection.execute(
        text(f"INSERT INTO {rebuilt} ({names}) SELECT {names} FROM {table}")
    )
    connection.execute(text(f"DROP TABLE {table}"))
    connection.execute(text(f"ALTER TABLE {rebuilt} RENAME TO {table}"))
    for statement in indexes:
        connection.execute(text(statement))


def community_columns(connection):
    # Topics may belong to a forum, dataset or model instead of a competition.
    drop_not_null(connection, "competition_posts", "competition_id")
    add_columns(
        connection,
        "competition_posts",
        [
            ("scope", "VARCHAR(20) NOT NULL DEFAULT 'competition'"),
            ("scope_id", "INTEGER"),
            ("edited_at", "VARCHAR"),
            ("deleted_at", "VARCHAR"),
        ],
    )
    for table in ("content_replies", "notebook_comments"):
        add_columns(
            connection, table, [("edited_at", "VARCHAR"), ("deleted_at", "VARCHAR")]
        )
    add_columns(
        connection,
        "competition_topic_settings",
        [("locked", "INTEGER NOT NULL DEFAULT 0")],
    )
    if inspect(connection).has_table("competition_posts"):
        connection.execute(
            text(
                "UPDATE competition_posts SET scope_id = competition_id"
                " WHERE scope = 'competition' AND scope_id IS NULL"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_competition_posts_scope"
                " ON competition_posts (scope, scope_id)"
            )
        )


DEFAULT_FORUMS = (
    ("general", "General", "Anything about data science, machine learning and Arena."),
    (
        "getting-started",
        "Getting Started",
        "New here? Introduce yourself and ask for a first step.",
    ),
    (
        "questions-answers",
        "Questions & Answers",
        "Ask technical questions and help others.",
    ),
    ("datasets", "Datasets", "Find, request and discuss datasets."),
    ("notebooks", "Notebooks", "Share techniques, code and notebook tips."),
    (
        "product-feedback",
        "Product Feedback",
        "Report problems and suggest improvements to Arena.",
    ),
)


def ensure_default_forums(connection):
    """Create the default forums once; administrators may later rename or archive them."""
    from .models import Forum

    table = Forum.__table__
    if not inspect(connection).has_table("forums") or connection.scalar(
        select(table.c.id).limit(1)
    ):
        return
    for position, (slug, title, description) in enumerate(DEFAULT_FORUMS):
        connection.execute(
            table.insert().values(
                slug=slug,
                title=title,
                description=description,
                position=position,
                archived=0,
                created_at=now(),
            )
        )


def legacy_discussions_to_forum(connection):
    """Copy legacy discussions and their comments into the General forum.

    The legacy rows are kept; legacy_discussion_map records each copy so reruns
    skip them. Replies and reactions on legacy items move to the new topics.
    """
    from .models import CompetitionPost, ContentReply, Forum, LegacyDiscussionMap

    inspector = inspect(connection)
    needed = (
        "forums",
        "discussions",
        "comments",
        "competition_posts",
        "content_replies",
        "legacy_discussion_map",
    )
    if not all(inspector.has_table(name) for name in needed):
        return
    ensure_default_forums(connection)
    forum = Forum.__table__
    general = connection.scalar(
        select(forum.c.id).where(forum.c.slug == "general")
    ) or connection.scalar(select(forum.c.id).order_by(forum.c.position).limit(1))
    mapping = LegacyDiscussionMap.__table__
    posts, replies = CompetitionPost.__table__, ContentReply.__table__

    def mapped(kind):
        return dict(
            connection.execute(
                select(mapping.c.legacy_id, mapping.c.new_id).where(
                    mapping.c.kind == kind
                )
            ).all()
        )

    topics = mapped("discussion")
    for row in connection.execute(
        text(
            "SELECT id, owner_id, title, body, created_at FROM discussions ORDER BY id"
        )
    ).all():
        if row.id in topics:
            continue
        new_id = connection.execute(
            posts.insert().values(
                competition_id=None,
                scope="forum",
                scope_id=general,
                owner_id=row.owner_id,
                title=row.title,
                body=row.body,
                created_at=row.created_at or now(),
                hidden=0,
                hidden_reason="",
            )
        ).inserted_primary_key[0]
        connection.execute(
            mapping.insert().values(kind="discussion", legacy_id=row.id, new_id=new_id)
        )
        topics[row.id] = new_id
    comments = mapped("comment")
    for row in connection.execute(
        text(
            "SELECT id, discussion_id, owner_id, body, created_at FROM comments"
            " ORDER BY id"
        )
    ).all():
        if row.id in comments or row.discussion_id not in topics:
            continue
        new_id = connection.execute(
            replies.insert().values(
                target_kind="competition-post",
                target_id=topics[row.discussion_id],
                owner_id=row.owner_id,
                body=row.body,
                created_at=row.created_at or now(),
                hidden=0,
                hidden_reason="",
            )
        ).inserted_primary_key[0]
        connection.execute(
            mapping.insert().values(kind="comment", legacy_id=row.id, new_id=new_id)
        )
        comments[row.id] = new_id
    moves = [
        ("discussion", "competition-post", topics),
        ("discussion-comment", "competition-comment", comments),
    ]
    for table in ("content_replies", "content_reactions"):
        if not inspector.has_table(table):
            continue
        for old_kind, new_kind, ids in moves:
            for legacy_id, new_id in ids.items():
                connection.execute(
                    text(
                        f"UPDATE {table} SET target_kind = :new_kind, target_id = :new_id"
                        " WHERE target_kind = :old_kind AND target_id = :legacy_id"
                    ),
                    {
                        "new_kind": new_kind,
                        "new_id": new_id,
                        "old_kind": old_kind,
                        "legacy_id": legacy_id,
                    },
                )


def community_backfill(connection):
    """Topic likes become votes (never self-votes) and topic authors watch their topics."""
    inspector = inspect(connection)
    if not all(
        inspector.has_table(name)
        for name in ("competition_posts", "content_reactions", "votes", "topic_watches")
    ):
        return
    connection.execute(
        text(
            "INSERT INTO votes (target_kind, target_id, user_id, created_at)"
            " SELECT 'competition-post', r.target_id, r.user_id, :now"
            " FROM content_reactions r JOIN competition_posts p ON p.id = r.target_id"
            " WHERE r.target_kind = 'competition-post' AND r.reaction = 'like'"
            " AND r.user_id <> p.owner_id AND NOT EXISTS (SELECT 1 FROM votes v"
            " WHERE v.target_kind = 'competition-post' AND v.target_id = r.target_id"
            " AND v.user_id = r.user_id)"
        ),
        {"now": now()},
    )
    connection.execute(
        text(
            "INSERT INTO topic_watches (post_id, user_id)"
            " SELECT p.id, p.owner_id FROM competition_posts p WHERE NOT EXISTS"
            " (SELECT 1 FROM topic_watches w WHERE w.post_id = p.id"
            " AND w.user_id = p.owner_id)"
        )
    )


def course_authoring(connection):
    """Authoring columns for courses. Existing courses stay published, in id order.

    Lesson rows, lesson progress and seeded exercises are created from the legacy
    lesson JSON by the idempotent learn_content.ensure_learning_content backfill.
    """
    add_columns(
        connection,
        "courses",
        [
            ("owner_id", "INTEGER"),
            ("difficulty", "VARCHAR(20) NOT NULL DEFAULT 'beginner'"),
            ("status", "VARCHAR(12) NOT NULL DEFAULT 'published'"),
            ("position", "INTEGER NOT NULL DEFAULT 0"),
            ("created_at", "VARCHAR"),
            ("updated_at", "VARCHAR"),
            ("published_at", "VARCHAR"),
        ],
    )
    if inspect(connection).has_table("courses"):
        connection.execute(
            text(
                "UPDATE courses SET position = id,"
                " published_at = COALESCE(published_at, :now)"
                " WHERE position = 0 AND status = 'published'"
            ),
            {"now": now()},
        )


def gpu_allocation_lock(connection):
    """A settings row that GPU allocation locks (SELECT ... FOR UPDATE); see compute.py."""
    if not inspect(connection).has_table("site_settings"):
        return
    if connection.scalar(
        text("SELECT 1 FROM site_settings WHERE key = 'gpu_allocation_lock'")
    ):
        return
    connection.execute(
        text(
            "INSERT INTO site_settings (key, value, updated_at)"
            " VALUES ('gpu_allocation_lock', '0', :now)"
        ),
        {"now": now()},
    )


def resource_versions_schema(connection):
    """Model cards gain Markdown; file sizes may exceed 2 GiB on PostgreSQL.

    The version, upload and quota tables are new, so create_all builds them.
    SQLite INTEGER columns already hold 64-bit values.
    """
    add_columns(connection, "model_cards", [("card", "TEXT NOT NULL DEFAULT ''")])
    if connection.dialect.name != "postgresql":
        return
    inspector = inspect(connection)
    for table in ("datasets", "artifact_versions"):
        if inspector.has_table(table):
            connection.execute(
                text(f"ALTER TABLE {table} ALTER COLUMN size TYPE BIGINT")
            )


def resource_versions_backfill(connection):
    """Existing datasets and models become version 1; see version_backfill.py."""
    from .version_backfill import backfill_resource_versions

    result = backfill_resource_versions(connection)
    logging.getLogger(__name__).info("Versioned existing resources: %s", result)


MIGRATIONS = (
    ("0001_user_role_status", user_role_status),
    ("0002_moderation_hidden", moderation_hidden),
    ("0003_competition_solution_usage", competition_solution_usage),
    ("0004_session_auth_method", session_auth_method),
    ("0005_competition_rules_acceptance", competition_rules_acceptance),
    ("0006_competition_timeline_limits", competition_timeline_limits),
    ("0007_submission_private_scores", submission_private_scores),
    ("0008_community_columns", community_columns),
    ("0009_legacy_discussions_to_forum", legacy_discussions_to_forum),
    ("0010_community_backfill", community_backfill),
    ("0011_course_authoring", course_authoring),
    ("0012_gpu_allocation_lock", gpu_allocation_lock),
    ("0013_resource_versions_schema", resource_versions_schema),
    ("0014_resource_versions_backfill", resource_versions_backfill),
)


def run_migrations(engine):
    """Apply pending migrations, each in its own transaction. Returns applied ids."""
    SchemaMigration.__table__.create(engine, checkfirst=True)
    applied = []
    for id, migrate in MIGRATIONS:
        with engine.begin() as connection:
            if connection.scalar(
                select(SchemaMigration.id).where(SchemaMigration.id == id)
            ):
                continue
            migrate(connection)
            connection.execute(
                SchemaMigration.__table__.insert().values(id=id, applied_at=now())
            )
        applied.append(id)
        logging.getLogger(__name__).info("Applied schema migration %s", id)
    return applied
