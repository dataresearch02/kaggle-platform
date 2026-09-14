"""Accelerator choice, weekly GPU-hour quotas and shared GPU capacity.

Every GPU allocation is a GpuUsage row. Interactive GPU sessions stay open from start
until Arena stops the server or the Hub reports it stopped; background notebook runs
and exercise attempts are open for their actual Job duration. Competition commit and
benchmark Jobs that request EVALUATION_GPUS are recorded as well, so they hold
capacity, but they are not charged to anyone's quota. Open rows hold capacity: the
`gpu_capacity` admin setting is the number of GPUs Arena allocates at once, and one
live GPU session holds a whole card even while idle. Sessions, runs and attempts count
toward the owner's `gpu_weekly_hours`, which reset every Monday at 00:00 UTC.
"""

import contextlib
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select, update

from .auth import current_user
from .db import get_db
from .models import GpuUsage, SiteSetting, User
from .permissions import require_admin
from .site_settings import setting

router = APIRouter(prefix="/api", tags=["Compute"])
Accelerator = Literal["cpu", "gpu"]
# Usage kinds charged to the owner's weekly quota.
CHARGED = ("session", "run", "attempt")
RESET_WEEKDAY = 0  # Monday
LOCK_KEY = "gpu_allocation_lock"


def iso(moment):
    return datetime.fromtimestamp(moment, timezone.utc).isoformat()


