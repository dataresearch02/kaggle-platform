import json
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.main import app
from app.db import get_db
from app.models import CompetitionDataFile, CompetitionOverview, DatasetProfile
from app.competition_metadata import backfill_metadata
from test_challenges import publish


def test_metadata_edit_and_period_validation(member):
    item = publish(member).json()
    base = f"/api/competitions/{item['id']}"
    overview = member.get(base + "/overview").json()
    assert overview["ends_at"] == item["deadline"]
    overview.update(
        prize="Learning credits",
        prize_details="Top three receive credits",
        getting_started="Train, validate, submit",
        data_description="Training labels and test features",
    )
    assert member.put(base + "/overview", json=overview).status_code == 200
    assert member.get(base).json()["prize"] == "Learning credits"
    overview["starts_at"] = overview["ends_at"]
    assert member.put(base + "/overview", json=overview).status_code == 422
    overview["starts_at"] = "2026-01-01T00:00:00"
    assert member.put(base + "/overview", json=overview).status_code == 422
    member.post("/api/auth/logout")
    member.post(
        "/api/auth/register",
        json={"username": "outsider", "password": "outsider-password"},
    )
    overview["starts_at"] = None
    assert member.put(base + "/overview", json=overview).status_code == 403


def test_join_gate_and_private_answers(member):
    item = publish(member).json()
    base = f"/api/competitions/{item['id']}"
    files = member.get(base + "/files").json()
    assert {row["role"] for row in files} == {"test", "submission"}
    assert "content" not in files[0] and "columns_json" not in files[0]
    file_id = next(row["id"] for row in files if row["role"] == "test")
    assert member.get(f"{base}/files/{file_id}").status_code == 200
    member.post("/api/auth/logout")
    for path in [
        "/data",
        "/test",
        "/sample",
        f"/files/{file_id}",
        f"/files/{file_id}/download",
    ]:
        assert member.get(base + path).status_code == 401
    member.post(
        "/api/auth/register",
        json={"username": "visitor", "password": "visitor-password"},
    )
    for path in [
        "/data",
        "/test",
        "/sample",
        f"/files/{file_id}",
        f"/files/{file_id}/download",
    ]:
        assert member.get(base + path).status_code == 403
    assert member.post(base + "/join").status_code == 200
    preview = member.get(f"{base}/files/{file_id}").json()
    assert [col["name"] for col in preview["columns"]] == ["id", "temperature"]
    assert (
        member.get(f"{base}/files/{file_id}/download").text
        == "id,temperature\na,20\nb,30\n"
    )
    assert member.get(f"{base}/files/{file_id}?offset=-1").status_code == 422
    other = publish(member).json()["id"]
    assert member.get(f"/api/competitions/{other}/files/{file_id}").status_code == 404


def test_dataset_snapshot_dictionary_and_deletion(member):
    dataset = member.post(
        "/api/datasets",
        data={"title": "Training rows", "description": "Training labels"},
        files={"file": ("train.csv", b"id,x,target\n1,2,4\n2,NA,8\n")},
    ).json()
    metadata = member.get(f"/api/datasets/{dataset['id']}/metadata").json()
    assert metadata["rows"] == 2
    assert metadata["columns"][1]["missing"] == 1
    assert (
        member.put(
            f"/api/datasets/{dataset['id']}/metadata",
            json={
                "source_url": "https://example.com/data",
                "citation": "Author",
                "documentation": "Readme",
                "column_descriptions": {"x": "Measured input"},
            },
        ).status_code
        == 200
    )
    item = publish(member).json()
    base = f"/api/competitions/{item['id']}"
    response = member.post(
        base + "/files",
        data={
            "dataset_id": dataset["id"],
            "path": "train/features.csv",
            "role": "train",
            "description": "Training set",
        },
    )
    assert response.status_code == 201, response.text
    file_id = response.json()["id"]
    assert (
        member.post(
            base + "/files",
            data={
                "dataset_id": dataset["id"],
                "path": "train/features.csv",
                "role": "train",
            },
        ).status_code
        == 409
    )
    assert (
        member.put(
            f"{base}/files/{file_id}",
            json={
                "description": "Updated docs",
                "column_descriptions": {"target": "Value to predict"},
            },
        ).status_code
        == 200
    )
    assert (
        member.get(f"{base}/files/{file_id}").json()["columns"][2]["description"]
        == "Value to predict"
    )
    assert (
        member.put(
            f"{base}/files/{file_id}",
            json={"description": "", "column_descriptions": {"unknown": "Invalid"}},
        ).status_code
        == 422
    )
    before = member.get(f"{base}/files/{file_id}/download").content
    assert member.delete(f"/api/work/datasets/{dataset['id']}").status_code == 204
    assert member.get(f"{base}/files/{file_id}/download").content == before
    assert member.get(f"{base}/files/{file_id}").json()["source_dataset_id"] is None
    assert member.delete(f"/api/work/competitions/{item['id']}").status_code == 204
    with next(app.dependency_overrides[get_db]()) as db:
        assert db.get(CompetitionDataFile, file_id) is None
        assert db.get(CompetitionOverview, item["id"]) is None
        assert db.get(DatasetProfile, dataset["id"]) is None


def test_upload_validation_pagination_and_backfill(member):
    item = publish(member).json()
    base = f"/api/competitions/{item['id']}"
    for path, content in [
        ("../secret.csv", b"x\n1\n"),
        ("train/ok.csv", b"x,x\n1,2\n"),
        ("train/ok.csv", b"x,y\n1\n"),
    ]:
        assert (
            member.post(
                base + "/files",
                data={"path": path, "role": "train"},
                files={"file": ("data.csv", content)},
            ).status_code
            == 422
        )
    content = "id,x\n" + "".join(f"{n},{n * 2}\n" for n in range(60))
    response = member.post(
        base + "/files",
        data={"path": "reference/measurements.csv", "role": "reference"},
        files={"file": ("data.csv", content)},
    )
    assert response.status_code == 201
    file_id = response.json()["id"]
    page = member.get(f"{base}/files/{file_id}?offset=25").json()
    assert len(page["preview"]) == 25 and page["preview"][0]["id"] == "25"
    with next(app.dependency_overrides[get_db]()) as db:
        overview = db.get(CompetitionOverview, item["id"])
        overview.getting_started = "Keep these organizer instructions"
        db.commit()
        count = len(list(db.scalars(select(CompetitionDataFile))))
        backfill_metadata(db)
        backfill_metadata(db)
        assert len(list(db.scalars(select(CompetitionDataFile)))) == count
        assert (
            db.get(CompetitionOverview, item["id"]).getting_started
            == "Keep these organizer instructions"
        )
