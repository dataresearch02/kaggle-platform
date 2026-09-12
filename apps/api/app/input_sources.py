"""Grouped notebook inputs, resolved from authorized immutable source files."""

import base64
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from sqlalchemy.orm import defer, load_only
from pathlib import PurePosixPath
from fastapi import HTTPException, Depends
from sqlalchemy import select, or_, func
from .db import DATA_DIR, get_db
from .auth import current_user
from .models import (
    Dataset,
    Notebook,
    NotebookOutput,
    Competition,
    CompetitionDataFile,
    ArtifactVersion,
    ModelCard,
    DatasetProfile,
)
from .dataset_access import readable as dataset_readable, visible_datasets, visibility
from .notebook_visibility import require_visible, visible_notebooks
from .notebook_outputs import readable as output_readable, router
from .competition_metadata import require_data_access


def safe_path(value):
    path = PurePosixPath(value)
    if (
        not value
        or str(path) == "."
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in value
    ):
        raise HTTPException(422, "Invalid input filename")
    return str(path)


@dataclass
class InputFile:
    id: int
    filename: str
    kind: str
    size: int
    sha256: str = ""
    storage_path: Optional[Path] = None

    def read(self, db):
        if self.kind == "competition":
            content = db.scalar(
                select(CompetitionDataFile.content).where(
                    CompetitionDataFile.id == self.id
                )
            )
            if content is None:
                raise HTTPException(404, "Competition input is unavailable")
            return content.encode()
        if not self.storage_path or not self.storage_path.is_file():
            raise HTTPException(404, "Input file is unavailable")
        return self.storage_path.read_bytes()


def source_files(db, user, kind, id, selected=None, public=False):
    """Resolve metadata only. Load a single file's bytes when it is actually copied."""
    files = []
    if kind in ("dataset", "model"):
        from .artifacts import resource

        resource_kind = "datasets" if kind == "dataset" else "models"
        row = resource(db, resource_kind, id, user)
        if public and kind == "dataset" and visibility(db, id) != "public":
            raise HTTPException(
                422, "Publish the input dataset before publishing this notebook"
            )
        query = select(ArtifactVersion).where(
            ArtifactVersion.kind == resource_kind, ArtifactVersion.resource_id == id
        )
        if selected is not None:
            artifact_ids = [
                file["id"] for file in selected if file.get("kind") == "artifact"
            ]
            query = query.where(ArtifactVersion.id.in_(artifact_ids))
        else:
            # Select the newest version of each path in SQL, not every historic payload.
            latest = (
                select(func.max(ArtifactVersion.id))
                .where(
                    ArtifactVersion.kind == resource_kind,
                    ArtifactVersion.resource_id == id,
                )
                .group_by(ArtifactVersion.path)
            )
            query = query.where(ArtifactVersion.id.in_(latest))
        artifacts = list(db.scalars(query.order_by(ArtifactVersion.id.desc())))
        if selected is not None and len(artifacts) != len(set(artifact_ids)):
            raise HTTPException(404, "An attached artifact version is unavailable")
        for file in artifacts:
            files.append(
                InputFile(
                    file.id,
                    safe_path(file.path),
                    "artifact",
                    file.size,
                    file.sha256,
                    DATA_DIR / "artifacts" / file.storage_key,
                )
            )
        include_primary = kind == "dataset" and (
            selected is None
            or any(
                file.get("kind", "dataset") == "dataset" and file["id"] == id
                for file in selected
            )
        )
        if include_primary and not any(file.filename == row.filename for file in files):
            profile = db.get(DatasetProfile, id)
            files.append(
                InputFile(
                    row.id,
                    safe_path(row.filename),
                    "dataset",
                    row.size,
                    profile.sha256 if profile else "",
                    DATA_DIR / "uploads" / row.storage_key,
                )
            )
        if selected is not None and any(
            file.get("kind", "dataset") not in ("artifact", "dataset")
            or (
                file.get("kind", "dataset") == "dataset"
                and (kind != "dataset" or file["id"] != id)
            )
            for file in selected
        ):
            raise HTTPException(422, "Invalid dataset or model input reference")
    elif kind == "competition":
        row = db.get(Competition, id)
        require_data_access(db, id, user)
        query = (
            select(CompetitionDataFile)
            .options(defer(CompetitionDataFile.content))
            .where(
                CompetitionDataFile.competition_id == id,
                CompetitionDataFile.role.in_(
                    ["train", "test", "reference", "submission", "sample_submission"]
                ),
            )
        )
        if selected is not None:
            query = query.where(
                CompetitionDataFile.id.in_([file["id"] for file in selected])
            )
        rows = list(db.scalars(query.order_by(CompetitionDataFile.id)))
        if selected is not None and len(rows) != len({file["id"] for file in selected}):
            raise HTTPException(404, "An attached competition file is unavailable")
        files = [
            InputFile(
                file.id, safe_path(file.path), "competition", file.size, file.sha256
            )
            for file in rows
        ]
    elif kind == "notebook":
        row = require_visible(db, id, user)
        if public and not db.scalar(
            select(Notebook.id).where(Notebook.id == id, visible_notebooks(None))
        ):
            raise HTTPException(
                422, "Publish the source notebook before publishing this notebook"
            )
        allowed = or_(NotebookOutput.owner_id == user.id, NotebookOutput.shared == 1)
        query = select(NotebookOutput).where(NotebookOutput.notebook_id == id, allowed)
        if selected is not None:
            query = query.where(
                NotebookOutput.id.in_([file["id"] for file in selected])
            )
        else:
            latest = (
                select(func.max(NotebookOutput.id))
                .where(NotebookOutput.notebook_id == id, allowed)
                .group_by(NotebookOutput.filename)
            )
            query = query.where(NotebookOutput.id.in_(latest))
        outputs = list(db.scalars(query.order_by(NotebookOutput.id.desc())))
        if selected is not None and len(outputs) != len(
            {file["id"] for file in selected}
        ):
            raise HTTPException(404, "An attached notebook output is unavailable")
        for output in outputs:
            if public and not output.shared:
                raise HTTPException(
                    422, "Notebook output must be shared before publishing"
                )
            files.append(
                InputFile(
                    output.id,
                    safe_path(output.filename),
                    "notebook-output",
                    output.size,
                    output.sha256,
                    DATA_DIR / "notebook-outputs" / output.storage_key,
                )
            )
    else:
        raise HTTPException(422, "Unknown input source")
    if not row or not files:
        raise HTTPException(422, "This source has no available input files")
    if len(files) > 1000 or sum(file.size for file in files) > 200 * 1024 * 1024:
        raise HTTPException(
            422, "A local input source supports up to 1,000 files totaling 200 MB"
        )
    if len({file.filename for file in files}) != len(files):
        raise HTTPException(422, "Input files must have unique relative paths")
    slug = re.sub(r"[^a-z0-9]+", "-", row.title.lower()).strip("-")[:80] or kind
    folder = f"input/{slug}-{kind}-{id}"
    return {
        "format_version": 2,
        "id": id,
        "kind": kind,
        "title": row.title,
        "path": folder,
        "files": [
            {
                "id": file.id,
                "kind": file.kind,
                "filename": file.filename,
                "path": f"{folder}/{file.filename}",
                "size": file.size,
                "sha256": file.sha256,
            }
            for file in files
        ],
    }, files


