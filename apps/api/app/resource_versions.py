"""Numbered, immutable dataset and model versions with file browsing and previews.

A dataset has versions 1, 2, ... A model has variations (framework plus a slug such
as "base"), and each variation has its own numbered versions. A version is a set of
files, each a relative path pointing at a stored blob (see file_store.py). Owners and
administrators stage files in one draft per dataset or variation, optionally carrying
over the previous version's files, then publish it with a note; publishing assigns
the next number. Numbers are never reused: deleting a version keeps a "deleted" row
so a notebook pinned to it fails clearly instead of reading different files.

Visibility follows the parent: dataset privacy, sharing and moderation, or model
moderation. Drafts are visible only to people who can manage the parent.

Legacy compatibility: `datasets.filename/storage_key/size` always describe a CSV of
the latest version (empty when it has none), so old download links, profiles and
`arena_inputs` notebook references read the latest data.
"""

import csv
import io
import json
import os
import re
from pathlib import PurePosixPath
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from .auth import current_user
from .code_pages import optional_user
from .dataset_access import readable as readable_dataset
from .db import get_db
from .file_previews import IMAGE_BYTES, file_type, image_type, preview
from .file_store import download_name, open_blob
from .models import (
    Dataset,
    DatasetAccess,
    DatasetProfile,
    ModelCard,
    ModelVariation,
    ResourceVersion,
    ResourceVersionFile,
    StoredFile,
    User,
    now,
)
from .moderation import record
from .pagination import Page, page, set_total, window
from .permissions import can_manage, can_view
from .storage_quotas import release_files
from .version_backfill import FRAMEWORKS

router = APIRouter(prefix="/api", tags=["Versions"])
RESOURCE_KINDS = {"datasets": "dataset", "models": "model"}
MAX_FILES = 10_000
PROFILE_BYTES = 64 * 1024 * 1024


def parent(db, kind, id, user, write=False):
    """The dataset or model: readable by the user, or manageable (and locked)."""
    model = Dataset if kind == "dataset" else ModelCard
    if write:
        row = db.scalar(select(model).where(model.id == id).with_for_update())
        if not row or not can_manage(user, row.owner_id):
            raise HTTPException(404, f"Your {kind} was not found")
        return row
    if kind == "dataset":
        return readable_dataset(db, id, user)
    row = db.get(ModelCard, id)
    if not row or not can_view(row, user):
        raise HTTPException(404, "Model not found")
    return row


def scope_variation(db, kind, id, variation_id):
    if kind == "dataset":
        return 0
    variation = db.get(ModelVariation, variation_id)
    if not variation or variation.model_id != id:
        raise HTTPException(404, "Model variation not found")
    return variation.id


def in_scope(kind, id, variation_id):
    return select(ResourceVersion).where(
        ResourceVersion.kind == kind,
        ResourceVersion.resource_id == id,
        ResourceVersion.variation_id == variation_id,
    )


def published(kind, id, variation_id=0):
    return in_scope(kind, id, variation_id).where(ResourceVersion.status == "published")


def latest(db, kind, id, variation_id=0):
    return db.scalar(
        published(kind, id, variation_id)
        .order_by(ResourceVersion.number.desc())
        .limit(1)
    )


def draft_of(db, kind, id, variation_id=0):
    return db.scalar(
        in_scope(kind, id, variation_id)
        .where(ResourceVersion.status == "draft")
        .limit(1)
    )


def find_version(db, kind, id, variation_id, ref, user, row):
    """A published version by number or "latest", or the draft for managers."""
    if ref == "draft":
        version = (
            draft_of(db, kind, id, variation_id)
            if can_manage(user, row.owner_id)
            else None
        )
    elif ref == "latest":
        version = latest(db, kind, id, variation_id)
    elif ref.isdigit() and len(ref) < 10:
        version = db.scalar(
            in_scope(kind, id, variation_id).where(ResourceVersion.number == int(ref))
        )
        if version and version.status == "deleted":
            raise HTTPException(404, f"Version {ref} was deleted")
    else:
        version = None
    if not version or version.status not in ("published", "draft"):
        raise HTTPException(404, "Version not found")
    return version


