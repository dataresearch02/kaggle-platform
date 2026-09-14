"""Convert datasets and models that predate versions into version 1, once.

Run by migration 0014 on upgraded databases and by seed() at every start, so rows
created by older importers also gain a version. A dataset with any version row, or a
model with a variation, is skipped, so reruns change nothing. Files are not moved:
stored_files rows point at the existing uploads/ and artifacts/ blobs.

Dataset version 1 holds the primary CSV and the newest supplemental file of each path
(a supplemental file with the primary's name replaces it, as notebook inputs did).
Every model gains a "default" variation; version 1 is created when it has files.
"""

import hashlib
import re

from sqlalchemy import func, inspect, select

from .db import DATA_DIR
from .file_store import fallback_path
from .models import (
    ArtifactVersion,
    Dataset,
    DatasetProfile,
    ModelCard,
    ModelVariation,
    ResourceVersion,
    ResourceVersionFile,
    StoredFile,
    now,
)

FRAMEWORKS = {
    "pytorch": "PyTorch",
    "tensorflow": "TensorFlow / Keras",
    "jax": "JAX",
    "scikit-learn": "scikit-learn",
    "onnx": "ONNX",
    "transformers": "Transformers",
    "gguf": "GGUF",
    "other": "Other",
}
ALIASES = {
    "pytorch": "pytorch",
    "torch": "pytorch",
    "tensorflow": "tensorflow",
    "tensorflowkeras": "tensorflow",
    "keras": "tensorflow",
    "tf": "tensorflow",
    "jax": "jax",
    "flax": "jax",
    "scikitlearn": "scikit-learn",
    "sklearn": "scikit-learn",
    "onnx": "onnx",
    "transformers": "transformers",
    "huggingface": "transformers",
    "huggingfacetransformers": "transformers",
    "gguf": "gguf",
    "llamacpp": "gguf",
}
NEEDED = ("stored_files", "resource_versions", "resource_version_files")


def framework_key(value):
    return ALIASES.get(re.sub(r"[^a-z0-9]", "", (value or "").lower()), "other")


def file_facts(store, key, size, sha256):
    """Size and digest, completed from the file for small legacy blobs."""
    path = DATA_DIR / store / key
    if path.is_file() and not path.is_symlink():
        size = path.stat().st_size
        if not sha256 and size <= 64 * 1024 * 1024:
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            sha256 = digest.hexdigest()
    return int(size or 0), sha256 or ""


def stored_file(connection, owner_id, store, key, size, sha256, created_at):
    table = StoredFile.__table__
    existing = connection.scalar(
        select(table.c.id).where(table.c.store == store, table.c.storage_key == key)
    )
    if existing:
        return existing, connection.scalar(
            select(table.c.size).where(table.c.id == existing)
        )
    size, sha256 = file_facts(store, key, size, sha256)
    return (
        connection.execute(
            table.insert().values(
                owner_id=owner_id,
                store=store,
                storage_key=key,
                size=size,
                sha256=sha256,
                created_at=created_at or now(),
            )
        ).inserted_primary_key[0],
        size,
    )


def latest_artifacts(connection, kind, resource_id):
    table = ArtifactVersion.__table__
    latest = (
        select(func.max(table.c.id))
        .where(table.c.kind == kind, table.c.resource_id == resource_id)
        .group_by(table.c.path)
    )
    return connection.execute(
        select(table).where(table.c.id.in_(latest)).order_by(table.c.path)
    ).all()


def add_version(
    connection, kind, resource_id, variation_id, owner_id, created_at, files
):
    """Insert published version 1 with (path, store, key, size, sha256) files."""
    versions, members = ResourceVersion.__table__, ResourceVersionFile.__table__
    rows, total = [], 0
    for path, store, key, size, sha256 in files:
        file_id, size = stored_file(
            connection, owner_id, store, key, size, sha256, created_at
        )
        rows.append((path, file_id))
        total += size
    version_id = connection.execute(
        versions.insert().values(
            kind=kind,
            resource_id=resource_id,
            variation_id=variation_id,
            number=1,
            status="published",
            note="Initial version",
            creator_id=owner_id,
            file_count=len(rows),
            total_size=total,
            created_at=created_at or now(),
            published_at=created_at or now(),
        )
    ).inserted_primary_key[0]
    for path, file_id in rows:
        connection.execute(
            members.insert().values(version_id=version_id, path=path, file_id=file_id)
        )


def backfill_resource_versions(connection):
    """Return how many datasets and models gained version rows."""
    inspector = inspect(connection)
    result = {"datasets": 0, "models": 0}
    if not all(inspector.has_table(name) for name in NEEDED):
        return result
    has_artifacts = inspector.has_table("artifact_versions")
    versions = ResourceVersion.__table__
    if inspector.has_table("datasets"):
        datasets = Dataset.__table__
        profiles = (
            DatasetProfile.__table__
            if inspector.has_table("dataset_profiles")
            else None
        )
        pending = connection.execute(
            select(
                datasets.c.id,
                datasets.c.owner_id,
                datasets.c.filename,
                datasets.c.storage_key,
                datasets.c.size,
                datasets.c.created_at,
            )
            .where(
                datasets.c.id.not_in(
                    select(versions.c.resource_id).where(versions.c.kind == "dataset")
                )
            )
            .order_by(datasets.c.id)
        ).all()
        for row in pending:
            files = {}
            if row.storage_key:
                digest = (
                    connection.scalar(
                        select(profiles.c.sha256).where(profiles.c.dataset_id == row.id)
                    )
                    if profiles is not None
                    else ""
                )
                files[fallback_path(row.filename)] = (
                    "uploads",
                    row.storage_key,
                    row.size,
                    digest,
                )
            for artifact in (
                latest_artifacts(connection, "datasets", row.id)
                if has_artifacts
                else []
            ):
                files[fallback_path(artifact.path, "file")] = (
                    "artifacts",
                    artifact.storage_key,
                    artifact.size,
                    artifact.sha256,
                )
            add_version(
                connection,
                "dataset",
                row.id,
                0,
                row.owner_id,
                row.created_at,
                [(path, *facts) for path, facts in sorted(files.items())],
            )
            result["datasets"] += 1
    if inspector.has_table("model_cards") and inspector.has_table("model_variations"):
        cards, variations = ModelCard.__table__, ModelVariation.__table__
        pending = connection.execute(
            select(cards.c.id, cards.c.owner_id, cards.c.framework, cards.c.created_at)
            .where(cards.c.id.not_in(select(variations.c.model_id)))
            .order_by(cards.c.id)
        ).all()
        for row in pending:
            variation_id = connection.execute(
                variations.insert().values(
                    model_id=row.id,
                    framework=framework_key(row.framework),
                    slug="default",
                    description="",
                    created_at=row.created_at or now(),
                )
            ).inserted_primary_key[0]
            artifacts = (
                latest_artifacts(connection, "models", row.id) if has_artifacts else []
            )
            if artifacts and not connection.scalar(
                select(versions.c.id)
                .where(versions.c.kind == "model", versions.c.resource_id == row.id)
                .limit(1)
            ):
                add_version(
                    connection,
                    "model",
                    row.id,
                    variation_id,
                    row.owner_id,
                    row.created_at,
                    [
                        (
                            fallback_path(item.path, "file"),
                            "artifacts",
                            item.storage_key,
                            item.size,
                            item.sha256,
                        )
                        for item in artifacts
                    ],
                )
            result["models"] += 1
    return result
