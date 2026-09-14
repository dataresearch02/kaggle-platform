"""Administrator-controlled site settings stored as JSON values with defaults."""

import json
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from .db import get_db
from .models import SiteSetting

router = APIRouter(prefix="/api", tags=["Site"])

DEFAULTS = {
    "registration_open": True,
    # Administrators may always sign in locally as a break-glass path.
    "local_login_enabled": True,
    # "hosts": only host and admin roles create competitions and CSV benchmarks.
    "competition_creation": "hosts",
    # Markdown shown to every visitor; empty means no announcement.
    "announcement": "",
}
PUBLIC = ("registration_open", "local_login_enabled", "announcement")


def site_settings(db):
    values = dict(DEFAULTS)
    for row in db.scalars(select(SiteSetting).where(SiteSetting.key.in_(DEFAULTS))):
        try:
            values[row.key] = json.loads(row.value)
        except ValueError:
            pass  # Keep the default for an unreadable stored value.
    return values


def setting(db, key):
    return site_settings(db)[key]


class SettingsInput(BaseModel):
    registration_open: Optional[bool] = None
    local_login_enabled: Optional[bool] = None
    competition_creation: Optional[Literal["hosts", "everyone"]] = None
    announcement: Optional[str] = Field(default=None, max_length=5000)


def update_settings(db, data):
    """Stage changed values in the caller's transaction; return {key: {from, to}}."""
    current = site_settings(db)
    changes = {}
    for key, value in data.model_dump(exclude_none=True).items():
        if isinstance(value, str):
            value = value.strip()
        if current[key] == value:
            continue
        changes[key] = {"from": current[key], "to": value}
        db.merge(SiteSetting(key=key, value=json.dumps(value)))
    return changes


def can_create_competitions(db, user):
    return bool(
        user
        and user.status == "active"
        and (
            user.role in ("host", "admin")
            or setting(db, "competition_creation") == "everyone"
        )
    )


@router.get("/site")
def site(db=Depends(get_db)):
    from .oidc import enabled, label

    values = site_settings(db)
    return {
        **{key: values[key] for key in PUBLIC},
        # Deployment configuration rather than a stored setting.
        "oidc_enabled": enabled(),
        "oidc_label": label(),
    }