def members(version_id, q=""):
    query = (
        select(ResourceVersionFile, StoredFile)
        .join(StoredFile, StoredFile.id == ResourceVersionFile.file_id)
        .where(ResourceVersionFile.version_id == version_id)
    )
    if q:
        query = query.where(
            ResourceVersionFile.path.icontains(q[:240], autoescape=True)
        )
    return query.order_by(ResourceVersionFile.path)


def file_json(member, stored):
    kind = file_type(member.path)
    return {
        "id": member.id,
        "path": member.path,
        "name": PurePosixPath(member.path).name,
        "size": stored.size,
        "sha256": stored.sha256,
        "type": kind,
        "previewable": kind not in ("binary", "parquet", "unsafe"),
        "created_at": stored.created_at,
    }


def version_json(db, version):
    creator = db.get(User, version.creator_id) if version.creator_id else None
    return {
        "id": version.id,
        "number": version.number,
        "status": version.status,
        "note": version.note,
        "creator": creator.username if creator else None,
        "file_count": version.file_count,
        "total_size": version.total_size,
        "created_at": version.created_at,
        "published_at": version.published_at,
    }


def refresh_counts(db, version):
    db.flush()
    count, total = db.execute(
        select(
            func.count(ResourceVersionFile.id),
            func.coalesce(func.sum(StoredFile.size), 0),
        )
        .join(StoredFile, StoredFile.id == ResourceVersionFile.file_id)
        .where(ResourceVersionFile.version_id == version.id)
    ).one()
    version.file_count, version.total_size = int(count), int(total)


def next_number(db, kind, id, variation_id):
    # Deleted versions keep their number, so it is never reused.
    return (
        db.scalar(
            select(func.max(ResourceVersion.number)).where(
                ResourceVersion.kind == kind,
                ResourceVersion.resource_id == id,
                ResourceVersion.variation_id == variation_id,
            )
        )
        or 0
    ) + 1


def csv_profile(stored, previous):
    """Column names, types and missing counts from a bounded read of a CSV blob.

    Files up to 64 MiB are read fully; larger files are sampled from their start and
    report a row count of -1 (unknown). Column descriptions are kept by name.
    """
    descriptions = {
        column.get("name"): column.get("description", "") for column in previous
    }
    try:
        with open_blob(stored.store, stored.storage_key) as raw:
            text = io.TextIOWrapper(
                raw, encoding="utf-8-sig", errors="replace", newline=""
            )
            reader = csv.reader(text)
            columns = [
                {
                    "name": name[:200],
                    "type": "number",
                    "missing": 0,
                    "description": descriptions.get(name[:200], ""),
                }
                for name in next(reader, [])[:500]
            ]
            count, complete = 0, True
            for row in reader:
                count += 1
                if count % 1000 == 0 and raw.tell() > PROFILE_BYTES:
                    complete = False
                    break
                for column, value in zip(columns, row):
                    if value.strip().lower() in ("", "na", "nan", "null"):
                        column["missing"] += 1
                    elif column["type"] == "number":
                        try:
                            float(value)
                        except ValueError:
                            column["type"] = "text"
        return json.dumps(columns), count if complete else -1
    except (OSError, ValueError, csv.Error):
        return "[]", 0


def sync_primary(db, dataset):
    """Point the legacy dataset fields at a CSV of the latest version, if any."""
    version = latest(db, "dataset", dataset.id)
    choice = None
    if version:
        csv_files = members(version.id).where(
            func.lower(ResourceVersionFile.path).like("%.csv")
        )
        choice = db.execute(
            csv_files.where(ResourceVersionFile.path == dataset.filename)
        ).first() or (db.execute(csv_files.limit(1)).first())
    profile = db.get(DatasetProfile, dataset.id)
    if not profile:
        profile = DatasetProfile(
            dataset_id=dataset.id, sha256="", columns_json="[]", row_count=0
        )
        db.add(profile)
    if not choice:
        dataset.filename, dataset.storage_key, dataset.size = "", "", 0
        profile.sha256, profile.columns_json, profile.row_count = "", "[]", 0
        return
    member, stored = choice
    if dataset.storage_key == stored.storage_key and dataset.filename == member.path:
        return
    dataset.filename, dataset.storage_key, dataset.size = (
        member.path,
        stored.storage_key,
        stored.size,
    )
    profile.sha256 = stored.sha256
    profile.columns_json, profile.row_count = csv_profile(
        stored, json.loads(profile.columns_json or "[]")
    )


