from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Float,
    ForeignKey,
    UniqueConstraint,
)
from .db import Base


def now():
    return datetime.now(timezone.utc).isoformat()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(40), unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    created_at = Column(String, default=now)


class Session(Base):
    __tablename__ = "sessions"
    token_hash = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    expires_at = Column(Float, nullable=False)


class Dataset(Base):
    __tablename__ = "datasets"
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(160), nullable=False)
    description = Column(Text, nullable=False)
    tags = Column(String(300), default="")
    license = Column(String(80), default="CC0-1.0")
    filename = Column(String(255), nullable=False)
    storage_key = Column(String(80), nullable=False)
    size = Column(Integer, default=0)
    created_at = Column(String, default=now)


class Competition(Base):
    __tablename__ = "competitions"
    id = Column(Integer, primary_key=True)
    title = Column(String(160), nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String(80), default="Getting Started")
    metric = Column(String(30), default="RMSE")
    deadline = Column(String, nullable=False)
    solution = Column(Text, nullable=False)
    prize = Column(String(80), default="Knowledge")


class Entry(Base):
    __tablename__ = "entries"
    __table_args__ = (UniqueConstraint("user_id", "competition_id"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    competition_id = Column(Integer, ForeignKey("competitions.id"), nullable=False)


class Submission(Base):
    __tablename__ = "submissions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    competition_id = Column(Integer, ForeignKey("competitions.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    score = Column(Float, nullable=False)
    created_at = Column(String, default=now)


class Notebook(Base):
    __tablename__ = "notebooks"
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(160), nullable=False)
    description = Column(Text, default="")
    code = Column(Text, nullable=False)
    created_at = Column(String, default=now)


class Course(Base):
    __tablename__ = "courses"
    id = Column(Integer, primary_key=True)
    title = Column(String(160), nullable=False)
    description = Column(Text, nullable=False)
    duration = Column(String(40), nullable=False)
    lessons = Column(Text, nullable=False)


class Progress(Base):
    __tablename__ = "progress"
    __table_args__ = (UniqueConstraint("user_id", "course_id", "lesson_index"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False)
    lesson_index = Column(Integer, nullable=False)


class Discussion(Base):
    __tablename__ = "discussions"
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(160), nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(String, default=now)


class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True)
    discussion_id = Column(Integer, ForeignKey("discussions.id"), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(String, default=now)


class ModelCard(Base):
    __tablename__ = "model_cards"
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(160), nullable=False)
    description = Column(Text, nullable=False)
    framework = Column(String(80), nullable=False)
    license = Column(String(80), nullable=False)
    url = Column(Text, nullable=False)
    created_at = Column(String, default=now)


class ChallengeDetails(Base):
    """Creator metadata for new challenges; legacy competitions remain compatible."""

    __tablename__ = "challenge_details"
    competition_id = Column(Integer, ForeignKey("competitions.id"), primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    kind = Column(String(20), nullable=False)
    test_csv = Column(Text, nullable=False)
    created_at = Column(String, default=now)


class NotebookDraft(Base):
    __tablename__ = "notebook_drafts"
    id = Column(String(32), primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    expires_at = Column(Float, nullable=False)
    notebook_id = Column(Integer, ForeignKey("notebooks.id"), nullable=True)


class WorkFileDeletion(Base):
    """Durable cleanup jobs committed with removal of a published item."""

    __tablename__ = "work_file_deletions"
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    kind = Column(String(20), nullable=False)
    path = Column(String(255), nullable=False)


class CompetitionResource(Base):
    __tablename__ = "competition_resources"
    __table_args__ = (UniqueConstraint("competition_id", "kind", "resource_id"),)
    id = Column(Integer, primary_key=True)
    competition_id = Column(Integer, ForeignKey("competitions.id"), nullable=False)
    kind = Column(String(20), nullable=False)
    resource_id = Column(Integer, nullable=False)


class CompetitionPost(Base):
    __tablename__ = "competition_posts"
    id = Column(Integer, primary_key=True)
    competition_id = Column(Integer, ForeignKey("competitions.id"), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(160), nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(String, default=now)


class SampleImport(Base):
    """Completed sample packs; retain the receipt even if examples are deleted."""

    __tablename__ = "sample_imports"
    key = Column(String(80), primary_key=True)
    manifest = Column(Text, nullable=False)
    created_at = Column(String, default=now)


class CompetitionOverview(Base):
    __tablename__ = "competition_overviews"
    competition_id = Column(Integer, ForeignKey("competitions.id"), primary_key=True)
    starts_at = Column(String, nullable=True)
    prize_details = Column(Text, default="", nullable=False)
    getting_started = Column(Text, default="", nullable=False)
    evaluation = Column(Text, default="", nullable=False)
    data_description = Column(Text, default="", nullable=False)
    updated_at = Column(String, default=now, onupdate=now)


class DatasetProfile(Base):
    __tablename__ = "dataset_profiles"
    dataset_id = Column(Integer, ForeignKey("datasets.id"), primary_key=True)
    source_url = Column(Text, default="", nullable=False)
    citation = Column(Text, default="", nullable=False)
    documentation = Column(Text, default="", nullable=False)
    columns_json = Column(Text, default="[]", nullable=False)
    row_count = Column(Integer, default=0, nullable=False)
    sha256 = Column(String(64), nullable=False)
    updated_at = Column(String, default=now, onupdate=now)


class CompetitionDataFile(Base):
    """Immutable CSV snapshots, independent of later source dataset edits/deletion."""

    __tablename__ = "competition_data_files"
    __table_args__ = (UniqueConstraint("competition_id", "path"),)
    id = Column(Integer, primary_key=True)
    competition_id = Column(
        Integer, ForeignKey("competitions.id"), nullable=False, index=True
    )
    source_dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=True)
    path = Column(String(255), nullable=False)
    role = Column(String(30), nullable=False)
    description = Column(Text, default="", nullable=False)
    license = Column(String(80), default="", nullable=False)
    source_url = Column(Text, default="", nullable=False)
    content = Column(Text, nullable=False)
    columns_json = Column(Text, nullable=False)
    row_count = Column(Integer, nullable=False)
    size = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    created_at = Column(String, default=now)


class NotebookPublication(Base):
    """Explicit public snapshot; never a user's private runtime working copy."""

    __tablename__ = "notebook_publications"
    notebook_id = Column(Integer, ForeignKey("notebooks.id"), primary_key=True)
    document = Column(Text, nullable=False)
    forked_from = Column(Integer, ForeignKey("notebooks.id"), nullable=True)
    updated_at = Column(String, default=now, onupdate=now)


class NotebookBookmark(Base):
    __tablename__ = "notebook_bookmarks"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    notebook_id = Column(Integer, ForeignKey("notebooks.id"), primary_key=True)
    created_at = Column(String, default=now)


class NotebookShare(Base):
    __tablename__ = "notebook_shares"
    notebook_id = Column(Integer, ForeignKey("notebooks.id"), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    created_at = Column(String, default=now)


class NotebookComment(Base):
    __tablename__ = "notebook_comments"
    id = Column(Integer, primary_key=True)
    notebook_id = Column(
        Integer,
        ForeignKey("notebooks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(String, default=now)


class ContentReply(Base):
    __tablename__ = "content_replies"
    id = Column(Integer, primary_key=True)
    target_kind = Column(String(32), nullable=False, index=True)
    target_id = Column(Integer, nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(String, default=now)


class ContentReaction(Base):
    __tablename__ = "content_reactions"
    __table_args__ = (
        UniqueConstraint("target_kind", "target_id", "user_id", "reaction"),
    )
    id = Column(Integer, primary_key=True)
    target_kind = Column(String(32), nullable=False, index=True)
    target_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    reaction = Column(String(20), nullable=False)


class NotebookWorkingCopy(Base):
    __tablename__ = "notebook_working_copies"
    notebook_id = Column(Integer, ForeignKey("notebooks.id"), primary_key=True)
    document = Column(Text, nullable=False)
    competition_id = Column(Integer, ForeignKey("competitions.id"), nullable=True)
    forked_from = Column(Integer, nullable=True)
    private = Column(Integer, nullable=False, default=1)


class NotebookCommit(Base):
    __tablename__ = "notebook_commits"
    id = Column(Integer, primary_key=True)
    notebook_id = Column(
        Integer, ForeignKey("notebooks.id"), nullable=False, index=True
    )
    competition_id = Column(Integer, ForeignKey("competitions.id"), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    document = Column(Text, nullable=False)
    output_filename = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, default="queued", index=True)
    error = Column(Text, nullable=True)
    score = Column(Float, nullable=True)
    created_at = Column(String, default=now)


class CompetitionTeam(Base):
    __tablename__ = "competition_teams"
    id = Column(Integer, primary_key=True)
    competition_id = Column(
        Integer, ForeignKey("competitions.id"), nullable=False, index=True
    )
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(80), nullable=False)
    invite_code = Column(String(40), nullable=False, unique=True)
    created_at = Column(String, default=now)


class CompetitionTeamMember(Base):
    __tablename__ = "competition_team_members"
    __table_args__ = (UniqueConstraint("competition_id", "user_id"),)
    id = Column(Integer, primary_key=True)
    competition_id = Column(Integer, ForeignKey("competitions.id"), nullable=False)
    team_id = Column(
        Integer, ForeignKey("competition_teams.id"), nullable=False, index=True
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(String, default=now)
