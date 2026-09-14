import csv
import io
import json

from sqlalchemy import func, select

from app.db import get_db
from app.main import app
from app.models import (
    ArtifactVersion,
    Competition,
    CompetitionDataFile,
    Dataset,
    SampleImport,
)
from app.practice_competitions import PRACTICE, import_practice_competitions


def database():
    return next(app.dependency_overrides[get_db]())


def test_practice_import_is_idempotent_and_scores_offline(member):
    with database() as db:
        first = import_practice_competitions(db)
        assert sorted(item["slug"] for item in first) == [
            "breast-cancer-diagnosis",
            "diabetes-progression",
            "handwritten-digits",
            "wine-cultivar",
        ]
        assert {item["status"] for item in first} == {"imported"}
        again = import_practice_competitions(db)
        assert {item["status"] for item in again} == {"already imported"}
        assert [item["competition"] for item in again] == [
            item["competition"] for item in first
        ]
        assert (
            db.scalar(
                select(func.count())
                .select_from(Competition)
                .where(Competition.category == "Practice")
            )
            == 4
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(SampleImport)
                .where(SampleImport.key.startswith("practice-"))
            )
            == 4
        )

    for item in first:
        folder = PRACTICE / item["slug"]
        meta = json.loads((folder / "meta.json").read_text())
        base = f"/api/competitions/{item['competition']}"
        detail = member.get(base).json()
        assert detail["deadline"] is None
        assert detail["owner"] == "arena"
        assert detail["submission_columns"] == ["id", "prediction"]
        assert "solution_usage" not in detail
        overview = member.get(base + "/overview").json()
        assert overview["ends_at"] is None
        assert meta["license"] in overview["data_description"]

        dataset = member.get(f"/api/datasets/{item['dataset']}").json()
        assert dataset["license"] == meta["license"][:80]
        assert (
            meta["source"]
            in member.get(f"/api/datasets/{item['dataset']}/metadata").json()[
                "citation"
            ]
        )
        with database() as db:
            assert {
                row.path
                for row in db.scalars(
                    select(ArtifactVersion).where(
                        ArtifactVersion.kind == "datasets",
                        ArtifactVersion.resource_id == item["dataset"],
                    )
                )
            } == {"test.csv", "sample_submission.csv"}
            assert {
                row.role
                for row in db.scalars(
                    select(CompetitionDataFile).where(
                        CompetitionDataFile.competition_id == item["competition"]
                    )
                )
            } == {"train", "test", "submission"}
            usage = json.loads(db.get(Competition, item["competition"]).solution_usage)
            assert set(usage.values()) == {"Public", "Private"}

        assert member.post(base + "/join").status_code == 200
        solution = (folder / "solution.csv").read_text()
        with_usage = member.post(
            base + "/submissions", files={"file": ("solution.csv", solution.encode())}
        )
        assert with_usage.status_code == 422
        rows = list(csv.DictReader(io.StringIO(solution)))
        answers = "id,prediction\n" + "".join(
            f"{row['id']},{row['prediction']}\n" for row in rows
        )
        scored = member.post(
            base + "/submissions", files={"file": ("answers.csv", answers.encode())}
        )
        assert scored.status_code == 201, scored.text
        expected = 1.0 if detail["metric"] == "Accuracy" else 0.0
        assert scored.json()["score"] == expected

    with database() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(Dataset)
                .where(Dataset.tags.startswith("practice,"))
            )
            == 4
        )