def attach_file(db, version, path, file_id, cleanup_owner):
    """Put a stored file at `path` in a draft, replacing and releasing any previous one."""
    existing = db.scalar(
        select(ResourceVersionFile).where(
            ResourceVersionFile.version_id == version.id,
            ResourceVersionFile.path == path,
        )
    )
    replaced = None
    if existing:
        replaced, existing.file_id = existing.file_id, file_id
        member = existing
    else:
        count = db.scalar(
            select(func.count())
            .select_from(ResourceVersionFile)
            .where(ResourceVersionFile.version_id == version.id)
        )
        if count >= MAX_FILES:
            raise HTTPException(422, f"A version can contain up to {MAX_FILES:,} files")
        member = ResourceVersionFile(version_id=version.id, path=path, file_id=file_id)
        db.add(member)
    refresh_counts(db, version)
    if replaced and replaced != file_id:
        release_files(db, [replaced], cleanup_owner)
    return member


def create_draft(db, kind, row, variation_id, user, carry_over=True):
    draft = draft_of(db, kind, row.id, variation_id)
    if draft:
        return draft
    draft = ResourceVersion(
        kind=kind,
        resource_id=row.id,
        variation_id=variation_id,
        status="draft",
        creator_id=user.id,
        created_at=now(),
    )
    db.add(draft)
    db.flush()
    base = latest(db, kind, row.id, variation_id) if carry_over else None
    if base:
        for member, _ in db.execute(members(base.id)).all():
            db.add(
                ResourceVersionFile(
                    version_id=draft.id, path=member.path, file_id=member.file_id
                )
            )
    refresh_counts(db, draft)
    return draft


def publish_draft(db, kind, row, version, note):
    from .uploads import ACTIVE, UploadSession

    if db.scalar(
        select(UploadSession.id)
        .where(UploadSession.version_id == version.id, UploadSession.status.in_(ACTIVE))
        .limit(1)
    ):
        raise HTTPException(
            409, "Finish or cancel the uploads into this draft before publishing"
        )
    refresh_counts(db, version)
    if not version.file_count:
        raise HTTPException(422, "Add at least one file before publishing a version")
    version.number = next_number(db, kind, row.id, version.variation_id)
    version.status, version.note, version.published_at = (
        "published",
        note.strip(),
        now(),
    )
    db.flush()
    if kind == "dataset":
        sync_primary(db, row)
    return version


def publish_files(db, kind, row, variation_id, files, note, user):
    """Publish {path: stored file id} directly as the next version."""
    version = ResourceVersion(
        kind=kind,
        resource_id=row.id,
        variation_id=variation_id,
        status="draft",
        creator_id=user.id if user else row.owner_id,
        created_at=now(),
    )
    db.add(version)
    db.flush()
    for path, file_id in sorted(files.items()):
        db.add(ResourceVersionFile(version_id=version.id, path=path, file_id=file_id))
    refresh_counts(db, version)
    version.number = next_number(db, kind, row.id, variation_id)
    version.status, version.note, version.published_at = "published", note, now()
    db.flush()
    if kind == "dataset":
        sync_primary(db, row)
    return version


def version_file_ids(db, version_ids):
    return list(
        db.scalars(
            select(ResourceVersionFile.file_id).where(
                ResourceVersionFile.version_id.in_(version_ids)
            )
        )
    )


def discard_draft(db, version, cleanup_owner):
    from .uploads import drop_sessions

    drop_sessions(db, [version.id])
    file_ids = version_file_ids(db, [version.id])
    db.execute(
        delete(ResourceVersionFile).where(ResourceVersionFile.version_id == version.id)
    )
    db.delete(version)
    db.flush()
    release_files(db, file_ids, cleanup_owner)


