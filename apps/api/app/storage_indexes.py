"""Additive, repeatable indexes for growing catalogs; existing rows are unchanged."""

from sqlalchemy import Index
from .models import (
    ArtifactVersion,
    NotebookOutput,
    NotebookVersion,
    NotebookWorkingCopy,
    NotebookCommit,
    Dataset,
    Notebook,
    ModelCard,
    Submission,
)

INDEXES = (
    Index(
        "ix_artifact_source_path_version",
        ArtifactVersion.kind,
        ArtifactVersion.resource_id,
        ArtifactVersion.path,
        ArtifactVersion.id,
    ),
    Index(
        "ix_output_notebook_file_version",
        NotebookOutput.notebook_id,
        NotebookOutput.filename,
        NotebookOutput.id,
    ),
    Index(
        "ix_output_notebook_digest", NotebookOutput.notebook_id, NotebookOutput.sha256
    ),
    Index("ix_output_storage_key", NotebookOutput.storage_key),
    Index(
        "ix_version_notebook_sequence", NotebookVersion.notebook_id, NotebookVersion.id
    ),
    Index("ix_working_competition", NotebookWorkingCopy.competition_id),
    Index("ix_commit_status_sequence", NotebookCommit.status, NotebookCommit.id),
    Index("ix_dataset_owner_sequence", Dataset.owner_id, Dataset.id),
    Index("ix_notebook_owner_sequence", Notebook.owner_id, Notebook.id),
    Index("ix_model_owner_sequence", ModelCard.owner_id, ModelCard.id),
    Index(
        "ix_submission_competition_sequence", Submission.competition_id, Submission.id
    ),
)


def ensure_storage_indexes(engine):
    for index in INDEXES:
        index.create(engine, checkfirst=True)
