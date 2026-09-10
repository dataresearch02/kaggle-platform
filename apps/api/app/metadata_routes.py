"""Organizer metadata editing and member-only competition file exploration."""

import csv
import io
import json
import re
from datetime import datetime, timezone
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Form, File, UploadFile, Response
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.orm import Session
from .auth import current_user
from .db import get_db, DATA_DIR
from .models import (
    Competition,
    CompetitionOverview,
    CompetitionDataFile,
    ChallengeDetails,
    Dataset,
    DatasetProfile,
    now,
)
from .competition_metadata import add_file, ensure_profile, require_data_access

router = APIRouter(prefix="/api", tags=["Competition metadata"])


def organizer(db, id, user):
    competition = db.scalar(
        select(Competition).where(Competition.id == id).with_for_update()
    )
    details = db.get(ChallengeDetails, id)
    if not competition or not details or details.owner_id != user.id:
        raise HTTPException(403, "Only the organizer can edit this competition")
    return competition


def overview_data(db, id):
    competition = db.get(Competition, id)
    if not competition:
        raise HTTPException(404, "Competition not found")
    overview = db.get(CompetitionOverview, id)
    fields = (
        "starts_at",
        "prize_details",
        "getting_started",
        "evaluation",
        "data_description",
    )
    return {
        **{key: getattr(overview, key, None) for key in fields},
        "ends_at": competition.deadline,
        "prize": competition.prize,
        "description": competition.description,
        "metric": competition.metric,
    }


class OverviewInput(BaseModel):
    starts_at: Optional[datetime] = None
    ends_at: datetime
    prize: str = Field(max_length=80)
    description: str = Field(min_length=3, max_length=20000)
    prize_details: str = Field(default="", max_length=10000)
    getting_started: str = Field(default="", max_length=20000)
    evaluation: str = Field(default="", max_length=10000)
    data_description: str = Field(default="", max_length=20000)


@router.get("/competitions/{id}/overview")
def overview(id: int, db: Session = Depends(get_db)):
    return overview_data(db, id)


@router.put("/competitions/{id}/overview")
def update_overview(
    id: int,
    data: OverviewInput,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    competition = organizer(db, id, user)
    if data.ends_at.tzinfo is None or (
        data.starts_at
        and (data.starts_at.tzinfo is None or data.starts_at >= data.ends_at)
    ):
        raise HTTPException(
            422, "Use timezone-aware dates; the start must precede the deadline"
        )
    row = db.get(CompetitionOverview, id)
    if not row:
        row = CompetitionOverview(competition_id=id)
        db.add(row)
    for key in ("prize_details", "getting_started", "evaluation", "data_description"):
        setattr(row, key, getattr(data, key))
    row.starts_at = (
        data.starts_at.astimezone(timezone.utc).isoformat() if data.starts_at else None
    )
    competition.deadline = data.ends_at.astimezone(timezone.utc).isoformat()
    competition.prize = data.prize
    competition.description = data.description
    db.commit()
    return overview_data(db, id)


def file_metadata(row):
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "path",
            "role",
            "description",
            "license",
            "source_url",
            "source_dataset_id",
            "row_count",
            "size",
            "sha256",
            "created_at",
        )
    }


@router.get("/competitions/{id}/files")
def files(id: int, db: Session = Depends(get_db)):
    if not db.get(Competition, id):
        raise HTTPException(404, "Competition not found")
    return [
        file_metadata(row)
        for row in db.scalars(
            select(CompetitionDataFile)
            .where(CompetitionDataFile.competition_id == id)
            .order_by(CompetitionDataFile.path)
        )
    ]


def member_file(db, id, file_id, user):
    require_data_access(db, id, user)
    row = db.get(CompetitionDataFile, file_id)
    if not row or row.competition_id != id:
        raise HTTPException(404, "Competition file not found")
    return row


@router.get("/competitions/{id}/files/{file_id}")
def preview(
    id: int,
    file_id: int,
    offset: int = 0,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    row = member_file(db, id, file_id, user)
    if offset < 0 or offset > row.row_count:
        raise HTTPException(422, "Invalid row offset")
    from itertools import islice

    rows = list(islice(csv.DictReader(io.StringIO(row.content)), offset, offset + 25))
    return {
        **file_metadata(row),
        "columns": json.loads(row.columns_json),
        "preview": rows,
        "offset": offset,
    }


@router.get("/competitions/{id}/files/{file_id}/download")
def download(
    id: int, file_id: int, user=Depends(current_user), db: Session = Depends(get_db)
):
    row = member_file(db, id, file_id, user)
    return Response(
        row.content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{row.path.split("/")[-1]}"'
        },
    )


