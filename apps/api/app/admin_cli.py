"""Operator commands for bootstrapping administrators without the web UI.

Run inside the API container:

  python -m app.admin_cli promote <username> [--role admin|host]
  python -m app.admin_cli demote <username>
  python -m app.admin_cli suspend <username>
  python -m app.admin_cli activate <username>

Changes are recorded in the audit log with the system as actor.
"""

import argparse
import sys

from sqlalchemy import select

from .db import Base, SessionLocal, engine
from .migrations import run_migrations
from .models import User
from .moderation import record

TARGETS = {
    "demote": ("role", "user"),
    "suspend": ("status", "suspended"),
    "activate": ("status", "active"),
}


def apply(db, action, username, role="admin"):
    user = db.scalar(select(User).where(User.username == username.strip().lower()))
    if not user:
        raise LookupError(f"No user named {username!r}")
    field, value = ("role", role) if action == "promote" else TARGETS[action]
    before = getattr(user, field)
    if before != value:
        record(
            db,
            None,
            f"user.{field}",
            "user",
            user.id,
            {
                "username": user.username,
                "from": before,
                "to": value,
                "source": "admin_cli",
            },
        )
        setattr(user, field, value)
    db.commit()
    return f"{user.username}: {field} {before} -> {value}"


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m app.admin_cli")
    parser.add_argument("action", choices=["promote", "demote", "suspend", "activate"])
    parser.add_argument("username")
    parser.add_argument(
        "--role",
        choices=["admin", "host"],
        default="admin",
        help="role granted by promote (default: admin)",
    )
    args = parser.parse_args(argv)
    Base.metadata.create_all(engine)
    run_migrations(engine)
    with SessionLocal() as db:
        try:
            print(apply(db, args.action, args.username, args.role))
        except LookupError as exc:
            print(exc, file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