def delete_version(db, kind, row, version, cleanup_owner):
    if kind == "dataset" and not db.scalar(
        published(kind, row.id)
        .where(ResourceVersion.id != version.id)
        .with_only_columns(ResourceVersion.id)
        .limit(1)
    ):
        raise HTTPException(
            409, "A dataset needs at least one version; delete the dataset instead"
        )
    file_ids = version_file_ids(db, [version.id])
    db.execute(
        delete(ResourceVersionFile).where(ResourceVersionFile.version_id == version.id)
    )
    version.status, version.file_count, version.total_size = "deleted", 0, 0
    db.flush()
    if kind == "dataset":
        sync_primary(db, row)
    release_files(db, file_ids, cleanup_owner)


def delete_resource_versions(db, kind, id, cleanup_owner):
    """Remove every version, draft, upload and (for models) variation of a resource."""
    from .uploads import drop_sessions

    ids = list(
        db.scalars(
            select(ResourceVersion.id).where(
                ResourceVersion.kind == kind, ResourceVersion.resource_id == id
            )
        )
    )
    drop_sessions(db, ids)
    file_ids = version_file_ids(db, ids)
    db.execute(
        delete(ResourceVersionFile).where(ResourceVersionFile.version_id.in_(ids))
    )
    db.execute(delete(ResourceVersion).where(ResourceVersion.id.in_(ids)))
    if kind == "model":
        db.execute(delete(ModelVariation).where(ModelVariation.model_id == id))
    db.flush()
    return release_files(db, file_ids, cleanup_owner, keep_primary=False)


def writable_draft(db, version_id, user):
    """A draft version the user may upload into, with its locked parent row."""
    version = db.get(ResourceVersion, version_id)
    if not version or version.status != "draft":
        raise HTTPException(404, "Draft version not found")
    row = parent(db, version.kind, version.resource_id, user, write=True)
    db.refresh(version)
    if version.status != "draft":
        raise HTTPException(404, "Draft version not found")
    return version, row


def default_variation(db, model):
    variation = db.scalar(
        select(ModelVariation)
        .where(ModelVariation.model_id == model.id)
        .order_by(ModelVariation.id)
        .limit(1)
    )
    if not variation:
        from .version_backfill import framework_key

        variation = ModelVariation(
            model_id=model.id, framework=framework_key(model.framework), slug="default"
        )
        db.add(variation)
        db.flush()
    return variation


def add_legacy_file(db, kind, row, path, stored, user):
    """A single-request file upload (the /api/assets endpoint) becomes a new version
    that carries over the latest files and adds or replaces this path."""
    from .version_backfill import backfill_resource_versions

    backfill_resource_versions(db.connection())
    variation_id = 0 if kind == "dataset" else default_variation(db, row).id
    base = latest(db, kind, row.id, variation_id)
    files = (
        {
            member.path: member.file_id
            for member, _ in db.execute(members(base.id)).all()
        }
        if base
        else {}
    )
    files[path] = stored.id
    return publish_files(db, kind, row, variation_id, files, f"Uploaded {path}", user)


def slugify(title, fallback):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80] or fallback


def input_folder(kind, title, id, variation=None):
    """The folder notebooks read a source from, such as input/iris-dataset-4."""
    slug = slugify(title, kind)
    if variation is not None:
        slug = f"{slug}-{variation.framework}-{variation.slug}"
    return f"input/{slug}-{kind}-{id}"


LOADERS = {
    "pytorch": (
        (".pt", ".pth", ".bin", ".safetensors"),
        'import torch\nstate = torch.load(model_dir / "{name}", map_location="cpu", weights_only=True)',
    ),
    "tensorflow": (
        (".keras", ".h5"),
        'import keras\nmodel = keras.models.load_model(model_dir / "{name}")',
    ),
    "scikit-learn": (
        (".joblib", ".pkl"),
        'import joblib\nmodel = joblib.load(model_dir / "{name}")',
    ),
    "onnx": (
        (".onnx",),
        'import onnxruntime\nsession = onnxruntime.InferenceSession(str(model_dir / "{name}"))',
    ),
    "transformers": (
        (".json",),
        "from transformers import AutoModel\nmodel = AutoModel.from_pretrained(model_dir, local_files_only=True)",
    ),
    "gguf": (
        (".gguf",),
        '# Load with a GGUF runtime such as llama.cpp: model_dir / "{name}"',
    ),
}