def validate_reference(item):
    if (
        not isinstance(item, dict)
        or item.get("kind") not in ("dataset", "competition", "notebook", "model")
        or type(item.get("id")) is not int
        or item["id"] < 1
    ):
        raise HTTPException(422, "Invalid input source")
    path = item.get("path", "")
    if not isinstance(path, str) or not re.fullmatch(
        r"input/[a-z0-9-]+-" + item["kind"] + "-" + str(item["id"]), path
    ):
        raise HTTPException(422, "Invalid input folder")
    files = item.get("files")
    if not isinstance(files, list) or not files or len(files) > 1000:
        raise HTTPException(422, "Invalid input file list")
    for file in files:
        if (
            not isinstance(file, dict)
            or type(file.get("id")) is not int
            or not isinstance(file.get("filename"), str)
        ):
            raise HTTPException(422, "Invalid input file")
        safe_path(file["filename"])
    return item


def resolve_attachment(db, user, item, public=False):
    validate_reference(item)
    result, files = source_files(
        db,
        user,
        item["kind"],
        item["id"],
        item["files"],
        public,
    )
    # Preserve the source folder across renames; reject arbitrary client paths.
    path = item.get("path", result["path"])
    if not re.fullmatch(
        r"input/[a-z0-9-]+-" + re.escape(item["kind"]) + "-" + str(item["id"]), path
    ):
        raise HTTPException(422, "Invalid input folder")
    result["path"] = path
    for file in result["files"]:
        file["path"] = path + "/" + file["filename"]
    return result, files


