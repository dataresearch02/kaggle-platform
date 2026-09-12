from pathlib import Path
from types import SimpleNamespace
from sqlalchemy import select, inspect
from app.db import get_db, DATA_DIR
from app.main import app
from app.models import Notebook, User, NotebookOutput
from app.input_sources import source_files, resolve_attachment
from app.notebook_outputs import store_snapshot
from app.storage_audit import audit
from app.storage_indexes import ensure_storage_indexes


def database():
    return app.dependency_overrides[get_db]()


def test_dataset_manifest_pins_supplemental_versions_without_reading_bytes(
    member, monkeypatch
):
    dataset = member.post(
        "/api/datasets",
        data={"title": "Training data", "description": "Multiple immutable files"},
        files={"file": ("train.csv", b"value\n1\n")},
    ).json()
    base = f'/api/assets/datasets/{dataset["id"]}'
    first = member.post(
        base,
        data={"path": "features.csv"},
        files={"file": ("features.csv", b"feature\n10\n")},
    ).json()
    with next(database()) as db:
        user = db.scalar(select(User).where(User.username == "learner"))
        with monkeypatch.context() as patch:
            patch.setattr(
                Path,
                "read_bytes",
                lambda self: (_ for _ in ()).throw(
                    AssertionError("Metadata resolution read file bytes")
                ),
            )
            manifest, files = source_files(db, user, "dataset", dataset["id"])
        assert {file.filename for file in files} == {"train.csv", "features.csv"}
        assert all(
            "sha256" in file and "size" in file and "kind" in file
            for file in manifest["files"]
        )
        member.post(
            base,
            data={"path": "features.csv"},
            files={"file": ("features.csv", b"feature\n20\n")},
        )
        restored, pinned = resolve_attachment(db, user, manifest)
        assert restored == manifest
        assert b"feature\n10\n" in [file.read(db) for file in pinned]
        _, latest = source_files(db, user, "dataset", dataset["id"])
        assert b"feature\n20\n" in [file.read(db) for file in latest]
    preview = member.get(
        f'/api/input-sources/dataset/{dataset["id"]}/files/{first["id"]}/preview?file_kind=artifact'
    )
    assert preview.status_code == 200
    assert preview.json()["rows"] == [["10"]]


def test_model_artifact_input_manifest(member):
    model = member.post(
        "/api/models",
        json={
            "title": "Trained model",
            "description": "Weights and configuration",
            "framework": "PyTorch",
            "license": "MIT",
        },
    ).json()
    member.post(
        f'/api/assets/models/{model["id"]}',
        data={"path": "model/weights.pt"},
        files={"file": ("weights.pt", b"\x00weights")},
    )
    assert (
        member.get("/api/input-sources?kind=model").json()["items"][0]["id"]
        == model["id"]
    )
    with next(database()) as db:
        user = db.scalar(select(User).where(User.username == "learner"))
        manifest, files = source_files(db, user, "model", model["id"])
        assert files[0].read(db) == b"\x00weights"
        assert manifest["files"][0]["kind"] == "artifact"
        assert manifest["path"].endswith(f'-model-{model["id"]}')


def test_output_revert_is_latest_snapshot_without_duplicate_bytes(member):
    id = member.post(
        "/api/notebooks", json={"title": "Versioned outputs", "code": "print(1)"}
    ).json()["id"]
    with next(database()) as db:
        owner = db.get(Notebook, id).owner_id
        first = store_snapshot(db, id, owner, "predictions.csv", b"A")
        db.commit()
        second = store_snapshot(db, id, owner, "predictions.csv", b"B")
        db.commit()
        reverted = store_snapshot(db, id, owner, "predictions.csv", b"A")
        db.commit()
        assert reverted.id > second.id > first.id
        assert reverted.storage_key == first.storage_key
        assert store_snapshot(db, id, owner, "predictions.csv", b"A").id == reverted.id
        manifest, files = source_files(db, db.get(User, owner), "notebook", id)
        assert files[0].read(db) == b"A"
        assert manifest["files"][0]["id"] == reverted.id
        assert (
            len(
                {
                    row.storage_key
                    for row in db.scalars(
                        select(NotebookOutput).where(NotebookOutput.notebook_id == id)
                    )
                }
            )
            == 2
        )
    # Deletion queues each physical file once and retains the existing cleanup lifecycle.
    assert member.delete(f"/api/work/notebooks/{id}").status_code == 204


def test_audit_is_read_only_and_reports_missing_files(member, tmp_path):
    with next(database()) as db:
        report = audit(db, tmp_path)
        assert report["issues"]
        assert all(issue["type"] == "missing_file" for issue in report["issues"])
        assert list(tmp_path.iterdir()) == []
        ensure_storage_indexes(db.get_bind())
        ensure_storage_indexes(db.get_bind())
        assert "ix_output_notebook_file_version" in {
            index["name"]
            for index in inspect(db.get_bind()).get_indexes("notebook_outputs")
        }
