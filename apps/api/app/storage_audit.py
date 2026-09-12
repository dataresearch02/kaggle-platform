"""Read-only storage inventory. Never prints documents, CSV contents or credentials."""

import hashlib
import json
from collections import defaultdict
from sqlalchemy import select, func
from .db import SessionLocal, DATA_DIR, Base
from . import models


def audit(db, root=DATA_DIR):
    report = {
        "tables": {},
        "file_stores": {},
        "duplicate_bytes": 0,
        "issues": [],
        "document_bytes": {},
    }
    for name, table in Base.metadata.tables.items():
        report["tables"][name] = db.scalar(select(func.count()).select_from(table))
    hashes = defaultdict(list)
    dataset_hashes = dict(
        db.execute(
            select(models.DatasetProfile.dataset_id, models.DatasetProfile.sha256)
        ).all()
    )
    for directory, model, name_field in [
        ("uploads", models.Dataset, "filename"),
        ("artifacts", models.ArtifactVersion, "path"),
        ("notebook-outputs", models.NotebookOutput, "filename"),
    ]:
        referenced = set()
        total = 0
        rows = list(db.scalars(select(model)))
        for row in rows:
            referenced.add(row.storage_key)
            path = root / directory / row.storage_key
            if not path.is_file() or path.is_symlink():
                report["issues"].append(
                    {"type": "missing_file", "table": model.__tablename__, "id": row.id}
                )
                continue
            digest = hashlib.sha256()
            size = 0
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                    size += len(chunk)
            total += size
            hashes[digest.hexdigest()].append((directory, row.storage_key, size))
            if row.size != size:
                report["issues"].append(
                    {
                        "type": "size_mismatch",
                        "table": model.__tablename__,
                        "id": row.id,
                    }
                )
            expected = (
                dataset_hashes.get(row.id)
                if model is models.Dataset
                else getattr(row, "sha256", None)
            )
            if expected and expected != digest.hexdigest():
                report["issues"].append(
                    {
                        "type": "hash_mismatch",
                        "table": model.__tablename__,
                        "id": row.id,
                    }
                )
        physical = (
            {p.name for p in (root / directory).iterdir() if p.is_file()}
            if (root / directory).is_dir()
            else set()
        )
        report["file_stores"][directory] = {
            "references": len(rows),
            "referenced_bytes": total,
            "unreferenced_files": sorted(physical - referenced),
        }
    for group in hashes.values():
        unique = {(directory, key): size for directory, key, size in group}
        if len(unique) > 1:
            report["duplicate_bytes"] += sum(unique.values()) - next(
                iter(unique.values())
            )
    for model in (
        models.NotebookWorkingCopy,
        models.NotebookVersion,
        models.NotebookPublication,
        models.NotebookCommit,
    ):
        size = 0
        for document in db.scalars(select(model.document)):
            size += len(document.encode())
            try:
                parsed = json.loads(document)
                if not isinstance(parsed, dict) or not isinstance(
                    parsed.get("cells"), list
                ):
                    raise ValueError("Invalid notebook document")
            except (ValueError, TypeError):
                report["issues"].append(
                    {"type": "invalid_notebook_document", "table": model.__tablename__}
                )
                continue
            source_models = {
                "dataset": models.Dataset,
                "competition": models.Competition,
                "notebook": models.Notebook,
                "model": models.ModelCard,
            }
            for source in parsed.get("metadata", {}).get("arena_input_sources", []):
                if not isinstance(source, dict):
                    report["issues"].append(
                        {
                            "type": "invalid_input_reference",
                            "table": model.__tablename__,
                        }
                    )
                    continue
                source_model = source_models.get(source.get("kind"))
                if source_model is None or not db.get(source_model, source.get("id")):
                    report["issues"].append(
                        {
                            "type": "missing_input_source",
                            "table": model.__tablename__,
                            "source_kind": source.get("kind"),
                            "source_id": source.get("id"),
                        }
                    )

        report["document_bytes"][model.__tablename__] = size
    report["competition_csv_bytes"] = 0
    for file in db.scalars(select(models.CompetitionDataFile)):
        content = file.content.encode()
        report["competition_csv_bytes"] += len(content)
        if (
            file.size != len(content)
            or file.sha256 != hashlib.sha256(content).hexdigest()
        ):
            report["issues"].append(
                {"type": "competition_file_integrity", "id": file.id}
            )
    for kind, model in [("datasets", models.Dataset), ("models", models.ModelCard)]:
        ids = select(model.id)
        for id in db.scalars(
            select(models.ArtifactVersion.id).where(
                models.ArtifactVersion.kind == kind,
                models.ArtifactVersion.resource_id.not_in(ids),
            )
        ):
            report["issues"].append({"type": "orphan_artifact_reference", "id": id})
    return report


if __name__ == "__main__":
    with SessionLocal() as db:
        print(json.dumps(audit(db), indent=2))