async def materialize(db, user, hub, folder, item):
    from .notebook_files import mkdir, endpoint

    result, files = resolve_attachment(db, user, item)
    for file in files:
        content = file.read(db)
        path = (folder + "/" if folder else "") + result["path"] + "/" + file.filename
        await mkdir(user, hub, str(PurePosixPath(path).parent))
        hub.expect(
            await hub.request(
                "PUT",
                endpoint(user, path),
                contents=True,
                json={
                    "type": "file",
                    "format": "base64",
                    "content": base64.b64encode(content).decode(),
                },
            ),
            (200, 201),
        )
    return result


@router.get("/input-sources")
def catalog(
    kind: str,
    q: str = "",
    before: int = 2147483647,
    user=Depends(current_user),
    db=Depends(get_db),
):
    model = {
        "dataset": Dataset,
        "competition": Competition,
        "notebook": Notebook,
        "model": ModelCard,
    }.get(kind)
    if not model:
        raise HTTPException(422, "Unknown source type")
    query = (
        select(model)
        .options(load_only(model.id, model.title))
        .where(model.id < before, model.title.icontains(q[:160], autoescape=True))
    )
    if kind == "dataset":
        query = query.where(visible_datasets(user))
    if kind == "model":
        query = query.where(
            ModelCard.id.in_(
                select(ArtifactVersion.resource_id).where(
                    ArtifactVersion.kind == "models"
                )
            )
        )
    if kind == "notebook":
        query = query.where(
            visible_notebooks(user), Notebook.id.in_(select(NotebookOutput.notebook_id))
        )
    rows = list(db.scalars(query.order_by(model.id.desc()).limit(51)))
    return {
        "items": [
            {"id": row.id, "title": row.title, "kind": kind} for row in rows[:50]
        ],
        "next_cursor": rows[49].id if len(rows) > 50 else None,
    }


@router.get("/input-sources/{kind}/{id}/files/{file_id}/preview")
def preview_file(
    kind: str,
    id: int,
    file_id: int,
    file_kind: str = "",
    user=Depends(current_user),
    db=Depends(get_db),
):
    """Bounded read-only preview of an authorized source, never execute its contents."""
    import csv
    import io

    limit = 256 * 1024
    if kind in ("dataset", "model") and (file_kind == "artifact" or kind == "model"):
        from .artifacts import resource

        resource_kind = "datasets" if kind == "dataset" else "models"
        resource(db, resource_kind, id, user)
        row = db.get(ArtifactVersion, file_id)
        if not row or row.kind != resource_kind or row.resource_id != id:
            raise HTTPException(404, "Input file not found")
        filename = row.path
        with (DATA_DIR / "artifacts" / row.storage_key).open("rb") as stream:
            content = stream.read(limit + 1)
    elif kind == "competition":
        from .metadata_routes import member_file

        row = member_file(db, id, file_id, user)
        filename, content = row.path, row.content.encode()[: limit + 1]
    elif kind == "dataset":
        row = dataset_readable(db, id, user)
        if file_id != id:
            raise HTTPException(404, "Input file not found")
        filename = row.filename
        with (DATA_DIR / "uploads" / row.storage_key).open("rb") as stream:
            content = stream.read(limit + 1)
    elif kind in ("notebook", "notebook-output"):
        row = output_readable(db, file_id, user)
        if (kind == "notebook" and row.notebook_id != id) or (
            kind == "notebook-output" and row.id != id
        ):
            raise HTTPException(404, "Input file not found")
        filename = row.filename
        with (DATA_DIR / "notebook-outputs" / row.storage_key).open("rb") as stream:
            content = stream.read(limit + 1)
    else:
        raise HTTPException(422, "Unknown input source")
    truncated = len(content) > limit
    try:
        text = content[:limit].decode("utf-8-sig")
        if "\x00" in text:
            raise UnicodeError()
    except UnicodeError:
        return {
            "filename": filename,
            "format": "binary",
            "message": "Preview is not available for this binary file.",
        }
    if filename.lower().endswith((".csv", ".tsv")):
        reader = csv.reader(
            io.StringIO(text),
            delimiter="\t" if filename.lower().endswith(".tsv") else ",",
        )
        columns = next(reader, [])[:50]
        rows = []
        for index, row in enumerate(reader):
            if index >= 50:
                truncated = True
                break
            rows.append([value[:2000] for value in row[:50]])
        return {
            "filename": filename,
            "format": "table",
            "columns": [value[:2000] for value in columns],
            "rows": rows,
            "truncated": truncated,
        }
    return {
        "filename": filename,
        "format": "text",
        "text": text[:16000],
        "truncated": truncated or len(text) > 16000,
    }
