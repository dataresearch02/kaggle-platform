import hashlib
import json

import pytest
from sqlalchemy import select
from app.db import DATA_DIR, get_db
from app.main import app
from app.import_titanic import import_titanic
from app.models import Competition, CompetitionSource, NotebookCommit, SampleImport


@pytest.fixture
def bundle(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    files = {}
    for name, start, count, label in [
        ("train.csv", 1, 891, True),
        ("test.csv", 892, 418, False),
        ("gender_submission.csv", 892, 418, True),
    ]:
        raw = (
            "PassengerId"
            + (",Survived" if label else ",Name")
            + "\n"
            + "".join(
                f"{i},{i % 2 if label else 'Test passenger'}\n"
                for i in range(start, start + count)
            )
        ).encode()
        (source / name).write_bytes(raw)
        files[name] = {"sha256": hashlib.sha256(raw).hexdigest()}
    (source / "manifest.json").write_text(json.dumps({"files": files}))
    document = {
        "nbformat": 4,
        "nbformat_minor": 4,
        "metadata": {},
        "cells": [
            {"cell_type": "markdown", "source": "# Source tutorial"},
            {"cell_type": "code", "source": "print('/kaggle/input/titanic/train.csv')"},
        ],
    }
    (tmp_path / "tutorial.json").write_text(
        json.dumps(
            {
                "metadata": {
                    "ref": "alexisbcook/titanic-tutorial",
                    "currentVersionNumber": 22,
                },
                "blob": {"source": json.dumps(document)},
            }
        )
    )
    (tmp_path / "pages.json").write_text(
        json.dumps(
            {
                "pages": [
                    {"name": name, "content": "# Official " + name}
                    for name in [
                        "Description",
                        "Evaluation",
                        "rules",
                        "data-description",
                        "Frequently Asked Questions",
                    ]
                ]
            }
        )
    )
    (tmp_path / "competition.json").write_text(
        json.dumps({"enabledDate": "2012-09-28T21:13:33.550Z"})
    )
    return tmp_path


def test_original_import_preserves_files_and_defers_scoring(member, bundle):
    with next(app.dependency_overrides[get_db]()) as db:
        result = import_titanic(db, bundle)
        assert import_titanic(db, bundle)["status"] == "already imported"
        id = result["competition"]
        base = f"/api/competitions/{id}"
        response = member.get(base).json()
        assert response["evaluation_available"] is False
        assert response["deadline"] is None
        assert response["rules_content"] == "# Official rules"
        assert member.get(base + "/overview").json()["ends_at"] is None
        assert member.get(base + "/data").status_code == 403
        assert member.post(base + "/join").status_code == 200
        assert (
            member.get(base + "/sample").content
            == (bundle / "source/gender_submission.csv").read_bytes()
        )
        assert (
            member.get(base + "/test").content
            == (bundle / "source/test.csv").read_bytes()
        )
        for dataset_id, name in zip(
            result["datasets"], ["train.csv", "test.csv", "gender_submission.csv"]
        ):
            assert (
                member.get(f"/api/datasets/{dataset_id}/download").content
                == (bundle / "source" / name).read_bytes()
            )
        denied = member.post(
            base + "/submissions",
            files={"file": ("submission.csv", "id,prediction\n892,0\n", "text/csv")},
        )
        assert denied.status_code == 409
        assert "unavailable" in denied.json()["detail"]
        fork = member.post(
            f"/api/code/{result['notebooks'][1]}/fork?competition_id={id}"
        ).json()
        denied = member.post(
            f"/api/code/{fork['id']}/commits", json={"competition_id": id}
        )
        assert denied.status_code == 409
        assert db.scalar(select(NotebookCommit)) is None
        assert db.get(Competition, id).solution == "{}"
        assert db.get(CompetitionSource, id).source_url.endswith("/titanic")
        assert member.get(base).json()["leaderboard"] == []
        original = member.get(f"/api/code/{result['notebooks'][0]}").json()["document"]
        adapted = member.get(f"/api/code/{result['notebooks'][1]}").json()["document"]
        assert "/kaggle/input" in original["cells"][-1]["source"]
        assert "/kaggle/input" not in adapted["cells"][-1]["source"]


def test_import_rejects_tampering_before_database_changes(client, bundle):
    (bundle / "source/train.csv").write_text("tampered")
    with next(app.dependency_overrides[get_db]()) as db:
        with pytest.raises(ValueError, match="checksum"):
            import_titanic(db, bundle)
        assert db.get(SampleImport, "titanic-official-v1") is None
        assert db.scalar(select(CompetitionSource)) is None


def test_failed_import_rolls_back_files(client, bundle, tmp_path, monkeypatch):
    with next(app.dependency_overrides[get_db]()) as db:

        def fail():
            raise RuntimeError("commit failed")

        monkeypatch.setattr(db, "commit", fail)
        storage = tmp_path / "storage"
        with pytest.raises(RuntimeError, match="commit failed"):
            import_titanic(db, bundle, storage)
        assert not list((storage / "uploads").iterdir())
        assert db.scalar(select(CompetitionSource)) is None


def test_organizer_can_delete_import_with_provenance(member, bundle):
    from app.models import ChallengeDetails

    user_id = member.get("/api/auth/me").json()["id"]
    with next(app.dependency_overrides[get_db]()) as db:
        result = import_titanic(db, bundle)
        id = result["competition"]
        db.get(ChallengeDetails, id).owner_id = user_id
        db.commit()
    assert member.delete(f"/api/work/competitions/{id}").status_code == 204
    with next(app.dependency_overrides[get_db]()) as db:
        assert db.get(CompetitionSource, id) is None
        assert db.get(Competition, id) is None