@router.post("/competitions/{id}/files", status_code=201)
async def upload(
    id: int,
    path: str = Form(max_length=255),
    role: Literal["train", "reference"] = Form(),
    description: str = Form(default="", max_length=10000),
    license: str = Form(default="", max_length=80),
    dataset_id: Optional[int] = Form(default=None),
    file: Optional[UploadFile] = File(default=None),
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    organizer(db, id, user)
    if not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*\.csv", path):
        raise HTTPException(
            422,
            "Use a CSV path such as train/features.csv (letters, numbers, hyphens and underscores)",
        )
    if db.scalar(
        select(CompetitionDataFile.id).where(
            CompetitionDataFile.competition_id == id, CompetitionDataFile.path == path
        )
    ):
        raise HTTPException(409, "A file already exists at this path")
    if (dataset_id is None) == (file is None):
        raise HTTPException(422, "Choose either a source dataset or one CSV upload")
    source_url = ""
    if dataset_id is not None:
        dataset = db.scalar(
            select(Dataset).where(Dataset.id == dataset_id).with_for_update()
        )
        if not dataset or dataset.owner_id != user.id:
            raise HTTPException(403, "Choose a dataset you own")
        content = (DATA_DIR / "uploads" / dataset.storage_key).read_bytes()
        license = dataset.license
        profile = ensure_profile(db, dataset)
        source_url = profile.source_url
    else:
        content = await file.read(10 * 1024 * 1024 + 1)
    try:
        row = add_file(
            db,
            id,
            path,
            role,
            content.decode("utf-8-sig"),
            description=description,
            license=license,
            source_dataset_id=dataset_id,
            source_url=source_url,
        )
    except (ValueError, UnicodeError, csv.Error) as exc:
        raise HTTPException(422, str(exc))
    if dataset_id is not None:
        row.columns_json = profile.columns_json
    db.commit()
    return file_metadata(row)


class FileInput(BaseModel):
    description: str = Field(max_length=10000)
    column_descriptions: dict[str, str] = Field(default_factory=dict)


@router.put("/competitions/{id}/files/{file_id}")
def describe_file(
    id: int,
    file_id: int,
    data: FileInput,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    organizer(db, id, user)
    row = member_file(db, id, file_id, user)
    columns = json.loads(row.columns_json)
    if set(data.column_descriptions) - {c["name"] for c in columns} or any(
        len(v) > 2000 for v in data.column_descriptions.values()
    ):
        raise HTTPException(
            422, "Use existing column names and descriptions up to 2000 characters"
        )
    row.description = data.description
    for column in columns:
        if column["name"] in data.column_descriptions:
            column["description"] = data.column_descriptions[column["name"]]
    row.columns_json = json.dumps(columns)
    db.commit()
    return file_metadata(row)


class ProfileInput(BaseModel):
    source_url: Optional[HttpUrl] = None
    citation: str = Field(default="", max_length=10000)
    documentation: str = Field(default="", max_length=20000)
    column_descriptions: dict[str, str] = Field(default_factory=dict)


@router.get("/datasets/{id}/metadata")
def dataset_metadata(id: int, db: Session = Depends(get_db)):
    row = db.get(DatasetProfile, id)
    if not row:
        raise HTTPException(404, "Dataset metadata not found")
    return {
        "source_url": row.source_url,
        "citation": row.citation,
        "documentation": row.documentation,
        "columns": json.loads(row.columns_json),
        "rows": row.row_count,
        "sha256": row.sha256,
        "updated_at": row.updated_at,
    }


@router.put("/datasets/{id}/metadata")
def update_dataset_metadata(
    id: int,
    data: ProfileInput,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    dataset = db.scalar(select(Dataset).where(Dataset.id == id).with_for_update())
    if not dataset or dataset.owner_id != user.id:
        raise HTTPException(403, "Only the dataset owner can edit its metadata")
    row = ensure_profile(db, dataset)
    columns = json.loads(row.columns_json)
    if set(data.column_descriptions) - {c["name"] for c in columns} or any(
        len(v) > 2000 for v in data.column_descriptions.values()
    ):
        raise HTTPException(
            422, "Use existing column names and descriptions up to 2000 characters"
        )
    row.source_url = str(data.source_url) if data.source_url else ""
    row.citation, row.documentation = data.citation, data.documentation
    for column in columns:
        if column["name"] in data.column_descriptions:
            column["description"] = data.column_descriptions[column["name"]]
    row.columns_json = json.dumps(columns)
    db.commit()
    return dataset_metadata(id, db)
