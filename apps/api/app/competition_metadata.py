"""Additive metadata backfill and shared CSV profiling; no destructive schema changes."""

import csv
import hashlib
import io
import json
import math
from sqlalchemy import select
from fastapi import HTTPException
from .db import DATA_DIR
from .models import (
    Competition,
    CompetitionOverview,
    CompetitionDataFile,
    Dataset,
    DatasetProfile,
    ChallengeDetails,
    Entry,
    SampleImport,
)


def profile_csv(content):
    if len(content.encode()) > 10 * 1024 * 1024:
        raise ValueError("CSV files must be at most 10 MB")
    reader = csv.reader(io.StringIO(content))
    headers = next(reader, [])
    if (
        not headers
        or len(set(headers)) != len(headers)
        or any(not h.strip() for h in headers)
    ):
        raise ValueError("CSV needs unique, nonempty column names")
    columns = [
        {"name": name, "type": "number", "missing": 0, "description": ""}
        for name in headers
    ]
    count = 0
    for row in reader:
        if len(row) != len(headers):
            raise ValueError("CSV rows must match the column count")
        count += 1
        for column, value in zip(columns, row):
            if value.strip().lower() in ("", "na", "nan", "null"):
                column["missing"] += 1
            else:
                try:
                    if not math.isfinite(float(value)):
                        column["type"] = "text"
                except ValueError:
                    column["type"] = "text"
    if not count:
        raise ValueError("CSV needs at least one data row")
    return {
        "columns_json": json.dumps(columns),
        "row_count": count,
        "sha256": hashlib.sha256(content.encode()).hexdigest(),
    }


def add_file(db, competition_id, path, role, content, **metadata):
    row = CompetitionDataFile(
        competition_id=competition_id,
        path=path,
        role=role,
        content=content,
        size=len(content.encode()),
        **profile_csv(content),
        **metadata,
    )
    db.add(row)
    return row


def initialize_competition(db, competition):
    if db.get(CompetitionOverview, competition.id):
        return
    details = db.get(ChallengeDetails, competition.id)
    db.add(
        CompetitionOverview(
            competition_id=competition.id,
            starts_at=details.created_at if details else None,
            prize_details=competition.prize,
            getting_started="1. Join the competition and review the data dictionary.\n2. Download training and test data. Train and validate your model.\n3. Create a CSV with id,prediction columns.\n4. Upload predictions in Submissions before the deadline; your best score counts.",
            evaluation=f"{competition.metric}. {'Higher' if competition.metric == 'Accuracy' else 'Lower'} scores are better. The leaderboard uses your best submission.",
            data_description="Review the file descriptions and column dictionary before training. Test labels are kept private.",
        )
    )
    test = (
        details.test_csv
        if details
        else "id,temperature,working_day\n7,20,1\n8,10,1\n9,23,0\n"
    )
    add_file(
        db,
        competition.id,
        "test/test.csv",
        "test",
        test,
        description="Features for evaluation. Predict one value for each id.",
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "prediction"])
    writer.writerows((key, 0) for key in json.loads(competition.solution))
    add_file(
        db,
        competition.id,
        "submission/sample_submission.csv",
        "submission",
        output.getvalue(),
        description="Submission format example. Replace zero predictions with your model predictions.",
    )


def ensure_profile(db, dataset):
    profile = db.get(DatasetProfile, dataset.id)
    if not profile:
        raw = (DATA_DIR / "uploads" / dataset.storage_key).read_bytes()
        values = profile_csv(raw.decode("utf-8-sig"))
        values["sha256"] = hashlib.sha256(raw).hexdigest()
        profile = DatasetProfile(dataset_id=dataset.id, **values)
        db.add(profile)
    return profile


def backfill_metadata(db):
    """Idempotent per-record migration. Existing metadata and snapshots are preserved."""
    new_competitions = set()
    for dataset in db.scalars(select(Dataset)):
        if (DATA_DIR / "uploads" / dataset.storage_key).is_file():
            ensure_profile(db, dataset)
    for competition in db.scalars(select(Competition)):
        if not db.get(CompetitionOverview, competition.id):
            new_competitions.add(competition.id)
            initialize_competition(db, competition)
    receipt = db.get(SampleImport, "kaggle-practice-v1")
    if receipt:
        manifest = json.loads(receipt.manifest)
        for competition_id, dataset_id in zip(
            manifest["competitions"], manifest["datasets"][1::2]
        ):
            dataset = db.get(Dataset, dataset_id)
            if competition_id in new_competitions and dataset:
                path = DATA_DIR / "uploads" / dataset.storage_key
                if path.is_file():
                    add_file(
                        db,
                        competition_id,
                        "train/" + dataset.filename,
                        "train",
                        path.read_text(encoding="utf-8-sig"),
                        source_dataset_id=dataset.id,
                        description=dataset.description,
                        license=dataset.license,
                    )
    db.commit()


def require_data_access(db, competition_id, user):
    details = db.get(ChallengeDetails, competition_id)
    if details and details.owner_id == user.id:
        return
    if not db.scalar(
        select(Entry.id).where(
            Entry.competition_id == competition_id, Entry.user_id == user.id
        )
    ):
        raise HTTPException(
            403, "Join this competition to preview or download its files"
        )
