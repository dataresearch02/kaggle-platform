"""Retry file deletion after removing work, including when notebook servers are offline."""

import asyncio
import logging
from sqlalchemy import select

from .db import DATA_DIR, SessionLocal
from .models import User, WorkFileDeletion
from .notebook_drafts import user_lock
from .notebook_runtime import get_hub, hub_username


async def remove_work_file(task, db, hub=None):
    if task.kind == "upload":
        (DATA_DIR / "uploads" / task.path).unlink(missing_ok=True)
    elif task.kind == "benchmark-run":
        import re
        import shutil

        if not re.fullmatch(r"benchmark-\d+-[0-9a-f]+", task.path):
            raise ValueError("Invalid benchmark run directory")
        directory = DATA_DIR / "evaluations" / task.path
        if directory.is_symlink():
            directory.unlink()
        elif directory.exists():
            shutil.rmtree(directory)
    elif task.kind == "artifact":
        (DATA_DIR / "artifacts" / task.path).unlink(missing_ok=True)
    elif task.kind == "discussion-image":
        (DATA_DIR / "discussion-images" / task.path).unlink(missing_ok=True)
    elif task.kind == "notebook-output":
        from .models import NotebookOutput

        # Multiple immutable snapshots may share the same physical bytes.
        if not db.scalar(
            select(NotebookOutput.id)
            .where(NotebookOutput.storage_key == task.path)
            .limit(1)
        ):
            (DATA_DIR / "notebook-outputs" / task.path).unlink(missing_ok=True)
    else:
        user = db.get(User, task.owner_id)
        hub = hub or get_hub()
        if (await hub.status(user))["state"] != "ready":
            return False
        base = f"/user/{hub_username(user)}/api"
        sessions = hub.expect(
            await hub.request("GET", base + "/sessions", contents=True)
        ).json()
        for session in sessions:
            if session.get("path") == task.path:
                hub.expect(
                    await hub.request(
                        "DELETE", base + "/sessions/" + session["id"], contents=True
                    ),
                    (204, 404),
                )
        hub.expect(
            await hub.request("DELETE", base + "/contents/" + task.path, contents=True),
            (204, 404),
        )
    db.delete(task)
    db.commit()
    return True


async def cleanup_work_files():
    while True:
        await asyncio.sleep(30)
        try:
            with SessionLocal() as db:
                ids = list(
                    db.scalars(
                        select(WorkFileDeletion.id).order_by(WorkFileDeletion.id)
                    )
                )
                for id in ids:
                    task = db.get(WorkFileDeletion, id)
                    if not task:
                        continue
                    try:
                        async with user_lock(task.owner_id):
                            task = db.scalar(
                                select(WorkFileDeletion)
                                .where(WorkFileDeletion.id == id)
                                .with_for_update(skip_locked=True)
                            )
                            if task:
                                await remove_work_file(task, db)
                            db.rollback()
                    except Exception:
                        db.rollback()
                        logging.getLogger(__name__).warning(
                            "Work file cleanup deferred; will retry", exc_info=True
                        )
        except Exception:
            logging.getLogger(__name__).exception("Work cleanup failed; will retry")