def week_start(moment=None):
    """Start of the quota week containing `moment` (epoch seconds, UTC)."""
    moment = time.time() if moment is None else moment
    day = datetime.fromtimestamp(moment, timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return (day - timedelta(days=(day.weekday() - RESET_WEEKDAY) % 7)).timestamp()


def workload_gpus():
    """GPUs requested by one GPU session, run or attempt."""
    from .runtime_jobs import integer

    return integer("NOTEBOOK_GPU_COUNT", 1, minimum=1, maximum=8)


def gpu_supported(kind):
    """GPU sessions need KubeSpawner; background GPU work needs Kubernetes Jobs."""
    if kind == "session":
        return os.getenv("NOTEBOOK_SPAWNER", "docker") == "kubernetes"
    return os.getenv("EVALUATION_RUNTIME", "docker") == "kubernetes"


def quota_seconds(db):
    return float(setting(db, "gpu_weekly_hours")) * 3600


def capacity(db):
    return int(setting(db, "gpu_capacity"))


def used_seconds(db, user_id, at=None):
    """GPU-seconds charged to a user in the current quota week, up to `at`."""
    at = time.time() if at is None else at
    start = week_start(at)
    rows = db.execute(
        select(GpuUsage.started_at, GpuUsage.ended_at, GpuUsage.gpus).where(
            GpuUsage.user_id == user_id,
            GpuUsage.kind.in_(CHARGED),
            GpuUsage.started_at < at,
            or_(GpuUsage.ended_at.is_(None), GpuUsage.ended_at > start),
        )
    ).all()
    return sum(
        max(0.0, min(at if ended is None else ended, at) - max(started, start))
        * (gpus or 1)
        for started, ended, gpus in rows
    )


def in_use(db):
    return int(
        db.scalar(
            select(func.coalesce(func.sum(GpuUsage.gpus), 0)).where(
                GpuUsage.ended_at.is_(None)
            )
        )
        or 0
    )


def lock_pool(db):
    """Serialize allocation decisions across API replicas and the evaluation worker.

    The row is created by migration 0012; without it (a fresh test database) the
    single SQLite writer needs no lock.
    """
    db.scalar(select(SiteSetting).where(SiteSetting.key == LOCK_KEY).with_for_update())


def require_gpu(db, user, kind, check_capacity=True):
    """Refuse GPU work that is unavailable, over quota or, optionally, over capacity."""
    gpus = workload_gpus()
    limit = capacity(db)
    if not gpu_supported(kind) or limit <= 0:
        raise HTTPException(409, "GPUs are not available on this site. Choose CPU.")
    quota = quota_seconds(db)
    if used_seconds(db, user.id) >= quota:
        raise HTTPException(
            409,
            f"You have used your weekly GPU quota of {quota / 3600:g} hours. It resets"
            " on Monday at 00:00 UTC. Choose CPU to keep working.",
        )
    if check_capacity and in_use(db) + gpus > limit:
        raise HTTPException(
            409,
            "All GPUs are in use right now. Choose CPU, or try again after a GPU"
            " session or job finishes.",
        )
    return gpus


def open_usage(db, user_id, kind, ref_id=None, gpus=1):
    moment = time.time()
    row = GpuUsage(
        user_id=user_id,
        kind=kind,
        ref_id=ref_id,
        gpus=gpus,
        started_at=moment,
        last_seen_at=moment,
    )
    db.add(row)
    return row


def close_usage(db, kind, ref_id=None, user_id=None, ended_at=None):
    query = update(GpuUsage).where(GpuUsage.kind == kind, GpuUsage.ended_at.is_(None))
    if ref_id is not None:
        query = query.where(GpuUsage.ref_id == ref_id)
    if user_id is not None:
        query = query.where(GpuUsage.user_id == user_id)
    db.execute(query.values(ended_at=time.time() if ended_at is None else ended_at))


@contextlib.asynccontextmanager
async def gpu_job(factory, user_id, kind, ref_id, gpus):
    """Hold capacity while a commit or benchmark Job requests EVALUATION_GPUS."""
    if gpus:
        with factory() as db:
            open_usage(db, user_id, kind, ref_id, gpus)
            db.commit()
    try:
        yield
    finally:
        if gpus:
            with factory() as db:
                close_usage(db, kind, ref_id)
                db.commit()


def usage_json(db, user, at=None):
    at = time.time() if at is None else at
    start = week_start(at)
    quota = quota_seconds(db)
    used = used_seconds(db, user.id, at)
    limit = capacity(db)
    active = db.scalars(
        select(GpuUsage)
        .where(GpuUsage.user_id == user.id, GpuUsage.ended_at.is_(None))
        .order_by(GpuUsage.id)
    ).all()
    return {
        # The cluster is disconnected: no runtime has internet access.
        "internet": False,
        "gpu_available": {
            "session": gpu_supported("session") and limit > 0,
            "background": gpu_supported("job") and limit > 0,
        },
        "gpu_resource": os.getenv("GPU_RESOURCE_NAME", "nvidia.com/gpu"),
        "gpus_per_workload": workload_gpus(),
        "quota_hours": round(quota / 3600, 2),
        "used_hours": round(used / 3600, 2),
        "remaining_hours": round(max(0.0, quota - used) / 3600, 2),
        "week_start": iso(start),
        "resets_at": iso(start + 7 * 86400),
        "capacity": limit,
        "in_use": in_use(db),
        "active": [
            {
                "kind": row.kind,
                "ref_id": row.ref_id,
                "gpus": row.gpus,
                "started_at": iso(row.started_at),
            }
            for row in active
        ],
        "session_accelerator": (
            "gpu" if any(row.kind == "session" for row in active) else "cpu"
        ),
    }


@router.get("/compute/usage")
def my_usage(user=Depends(current_user), db=Depends(get_db)):
    return usage_json(db, user)


@router.get("/admin/compute/usage", dependencies=[Depends(require_admin)])
def all_usage(db=Depends(get_db)):
    """Per-user GPU usage this week, including anyone holding a GPU now."""
    at = time.time()
    start = week_start(at)
    quota = quota_seconds(db)
    user_ids = select(GpuUsage.user_id).where(
        or_(GpuUsage.ended_at.is_(None), GpuUsage.ended_at > start)
    )
    users = []
    for row in db.scalars(select(User).where(User.id.in_(user_ids)).limit(500)):
        used = used_seconds(db, row.id, at)
        users.append(
            {
                "user_id": row.id,
                "username": row.username,
                "used_hours": round(used / 3600, 2),
                "remaining_hours": round(max(0.0, quota - used) / 3600, 2),
                "active": list(
                    db.scalars(
                        select(GpuUsage.kind).where(
                            GpuUsage.user_id == row.id, GpuUsage.ended_at.is_(None)
                        )
                    )
                ),
            }
        )
    users.sort(key=lambda item: (-item["used_hours"], item["username"]))
    return {
        "capacity": capacity(db),
        "in_use": in_use(db),
        "quota_hours": round(quota / 3600, 2),
        "week_start": iso(start),
        "resets_at": iso(start + 7 * 86400),
        "users": users,
    }