def usage_snippet(folder, framework, paths):
    lines = [
        "from pathlib import Path",
        "",
        f'model_dir = Path("{folder}")',
        "for path in sorted(model_dir.rglob('*')):",
        "    if path.is_file():",
        "        print(path, path.stat().st_size)",
    ]
    suffixes, loader = LOADERS.get(framework, ((), ""))
    if loader:
        name = next(
            (path for path in paths if path.lower().endswith(suffixes)),
            "model" + suffixes[0],
        )
        lines += ["", loader.replace("{name}", name.replace('"', ""))]
    return "\n".join(lines) + "\n"


def variation_json(db, model, variation, user):
    newest = latest(db, "model", model.id, variation.id)
    folder = input_folder("model", model.title, model.id, variation)
    paths = (
        [member.path for member, _ in db.execute(members(newest.id).limit(20)).all()]
        if newest
        else []
    )
    return {
        "id": variation.id,
        "framework": variation.framework,
        "framework_label": FRAMEWORKS.get(variation.framework, variation.framework),
        "slug": variation.slug,
        "description": variation.description,
        "created_at": variation.created_at,
        "latest_version": version_json(db, newest) if newest else None,
        "version_count": db.scalar(
            published("model", model.id, variation.id).with_only_columns(
                func.count(ResourceVersion.id)
            )
        ),
        "has_draft": bool(
            can_manage(user, model.owner_id)
            and draft_of(db, "model", model.id, variation.id)
        ),
        "input_path": folder,
        "snippet": usage_snippet(folder, variation.framework, paths),
    }


def dataset_summary(db, dataset, user):
    newest = latest(db, "dataset", dataset.id)
    draft = (
        draft_of(db, "dataset", dataset.id)
        if can_manage(user, dataset.owner_id)
        else None
    )
    return {
        "latest_version": version_json(db, newest) if newest else None,
        "version_count": db.scalar(
            published("dataset", dataset.id).with_only_columns(
                func.count(ResourceVersion.id)
            )
        ),
        "draft_version": version_json(db, draft) if draft else None,
        "input_available": bool(newest and newest.file_count),
        "input_path": input_folder("dataset", dataset.title, dataset.id),
    }


def model_input_available(db, id):
    return bool(
        db.scalar(
            select(ResourceVersion.id)
            .where(
                ResourceVersion.kind == "model",
                ResourceVersion.resource_id == id,
                ResourceVersion.status == "published",
                ResourceVersion.file_count > 0,
            )
            .limit(1)
        )
    )


class DraftInput(BaseModel):
    # Start from the latest version's files instead of an empty file set.
    carry_over: bool = True


class PublishInput(BaseModel):
    note: str = Field(min_length=1, max_length=5000)


def audit(db, user, row, action, detail):
    """Record changes administrators make to other people's resources."""
    if user.id != row.owner_id:
        record(
            db,
            user,
            action,
            "dataset" if isinstance(row, Dataset) else "model",
            row.id,
            detail,
        )


