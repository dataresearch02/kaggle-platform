"""Ordered, idempotent schema migrations run at startup after `create_all`.

`Base.metadata.create_all` creates missing tables but never alters existing ones.
Each migration inspects the live schema and only adds what is absent, so upgrading
an existing database preserves its data and rerunning a migration is a no-op.
Append new migrations to MIGRATIONS; never reorder, rename or remove applied ones.
All DDL must work on SQLite and PostgreSQL.
"""

import logging

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


MIGRATIONS = (
    ("0001_user_role_status", user_role_status),
    ("0002_moderation_hidden", moderation_hidden),
    ("0003_competition_solution_usage", competition_solution_usage),
    ("0004_session_auth_method", session_auth_method),
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
