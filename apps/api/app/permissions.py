"""Roles, account status and shared authorization helpers."""

from fastapi import Depends, HTTPException
from sqlalchemy import or_, true

from .auth import current_user
from .models import UserProfile

ROLES = ("user", "host", "admin")
STATUSES = ("active", "suspended")


def is_admin(user):
    return bool(user and user.role == "admin")


def can_manage(user, owner_id):
    """Owners manage their own content; administrators may manage anyone's."""
    return bool(
        user and (is_admin(user) or (owner_id is not None and user.id == owner_id))
    )


def require_admin(user=Depends(current_user)):
    if not is_admin(user):
        raise HTTPException(403, "Administrator access is required")
    return user


def owner_column(model):
    return model.user_id if model is UserProfile else model.owner_id


def not_hidden(model, user):
    """SQL filter: moderator-hidden rows remain visible to their owner and admins."""
    if is_admin(user):
        return true()
    return or_(model.hidden == 0, owner_column(model) == (user.id if user else -1))


def can_view(row, user):
    owner_id = row.user_id if isinstance(row, UserProfile) else row.owner_id
    return not row.hidden or can_manage(user, owner_id)