def version_routes(kind, prefix):
    """Routes for dataset versions or model-variation versions (variation_id is 0 for datasets)."""
    label = kind.capitalize()

    @router.get(prefix + "/versions", tags=[label])
    def list_versions(
        id: int, variation_id: int = 0, user=Depends(optional_user), db=Depends(get_db)
    ):
        row = parent(db, kind, id, user)
        variation = scope_variation(db, kind, id, variation_id)
        statuses = (
            ["published", "draft"] if can_manage(user, row.owner_id) else ["published"]
        )
        rows = db.scalars(
            in_scope(kind, id, variation)
            .where(ResourceVersion.status.in_(statuses))
            .order_by(
                ResourceVersion.number.is_(None).desc(), ResourceVersion.number.desc()
            )
        )
        return [version_json(db, version) for version in rows]

    @router.get(prefix + "/versions/{ref}", tags=[label])
    def get_version(
        id: int,
        ref: str,
        variation_id: int = 0,
        user=Depends(optional_user),
        db=Depends(get_db),
    ):
        """`ref` is a version number, `latest` or (for managers) `draft`."""
        row = parent(db, kind, id, user)
        version = find_version(
            db, kind, id, scope_variation(db, kind, id, variation_id), ref, user, row
        )
        return version_json(db, version)

    @router.get(prefix + "/versions/{ref}/files", tags=[label])
    def list_files(
        id: int,
        ref: str,
        response: Response,
        variation_id: int = 0,
        q: str = Query("", max_length=240),
        pagination: Page = Depends(page),
        user=Depends(optional_user),
        db=Depends(get_db),
    ):
        row = parent(db, kind, id, user)
        version = find_version(
            db, kind, id, scope_variation(db, kind, id, variation_id), ref, user, row
        )
        query = members(version.id, q)
        set_total(
            response, db.scalar(query.with_only_columns(func.count()).order_by(None))
        )
        return [
            file_json(member, stored)
            for member, stored in db.execute(window(query, pagination))
        ]

    @router.post(prefix + "/versions", status_code=201, tags=[label])
    def start_draft(
        id: int,
        data: DraftInput = DraftInput(),
        variation_id: int = 0,
        user=Depends(current_user),
        db=Depends(get_db),
    ):
        """Create (or return the existing) draft for the next version."""
        row = parent(db, kind, id, user, write=True)
        draft = create_draft(
            db,
            kind,
            row,
            scope_variation(db, kind, id, variation_id),
            user,
            data.carry_over,
        )
        db.commit()
        return version_json(db, draft)

    @router.post(prefix + "/versions/draft/publish", tags=[label])
    def publish(
        id: int,
        data: PublishInput,
        variation_id: int = 0,
        user=Depends(current_user),
        db=Depends(get_db),
    ):
        row = parent(db, kind, id, user, write=True)
        draft = draft_of(db, kind, id, scope_variation(db, kind, id, variation_id))
        if not draft:
            raise HTTPException(404, "There is no draft version to publish")
        version = publish_draft(db, kind, row, draft, data.note)
        audit(
            db,
            user,
            row,
            "version.publish",
            {"number": version.number, "variation_id": version.variation_id},
        )
        from .progression import mark_related

        mark_related(db, kind, id)
        db.commit()
        return version_json(db, version)

    @router.delete(prefix + "/versions/draft", status_code=204, tags=[label])
    def discard(
        id: int, variation_id: int = 0, user=Depends(current_user), db=Depends(get_db)
    ):
        row = parent(db, kind, id, user, write=True)
        draft = draft_of(db, kind, id, scope_variation(db, kind, id, variation_id))
        if draft:
            discard_draft(db, draft, row.owner_id)
            db.commit()
        return Response(status_code=204)

    @router.delete(
        prefix + "/versions/draft/files/{file_id}", status_code=204, tags=[label]
    )
    def remove_draft_file(
        id: int,
        file_id: int,
        variation_id: int = 0,
        user=Depends(current_user),
        db=Depends(get_db),
    ):
        row = parent(db, kind, id, user, write=True)
        draft = draft_of(db, kind, id, scope_variation(db, kind, id, variation_id))
        member = db.get(ResourceVersionFile, file_id)
        if not draft or not member or member.version_id != draft.id:
            raise HTTPException(404, "Draft file not found")
        db.delete(member)
        refresh_counts(db, draft)
        release_files(db, [member.file_id], row.owner_id)
        db.commit()
        return Response(status_code=204)

    @router.delete(prefix + "/versions/{number}", status_code=204, tags=[label])
    def remove_version(
        id: int,
        number: int,
        variation_id: int = 0,
        user=Depends(current_user),
        db=Depends(get_db),
    ):
        """Delete a published version's files; its number is never reused."""
        row = parent(db, kind, id, user, write=True)
        version = db.scalar(
            published(kind, id, scope_variation(db, kind, id, variation_id)).where(
                ResourceVersion.number == number
            )
        )
        if not version:
            raise HTTPException(404, "Version not found")
        delete_version(db, kind, row, version, row.owner_id)
        audit(
            db,
            user,
            row,
            "version.delete",
            {"number": number, "variation_id": version.variation_id},
        )
        db.commit()
        return Response(status_code=204)


