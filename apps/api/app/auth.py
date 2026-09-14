import hashlib
import hmac
import os
import secrets
import time
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session as DBSession
from .db import get_db
from .models import Session, User

COOKIE = "arena_session"
SUSPENDED = "This account is suspended. Contact an administrator for help."
# Password work is still performed against this for unknown or SSO-only accounts.
DUMMY_HASH = "0" * 32 + ":" + "0" * 128


def require_active(user):
    """Suspended accounts keep their data but cannot sign in or use credentials."""
    if user.status == "suspended":
        raise HTTPException(403, SUSPENDED)


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt.encode(), n=16384, r=8, p=1
    ).hex()
    return f"{salt}:{digest}"


def unusable_password():
    """A password_hash marker for accounts that sign in only through Keycloak."""
    return "!" + secrets.token_hex(16)


def has_usable_password(stored):
    return bool(stored) and not stored.startswith("!") and stored.count(":") == 1


def verify_password(password, stored):
    # Unusable markers never match, but still cost scrypt work so response
    # timing does not reveal which accounts are SSO-only.
    usable = has_usable_password(stored)
    salt, expected = (stored if usable else DUMMY_HASH).split(":")
    actual = hashlib.scrypt(
        password.encode(), salt=salt.encode(), n=16384, r=8, p=1
    ).hex()
    return usable and hmac.compare_digest(expected, actual)


def new_session(db, user, response, method="password"):
    token = secrets.token_urlsafe(32)
    db.add(
        Session(
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            user_id=user.id,
            expires_at=time.time() + 604800,
            auth_method=method,
        )
    )
    db.commit()
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        secure=os.getenv("COOKIE_SECURE", "false") == "true",
        samesite="strict",
        max_age=604800,
        path="/",
    )


def current_user(request: Request, db: DBSession = Depends(get_db)):
    authorization = request.headers.get("authorization")
    if authorization:
        from sqlalchemy import select
        from .models import ApiToken, now

        scheme, _, secret = authorization.partition(" ")
        credential = (
            db.scalar(
                select(ApiToken).where(
                    ApiToken.token_hash == hashlib.sha256(secret.encode()).hexdigest()
                )
            )
            if scheme.lower() == "bearer" and secret
            else None
        )
        if not credential or credential.expires_at <= time.time():
            raise HTTPException(401, "API token is invalid or expired")
        if (
            request.method not in {"GET", "HEAD", "OPTIONS"}
            and credential.scope != "read-write"
        ):
            raise HTTPException(403, "This API token is read-only")
        user = db.get(User, credential.user_id)
        if not user:
            raise HTTPException(401, "API token owner no longer exists")
        require_active(user)
        credential.last_used_at = now()
        db.commit()
        return user
    token = request.cookies.get(COOKIE)
    session = (
        db.get(Session, hashlib.sha256(token.encode()).hexdigest()) if token else None
    )
    if not session or session.expires_at < time.time():
        raise HTTPException(401, "Sign in to continue")
    user = db.get(User, session.user_id)
    if not user:
        raise HTTPException(401, "Session is no longer valid")
    require_active(user)
    return user
