"""Operator-only service announcements; run inside the API container."""

import argparse
from sqlalchemy import select
from .db import SessionLocal
from .models import User, ServiceNotice


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True)
    parser.add_argument("--body", required=True)
    parser.add_argument("--username", help="Omit to notify all users")
    args = parser.parse_args()
    if not 1 <= len(args.title) <= 160 or not 1 <= len(args.body) <= 5000:
        parser.error("Use a title of 1–160 characters and body of 1–5000 characters")
    with SessionLocal() as db:
        user = (
            db.scalar(select(User).where(User.username == args.username.lower()))
            if args.username
            else None
        )
        if args.username and not user:
            parser.error("Unknown username")
        db.add(
            ServiceNotice(
                user_id=user.id if user else None, title=args.title, body=args.body
            )
        )
        db.commit()
    print("Service notification published")


if __name__ == "__main__":
    main()