def file_context(db, kind, id, file_id, user):
    row = parent(db, kind, id, user)
    found = db.execute(
        select(ResourceVersionFile, StoredFile, ResourceVersion)
        .join(StoredFile, StoredFile.id == ResourceVersionFile.file_id)
        .join(ResourceVersion, ResourceVersion.id == ResourceVersionFile.version_id)
        .where(
            ResourceVersionFile.id == file_id,
            ResourceVersion.kind == kind,
            ResourceVersion.resource_id == id,
        )
    ).first()
    if (
        not found
        or found[2].status not in ("published", "draft")
        or (found[2].status == "draft" and not can_manage(user, row.owner_id))
    ):
        raise HTTPException(404, "File not found")
    return found


def stream_blob(
    stored, path, media_type="application/octet-stream", disposition="attachment"
):
    """Stream a blob with a sanitized filename; browsers never sniff or run it."""
    try:
        handle = open_blob(stored.store, stored.storage_key)
    except (OSError, ValueError):
        raise HTTPException(404, "File is unavailable")
    size = os.fstat(handle.fileno()).st_size

    def body():
        with handle:
            while chunk := handle.read(1024 * 1024):
                yield chunk

    name = download_name(path)
    fallback = name.encode("ascii", "replace").decode().replace("?", "_")
    return StreamingResponse(
        body(),
        media_type=media_type,
        headers={
            "Content-Length": str(size),
            "Content-Disposition": f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{quote(name)}",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": "private, no-store",
        },
    )


def preview_json(kind, id, member, stored):
    try:
        with open_blob(stored.store, stored.storage_key) as handle:
            result = preview(handle, member.path, os.fstat(handle.fileno()).st_size)
    except (OSError, ValueError):
        raise HTTPException(404, "File is unavailable")
    result.update(id=member.id, path=member.path)
    if result.get("format") == "image":
        plural = "datasets" if kind == "dataset" else "models"
        result["url"] = f"/api/{plural}/{id}/files/{member.id}/raw"
    return result


def file_routes(plural, kind):
    label = kind.capitalize()

    @router.get(f"/{plural}/{{id}}/files/{{file_id}}/download", tags=[label])
    def download_file(
        id: int, file_id: int, user=Depends(optional_user), db=Depends(get_db)
    ):
        member, stored, _ = file_context(db, kind, id, file_id, user)
        return stream_blob(stored, member.path)

    @router.get(f"/{plural}/{{id}}/files/{{file_id}}/preview", tags=[label])
    def preview_file(
        id: int, file_id: int, user=Depends(optional_user), db=Depends(get_db)
    ):
        member, stored, _ = file_context(db, kind, id, file_id, user)
        return preview_json(kind, id, member, stored)

    @router.get(f"/{plural}/{{id}}/files/{{file_id}}/raw", tags=[label])
    def raw_image(
        id: int, file_id: int, user=Depends(optional_user), db=Depends(get_db)
    ):
        """PNG, JPEG, GIF or WebP up to 20 MB whose bytes match the extension."""
        member, stored, _ = file_context(db, kind, id, file_id, user)
        try:
            with open_blob(stored.store, stored.storage_key) as handle:
                media_type = image_type(member.path, handle.read(16))
        except (OSError, ValueError):
            raise HTTPException(404, "File is unavailable")
        if (
            file_type(member.path) != "image"
            or not media_type
            or stored.size > IMAGE_BYTES
        ):
            raise HTTPException(
                415, "Only PNG, JPEG, GIF and WebP images up to 20 MB are shown inline"
            )
        return stream_blob(stored, member.path, media_type, "inline")


version_routes("dataset", "/datasets/{id}")
version_routes("model", "/models/{id}/variations/{variation_id}")
for plural, kind in RESOURCE_KINDS.items():
    file_routes(plural, kind)


class DatasetDraftInput(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=3, max_length=5000)
    tags: str = Field(default="", max_length=300)
    license: str = Field(default="CC0-1.0", max_length=80)


@router.post("/datasets/drafts", status_code=201, tags=["Dataset"])
def create_dataset(
    data: DatasetDraftInput, user=Depends(current_user), db=Depends(get_db)
):
    """A private dataset with an empty draft version; upload files, then publish."""
    from .main import public

    dataset = Dataset(
        owner_id=user.id,
        title=data.title.strip(),
        description=data.description,
        tags=data.tags,
        license=data.license,
        filename="",
        storage_key="",
        size=0,
    )
    db.add(dataset)
    db.flush()
    db.add(DatasetAccess(dataset_id=dataset.id, visibility="private"))
    db.add(
        DatasetProfile(dataset_id=dataset.id, sha256="", columns_json="[]", row_count=0)
    )
    draft = create_draft(db, "dataset", dataset, 0, user, carry_over=False)
    db.commit()
    return {**public(dataset, db), "draft_version": version_json(db, draft)}


