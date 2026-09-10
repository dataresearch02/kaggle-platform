import csv
import io
import json
import math

import pytest
from sqlalchemy import select

from app.db import get_db
from app.main import app
from app.import_samples import import_samples
from app.models import Competition, Dataset, Notebook, SampleImport


def test_imported_collection_and_real_submissions(member, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with next(app.dependency_overrides[get_db]()) as db:
        result = import_samples(db)
        assert len(result["datasets"]) == 4
        assert len(result["notebooks"]) == 4
        assert len(result["competitions"]) == 2
        assert len(result["discussions"]) == 2
        again = import_samples(db)
        assert again["status"] == "already imported"
        assert again["competitions"] == result["competitions"]
        for competition_id in result["competitions"]:
            base = f"/api/competitions/{competition_id}"
            assert member.post(base + "/join").status_code == 200
            data = member.get(base + "/data").json()
            assert data["rows"] in (30, 69)
            assert len(member.get(base + "/discussion").json()) == 2
            notebooks = member.get(base + "/resources/notebooks").json()
            assert len(notebooks) == 2
            baseline = next(
                row for row in notebooks if "submission baseline" in row["title"]
            )
            exec(compile(baseline["code"], "<sample baseline>", "exec"), {})
            filename = (
                "iris-submission.csv"
                if baseline["title"].startswith("Iris")
                else "penguins-submission.csv"
            )
            content = (tmp_path / filename).read_bytes()
            assert member.post(base + "/join").status_code == 200
            response = member.post(
                base + "/submissions", files={"file": (filename, content, "text/csv")}
            )
            assert response.status_code == 201, response.text
            assert math.isfinite(response.json()["score"])
            assert len(member.get(base).json()["leaderboard"]) == 1
            competition = db.get(Competition, competition_id)
            assert set(json.loads(competition.solution)) == {
                r["id"] for r in csv.DictReader(io.StringIO(content.decode()))
            }
        for dataset_id in result["datasets"]:
            assert member.get(f"/api/datasets/{dataset_id}/download").status_code == 200
        # User edits and deletion survive another import; no automatic resurrection.
        dataset = db.get(Dataset, result["datasets"][0])
        dataset.title = "Edited by curator"
        notebook = db.get(Notebook, result["notebooks"][0])
        db.delete(notebook)
        db.commit()
        import_samples(db)
        assert db.get(Dataset, dataset.id).title == "Edited by curator"
        assert db.get(Notebook, result["notebooks"][0]) is None


def test_failed_import_rolls_back_database_and_files(client, tmp_path, monkeypatch):
    with next(app.dependency_overrides[get_db]()) as db:
        before = list(db.scalars(select(Dataset.id)))

        def fail_commit():
            raise RuntimeError("simulated database failure")

        monkeypatch.setattr(db, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="simulated"):
            import_samples(db, tmp_path)
        assert list(db.scalars(select(Dataset.id))) == before
        assert list((tmp_path / "uploads").iterdir()) == []
        assert db.scalar(select(SampleImport)) is None


def test_sample_narratives_and_existing_sample_upgrade(member):
    from app.import_samples import update_sample_notebooks
    from app.models import NotebookPublication

    with next(app.dependency_overrides[get_db]()) as db:
        result = import_samples(db)
        for id in result["notebooks"]:
            document = member.get(f"/api/code/{id}").json()["document"]
            markdown = [
                cell["source"]
                for cell in document["cells"]
                if cell["cell_type"] == "markdown"
            ]
            assert len(markdown) >= 6
            assert any("| Column | Role |" in cell for cell in markdown)
            assert any("> **" in cell for cell in markdown)
            assert any("## Sources and attribution" in cell for cell in markdown)
            code = "".join(
                cell["source"]
                for cell in document["cells"]
                if cell["cell_type"] == "code"
            )
            assert code == db.get(Notebook, id).code
            compile(code, "<sample cells>", "exec")
        for id in result["notebooks"]:
            db.delete(db.get(NotebookPublication, id))
        db.commit()
        upgraded = update_sample_notebooks(db)
        assert upgraded["updated"] == result["notebooks"]
        assert update_sample_notebooks(db)["updated"] == []
        for id in result["notebooks"]:
            assert (
                member.get(f"/api/code/{id}").json()["document"]["metadata"][
                    "arena_sample_revision"
                ]
                == 2
            )