Framework = Literal[tuple(FRAMEWORKS)]


class VariationInput(BaseModel):
    framework: Framework
    slug: str = Field(pattern=r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")
    description: str = Field(default="", max_length=2000)


@router.get("/models/{id}/variations", tags=["Model"])
def list_variations(id: int, user=Depends(optional_user), db=Depends(get_db)):
    model = parent(db, "model", id, user)
    return [
        variation_json(db, model, variation, user)
        for variation in db.scalars(
            select(ModelVariation)
            .where(ModelVariation.model_id == id)
            .order_by(ModelVariation.id)
        )
    ]


@router.post("/models/{id}/variations", status_code=201, tags=["Model"])
def create_variation(
    id: int, data: VariationInput, user=Depends(current_user), db=Depends(get_db)
):
    model = parent(db, "model", id, user, write=True)
    if db.scalar(
        select(ModelVariation.id).where(
            ModelVariation.model_id == id,
            ModelVariation.framework == data.framework,
            ModelVariation.slug == data.slug,
        )
    ):
        raise HTTPException(409, "This model already has that framework and variation")
    if (
        db.scalar(
            select(func.count())
            .select_from(ModelVariation)
            .where(ModelVariation.model_id == id)
        )
        >= 100
    ):
        raise HTTPException(422, "A model can have up to 100 variations")
    variation = ModelVariation(
        model_id=id,
        framework=data.framework,
        slug=data.slug,
        description=data.description,
    )
    db.add(variation)
    audit(
        db,
        user,
        model,
        "variation.create",
        {"framework": data.framework, "slug": data.slug},
    )
    db.commit()
    return variation_json(db, model, variation, user)


@router.delete(
    "/models/{id}/variations/{variation_id}", status_code=204, tags=["Model"]
)
def delete_variation(
    id: int, variation_id: int, user=Depends(current_user), db=Depends(get_db)
):
    """Delete a variation with all its versions and files."""
    from .uploads import drop_sessions

    model = parent(db, "model", id, user, write=True)
    scope_variation(db, "model", id, variation_id)
    ids = list(
        db.scalars(
            select(ResourceVersion.id).where(
                ResourceVersion.variation_id == variation_id
            )
        )
    )
    drop_sessions(db, ids)
    file_ids = version_file_ids(db, ids)
    db.execute(
        delete(ResourceVersionFile).where(ResourceVersionFile.version_id.in_(ids))
    )
    # A re-created variation gets a new id, so references to this one fail clearly.
    db.execute(delete(ResourceVersion).where(ResourceVersion.id.in_(ids)))
    db.execute(delete(ModelVariation).where(ModelVariation.id == variation_id))
    db.flush()
    release_files(db, file_ids, model.owner_id)
    audit(db, user, model, "variation.delete", {"variation_id": variation_id})
    db.commit()
    return Response(status_code=204)


class CardInput(BaseModel):
    card: str = Field(max_length=100_000)


def card_template(title, description, license):
    return f"""# {title}

## Overview
{description.strip()}

## Intended use
Describe the tasks and users this model is for, and uses it is not suited to.

## Training data
Describe the data the model was trained on, its source, license and preprocessing.

## Evaluation
Report metrics, the evaluation data and how results were measured.

## Limitations & bias
Describe known failure modes, biases and risks.

## License
{license}

## How to use
Attach a variation to a notebook with **Add Input → Models**. Its files are copied
read-only under `input/`; the model page shows the exact path and a loading snippet
for each variation.
"""


@router.put("/models/{id}/card", tags=["Model"])
def update_card(
    id: int, data: CardInput, user=Depends(current_user), db=Depends(get_db)
):
    model = parent(db, "model", id, user, write=True)
    model.card = data.card
    audit(db, user, model, "model.card", {"length": len(data.card)})
    db.commit()
    return {"id": model.id, "card": model.card}
