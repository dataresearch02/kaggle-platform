from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Float,
    ForeignKey,
    Index,
    LargeBinary,
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
    role = Column(String(10), nullable=False, default="user", server_default="user")
    status = Column(
        String(12), nullable=False, default="active", server_default="active"
    )


class Session(Base):
    __tablename__ = "sessions"
    token_hash = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    expires_at = Column(Float, nullable=False)
    # "password" or "oidc"; logout also ends the Keycloak session for "oidc".
    auth_method = Column(
        String(10), nullable=False, default="password", server_default="password"
    )


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
    # Moderation: hidden rows are visible only to their owner and administrators.
    hidden = Column(Integer, nullable=False, default=0, server_default="0")
    hidden_reason = Column(Text, nullable=False, default="", server_default="")


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
    # Private per-id answer metadata such as Public/Private leaderboard usage.
    solution_usage = Column(Text, nullable=False, default="{}", server_default="{}")
    # Host rules (Markdown); a material change bumps the revision to re-accept.
    rules = Column(Text, nullable=False, default="", server_default="")
    rules_revision = Column(Integer, nullable=False, default=1, server_default="1")
    rules_updated_at = Column(String, nullable=True)
    # Timeline; the start lives in competition_overviews and the end is `deadline`.
    entry_deadline = Column(String, nullable=True)
    merger_deadline = Column(String, nullable=True)
    max_daily_submissions = Column(
        Integer, nullable=False, default=5, server_default="5"
    )
    max_final_submissions = Column(
        Integer, nullable=False, default=2, server_default="2"
    )
    # K for MAP@K; ignored by other metrics.
    metric_k = Column(Integer, nullable=True)
    finalized_at = Column(String, nullable=True)


class Entry(Base):
    __tablename__ = "entries"
    __table_args__ = (UniqueConstraint("user_id", "competition_id"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    competition_id = Column(Integer, ForeignKey("competitions.id"), nullable=False)
    # Accepted Competition.rules_revision; submitting requires the current one.
    rules_revision = Column(Integer, nullable=True)
    rules_accepted_at = Column(String, nullable=True)


class Submission(Base):
    __tablename__ = "submissions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    competition_id = Column(Integer, ForeignKey("competitions.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    # Public leaderboard score (all rows when the competition has no split).
    score = Column(Float, nullable=False)
    created_at = Column(String, default=now)
    # Null without a private split or for legacy rows without stored predictions.
    private_score = Column(Float, nullable=True)
    final_selected = Column(Integer, nullable=False, default=0, server_default="0")


class SubmissionPrediction(Base):
    """Compressed original predictions, kept so submissions can be rescored."""

    __tablename__ = "submission_predictions"
    submission_id = Column(Integer, ForeignKey("submissions.id"), primary_key=True)
    content = Column(LargeBinary, nullable=False)


class CompetitionDisqualification(Base):
    """A user (solo entry) or team excluded from leaderboards and medals."""

    __tablename__ = "competition_disqualifications"
    id = Column(Integer, primary_key=True)
    competition_id = Column(
        Integer, ForeignKey("competitions.id"), nullable=False, index=True
    )
    team_id = Column(Integer, ForeignKey("competition_teams.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reason = Column(Text, nullable=False)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(String, default=now)


class CompetitionResult(Base):
    """Final private-leaderboard placement per user; team results repeat per member."""

    __tablename__ = "competition_results"
    __table_args__ = (UniqueConstraint("competition_id", "user_id"),)
    id = Column(Integer, primary_key=True)
    competition_id = Column(
        Integer, ForeignKey("competitions.id"), nullable=False, index=True
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    team_id = Column(Integer, nullable=True)
    rank = Column(Integer, nullable=False)
    team_count = Column(Integer, nullable=False)
    medal = Column(String(10), nullable=True)
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
    # Moderation: hidden rows are visible only to their owner and administrators.
    hidden = Column(Integer, nullable=False, default=0, server_default="0")
    hidden_reason = Column(Text, nullable=False, default="", server_default="")


class Course(Base):
    __tablename__ = "courses"
    id = Column(Integer, primary_key=True)
    title = Column(String(160), nullable=False)
    # The course summary.
    description = Column(Text, nullable=False)
    duration = Column(String(40), nullable=False)
    # Legacy lesson JSON, converted into course_lessons by learn_content.py.
    lessons = Column(Text, nullable=False, default="[]")
    # Null for seeded and legacy courses, which administrators manage.
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    difficulty = Column(
        String(20), nullable=False, default="beginner", server_default="beginner"
    )
    # New courses start as drafts; courses that predate authoring were published.
    status = Column(
        String(12), nullable=False, default="draft", server_default="published"
    )
    position = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(String, default=now)
    updated_at = Column(String, nullable=True)
    published_at = Column(String, nullable=True)


class CourseLesson(Base):
    __tablename__ = "course_lessons"
    id = Column(Integer, primary_key=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    position = Column(Integer, nullable=False, default=0)
    title = Column(String(160), nullable=False)
    # Markdown, rendered with the sanitized Markdown component.
    body = Column(Text, nullable=False, default="")
    created_at = Column(String, default=now)
    updated_at = Column(String, nullable=True)


class CourseExercise(Base):
    """A graded coding exercise. Checker and solution never reach learners early."""

    __tablename__ = "course_exercises"
    id = Column(Integer, primary_key=True)
    lesson_id = Column(
        Integer, ForeignKey("course_lessons.id"), nullable=False, index=True
    )
    position = Column(Integer, nullable=False, default=0)
    title = Column(String(160), nullable=False)
    prompt = Column(Text, nullable=False)
    starter_code = Column(Text, nullable=False, default="")
    # JSON list of progressive hints, revealed one at a time.
    hints = Column(Text, nullable=False, default="[]")
    solution = Column(Text, nullable=False)
    checker = Column(Text, nullable=False)
    # Reveal the solution after this many finished attempts; 0 only after passing.
    reveal_after = Column(Integer, nullable=False, default=3)
    # JSON list of practice pack slugs copied to input/<slug>/.
    inputs = Column(Text, nullable=False, default="[]")
    created_at = Column(String, default=now)
    updated_at = Column(String, nullable=True)


class LessonProgress(Base):
    __tablename__ = "lesson_progress"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    lesson_id = Column(Integer, ForeignKey("course_lessons.id"), primary_key=True)
    completed_at = Column(String, default=now)


class ExerciseProgress(Base):
    __tablename__ = "exercise_progress"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    exercise_id = Column(Integer, ForeignKey("course_exercises.id"), primary_key=True)
    # Finished (passed or failed) attempts; infrastructure failures do not count.
    attempts = Column(Integer, nullable=False, default=0)
    hints_revealed = Column(Integer, nullable=False, default=0)
    passed_at = Column(String, nullable=True)
    updated_at = Column(String, default=now, onupdate=now)


class ExerciseAttempt(Base):
    __tablename__ = "exercise_attempts"
    id = Column(Integer, primary_key=True)
    exercise_id = Column(
        Integer, ForeignKey("course_exercises.id"), nullable=False, index=True
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    code = Column(Text, nullable=False)
    accelerator = Column(String(3), nullable=False, default="cpu")
    # queued, running, passed or failed.
    status = Column(String(12), nullable=False, default="queued", index=True)
    message = Column(Text, nullable=False, default="")
    stdout = Column(Text, nullable=False, default="")
    error = Column(Text, nullable=False, default="")
    created_at = Column(String, default=now)
    started_at = Column(String, nullable=True)
    finished_at = Column(String, nullable=True)


class Certificate(Base):
    __tablename__ = "certificates"
    __table_args__ = (UniqueConstraint("user_id", "course_id"),)
    id = Column(Integer, primary_key=True)
    code = Column(String(40), nullable=False, unique=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False)
    # Kept as issued, even if the course is later renamed.
    course_title = Column(String(160), nullable=False)
    issued_at = Column(String, default=now)


class Progress(Base):
    """Legacy per-index lesson completion; see LessonProgress."""

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
    # Moderation: hidden rows are visible only to their owner and administrators.
    hidden = Column(Integer, nullable=False, default=0, server_default="0")
    hidden_reason = Column(Text, nullable=False, default="", server_default="")


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
    """A discussion topic in a competition, a site forum, or a dataset/model page."""

    __tablename__ = "competition_posts"
    __table_args__ = (Index("ix_competition_posts_scope", "scope", "scope_id"),)
    id = Column(Integer, primary_key=True)
    # Set only for competition topics; see scope/scope_id for the others.
    competition_id = Column(Integer, ForeignKey("competitions.id"), nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(160), nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(String, default=now)
    # Moderation: hidden rows are visible only to their owner and administrators.
    hidden = Column(Integer, nullable=False, default=0, server_default="0")
    hidden_reason = Column(Text, nullable=False, default="", server_default="")
    # "competition", "forum", "dataset" or "model"; scope_id is that row's id.
    scope = Column(
        String(20), nullable=False, default="competition", server_default="competition"
    )
    scope_id = Column(Integer, nullable=True)
    edited_at = Column(String, nullable=True)
    # Deleted by the author while it had comments: kept as a placeholder.
    deleted_at = Column(String, nullable=True)


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
    # Moderation: hidden rows are visible only to their owner and administrators.
    hidden = Column(Integer, nullable=False, default=0, server_default="0")
    hidden_reason = Column(Text, nullable=False, default="", server_default="")
    edited_at = Column(String, nullable=True)
    deleted_at = Column(String, nullable=True)


class ContentReply(Base):
    __tablename__ = "content_replies"
    id = Column(Integer, primary_key=True)
    target_kind = Column(String(32), nullable=False, index=True)
    target_id = Column(Integer, nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(String, default=now)
    # Moderation: hidden rows are visible only to their owner and administrators.
    hidden = Column(Integer, nullable=False, default=0, server_default="0")
    hidden_reason = Column(Text, nullable=False, default="", server_default="")
    edited_at = Column(String, nullable=True)
    deleted_at = Column(String, nullable=True)


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


class NotebookVersion(Base):
    """Immutable saved notebook history, separate from the public snapshot."""

    __tablename__ = "notebook_versions"
    id = Column(Integer, primary_key=True)
    notebook_id = Column(
        Integer, ForeignKey("notebooks.id"), nullable=False, index=True
    )
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    document = Column(Text, nullable=False)
    created_at = Column(String, default=now)


class DatasetAccess(Base):
    __tablename__ = "dataset_access"
    dataset_id = Column(Integer, ForeignKey("datasets.id"), primary_key=True)
    visibility = Column(String(10), nullable=False, default="private")


class DatasetShare(Base):
    __tablename__ = "dataset_shares"
    dataset_id = Column(Integer, ForeignKey("datasets.id"), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)


class SubmissionTeam(Base):
    """Team ownership fixed when predictions are submitted."""

    __tablename__ = "submission_teams"
    submission_id = Column(Integer, ForeignKey("submissions.id"), primary_key=True)
    team_id = Column(
        Integer, ForeignKey("competition_teams.id"), nullable=False, index=True
    )


class ArtifactVersion(Base):
    __tablename__ = "artifact_versions"
    id = Column(Integer, primary_key=True)
    kind = Column(String(20), nullable=False, index=True)
    resource_id = Column(Integer, nullable=False, index=True)
    path = Column(String(240), nullable=False)
    storage_key = Column(String(80), nullable=False, unique=True)
    size = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    created_at = Column(String, default=now)


class UserProfile(Base):
    __tablename__ = "user_profiles"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    details = Column(Text, nullable=False, default="{}")
    avatar = Column(Text, nullable=False, default="")
    avatar_type = Column(String(30), nullable=False, default="")
    visibility = Column(String(20), nullable=False, default="public")
    # Moderation: hidden rows are visible only to their owner and administrators.
    hidden = Column(Integer, nullable=False, default=0, server_default="0")
    hidden_reason = Column(Text, nullable=False, default="", server_default="")


class ApiToken(Base):
    __tablename__ = "api_tokens"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(80), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    prefix = Column(String(20), nullable=False)
    scope = Column(String(20), nullable=False)
    expires_at = Column(Float, nullable=False)
    created_at = Column(String, default=now)
    last_used_at = Column(String, nullable=True)


class UserGroup(Base):
    __tablename__ = "user_groups"
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(80), nullable=False)
    description = Column(Text, nullable=False, default="")
    invite_code = Column(String(80), nullable=False, unique=True)
    created_at = Column(String, default=now)


class GroupMember(Base):
    __tablename__ = "group_members"
    group_id = Column(Integer, ForeignKey("user_groups.id"), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)


class ServiceNotice(Base):
    __tablename__ = "service_notices"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    title = Column(String(160), nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(String, default=now)


class NoticeRead(Base):
    __tablename__ = "notice_reads"
    notice_id = Column(Integer, ForeignKey("service_notices.id"), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)


class CompetitionSource(Base):
    """Provenance for externally hosted competition materials."""

    __tablename__ = "competition_sources"
    competition_id = Column(Integer, ForeignKey("competitions.id"), primary_key=True)
    source_url = Column(Text, nullable=False)
    rules_url = Column(Text, nullable=False)
    rules_content = Column(Text, nullable=False)
    pages_json = Column(Text, nullable=False, default="{}")
    ongoing = Column(Integer, nullable=False, default=0)


class NotebookSettings(Base):
    __tablename__ = "notebook_settings"
    notebook_id = Column(
        Integer, ForeignKey("notebooks.id", ondelete="CASCADE"), primary_key=True
    )
    allow_comments = Column(Integer, nullable=False, default=1)


class NotebookOutput(Base):
    __tablename__ = "notebook_outputs"
    id = Column(Integer, primary_key=True)
    notebook_id = Column(
        Integer,
        ForeignKey("notebooks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    storage_key = Column(String(64), nullable=False)
    size = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    shared = Column(Integer, nullable=False, default=0)
    created_at = Column(String, default=now)


class NotebookWorkspaceFolder(Base):
    __tablename__ = "notebook_workspace_folders"
    notebook_id = Column(
        Integer, ForeignKey("notebooks.id", ondelete="CASCADE"), primary_key=True
    )
    folder = Column(String(160), nullable=False)


class NotebookDraftCompetition(Base):
    """Competition context retained independently of browser state."""

    __tablename__ = "notebook_draft_competitions"
    draft_id = Column(
        String(32),
        ForeignKey("notebook_drafts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    competition_id = Column(Integer, ForeignKey("competitions.id"), nullable=False)


class CompetitionTopicSettings(Base):
    __tablename__ = "competition_topic_settings"
    post_id = Column(
        Integer,
        ForeignKey("competition_posts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    pinned = Column(Integer, nullable=False, default=0)
    # Locked topics refuse new comments and replies.
    locked = Column(Integer, nullable=False, default=0, server_default="0")


class CompetitionTopicBookmark(Base):
    __tablename__ = "competition_topic_bookmarks"
    post_id = Column(
        Integer,
        ForeignKey("competition_posts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)


class DiscussionImage(Base):
    __tablename__ = "discussion_images"
    id = Column(String(48), primary_key=True)
    competition_id = Column(
        Integer,
        ForeignKey("competitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    media_type = Column(String(40), nullable=False)
    size = Column(Integer, nullable=False)
    created_at = Column(String, default=now)


class NotebookPublisher(Base):
    """Publisher identity captured when a notebook is committed successfully."""

    __tablename__ = "notebook_publishers"
    notebook_id = Column(
        Integer, ForeignKey("notebooks.id", ondelete="CASCADE"), primary_key=True
    )
    identity = Column(Text, nullable=False)


class BenchmarkAsset(Base):
    """A reusable task or model; code and data live in immutable revisions."""

    __tablename__ = "benchmark_assets"
    id = Column(Integer, primary_key=True)
    kind = Column(String(10), nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(160), nullable=False)
    description = Column(Text, nullable=False, default="")
    visibility = Column(String(10), nullable=False, default="private")
    created_at = Column(String, default=now)


class BenchmarkAssetVersion(Base):
    __tablename__ = "benchmark_asset_versions"
    id = Column(Integer, primary_key=True)
    asset_id = Column(
        Integer, ForeignKey("benchmark_assets.id"), nullable=False, index=True
    )
    source = Column(Text, nullable=False)
    provider_id = Column(String(128), nullable=True)
    cases = Column(Text, nullable=False, default="[]")
    digest = Column(String(64), nullable=False)
    created_at = Column(String, default=now)


class BenchmarkCollection(Base):
    __tablename__ = "benchmark_collections"
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(160), nullable=False)
    description = Column(Text, nullable=False, default="")
    visibility = Column(String(10), nullable=False, default="private")
    configuration = Column(Text, nullable=False, default='{"tasks":[],"models":[]}')
    created_at = Column(String, default=now)


class BenchmarkRun(Base):
    __tablename__ = "benchmark_runs"
    id = Column(Integer, primary_key=True)
    collection_id = Column(
        Integer, ForeignKey("benchmark_collections.id"), nullable=False, index=True
    )
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    fingerprint = Column(String(64), nullable=False, index=True)
    snapshot = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="queued", index=True)
    results = Column(Text, nullable=False, default="[]")
    logs = Column(Text, nullable=False, default="")
    error = Column(Text, nullable=False, default="")
    created_at = Column(String, default=now)
    finished_at = Column(String, nullable=True)


class NotebookDraftInput(Base):
    """Pinned resource selected before opening a new notebook."""

    __tablename__ = "notebook_draft_inputs"
    draft_id = Column(
        String(32),
        ForeignKey("notebook_drafts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source = Column(Text, nullable=False)


class ContentReceipt(Base):
    """A completed one-time content upgrade, such as the learn_content.py backfills."""

    __tablename__ = "content_receipts"
    key = Column(String(120), primary_key=True)
    detail = Column(Text, nullable=False, default="{}")
    created_at = Column(String, default=now)


class SchemaMigration(Base):
    """Applied additive schema migrations; see migrations.py."""

    __tablename__ = "schema_migrations"
    id = Column(String(80), primary_key=True)
    applied_at = Column(String, default=now)


class SiteSetting(Base):
    __tablename__ = "site_settings"
    key = Column(String(80), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(String, default=now, onupdate=now)


class ContentReport(Base):
    __tablename__ = "content_reports"
    id = Column(Integer, primary_key=True)
    reporter_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    target_kind = Column(String(32), nullable=False)
    target_id = Column(Integer, nullable=False)
    reason = Column(Text, nullable=False)
    status = Column(String(10), nullable=False, default="open", index=True)
    resolution_note = Column(Text, nullable=False, default="")
    resolved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(String, default=now)
    resolved_at = Column(String, nullable=True)


class UserIdentity(Base):
    """An OpenID Connect account linked to an Arena user; see oidc.py."""

    __tablename__ = "user_identities"
    __table_args__ = (UniqueConstraint("provider", "subject"),)
    id = Column(Integer, primary_key=True)
    # The issuer URL: `sub` values are unique only within one issuer.
    provider = Column(String(255), nullable=False)
    subject = Column(String(255), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # Informational copies of the latest claims; never used to find accounts.
    email = Column(String(320), nullable=False, default="")
    username_claim = Column(String(255), nullable=False, default="")
    created_at = Column(String, default=now)
    last_login_at = Column(String, nullable=True)


class OidcLoginAttempt(Base):
    """A pending single-use authorization request, keyed by the hashed state."""

    __tablename__ = "oidc_login_attempts"
    state_hash = Column(String(64), primary_key=True)
    # Hash of the browser-binding cookie set when the attempt started.
    browser_hash = Column(String(64), nullable=False)
    code_verifier = Column(String(128), nullable=False)
    nonce = Column(String(128), nullable=False)
    next_route = Column(String(255), nullable=False, default="home")
    # Set when a signed-in user links Keycloak to their existing account.
    link_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    expires_at = Column(Float, nullable=False, index=True)
    created_at = Column(String, default=now)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    # Null for system actions such as bootstrap promotion and the admin CLI.
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    action = Column(String(60), nullable=False, index=True)
    target_kind = Column(String(40), nullable=False, default="")
    target_id = Column(String(80), nullable=False, default="")
    detail = Column(Text, nullable=False, default="{}")
    created_at = Column(String, default=now)


class Forum(Base):
    """An administrator-managed site forum; archived forums are read-only."""

    __tablename__ = "forums"
    id = Column(Integer, primary_key=True)
    slug = Column(String(80), nullable=False, unique=True)
    title = Column(String(80), nullable=False)
    description = Column(Text, nullable=False, default="")
    position = Column(Integer, nullable=False, default=0)
    archived = Column(Integer, nullable=False, default=0)
    created_at = Column(String, default=now)


class LegacyDiscussionMap(Base):
    """Legacy discussions/comments copied into the General forum, keyed by old id."""

    __tablename__ = "legacy_discussion_map"
    kind = Column(String(20), primary_key=True)
    legacy_id = Column(Integer, primary_key=True)
    new_id = Column(Integer, nullable=False)


class ContentRevision(Base):
    """The previous text of an edited or author-deleted topic, comment or reply."""

    __tablename__ = "content_revisions"
    __table_args__ = (Index("ix_content_revisions_target", "target_kind", "target_id"),)
    id = Column(Integer, primary_key=True)
    target_kind = Column(String(32), nullable=False)
    target_id = Column(Integer, nullable=False)
    editor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    title = Column(String(160), nullable=True)
    body = Column(Text, nullable=False)
    created_at = Column(String, default=now)


class Vote(Base):
    """One upvote per user on a notebook, dataset, model, topic, comment or reply."""

    __tablename__ = "votes"
    __table_args__ = (
        UniqueConstraint("target_kind", "target_id", "user_id"),
        Index("ix_votes_target", "target_kind", "target_id"),
    )
    id = Column(Integer, primary_key=True)
    target_kind = Column(String(32), nullable=False)
    target_id = Column(Integer, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(String, default=now)


class TopicWatch(Base):
    __tablename__ = "topic_watches"
    post_id = Column(
        Integer,
        ForeignKey("competition_posts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_recipient", "recipient_id", "read_at"),)
    id = Column(Integer, primary_key=True)
    recipient_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    kind = Column(String(20), nullable=False)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    target_kind = Column(String(32), nullable=False, default="")
    target_id = Column(Integer, nullable=True)
    url = Column(String(255), nullable=False, default="")
    # Kind-specific JSON, e.g. the rank and medal of a competition result.
    detail = Column(Text, nullable=False, default="{}")
    # Coalesced events (such as votes on one item per day) share a group key.
    group_key = Column(String(120), nullable=True, index=True)
    count = Column(Integer, nullable=False, default=1)
    read_at = Column(String, nullable=True)
    created_at = Column(String, default=now)


class NotificationPreference(Base):
    """Opt-outs per notification kind; a missing row means enabled."""

    __tablename__ = "notification_preferences"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    kind = Column(String(20), primary_key=True)
    enabled = Column(Integer, nullable=False, default=1)


class Follow(Base):
    __tablename__ = "follows"
    follower_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    followee_id = Column(Integer, ForeignKey("users.id"), primary_key=True, index=True)
    created_at = Column(String, default=now)


class NotebookRun(Base):
    """A background Save & Run All of a saved notebook version; see notebook_runs.py."""

    __tablename__ = "notebook_runs"
    # One run per schedule slot, so restarts cannot enqueue the same slot twice.
    __table_args__ = (UniqueConstraint("schedule_id", "scheduled_for"),)
    id = Column(Integer, primary_key=True)
    notebook_id = Column(
        Integer, ForeignKey("notebooks.id"), nullable=False, index=True
    )
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    # The saved version that was run; null for legacy notebooks without versions.
    version_id = Column(Integer, nullable=True)
    executed_version_id = Column(Integer, nullable=True)
    document = Column(Text, nullable=False)
    # queued, running, succeeded, failed, cancelled or timed_out.
    status = Column(String(12), nullable=False, default="queued", index=True)
    accelerator = Column(String(3), nullable=False, default="cpu")
    # "manual" or "schedule".
    trigger = Column(String(10), nullable=False, default="manual")
    schedule_id = Column(Integer, nullable=True, index=True)
    scheduled_for = Column(Float, nullable=True)
    log = Column(Text, nullable=False, default="")
    error = Column(Text, nullable=False, default="")
    output_files = Column(Integer, nullable=False, default=0)
    created_at = Column(String, default=now)
    started_at = Column(String, nullable=True)
    finished_at = Column(String, nullable=True)


class NotebookSchedule(Base):
    __tablename__ = "notebook_schedules"
    id = Column(Integer, primary_key=True)
    notebook_id = Column(
        Integer, ForeignKey("notebooks.id"), nullable=False, index=True
    )
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # "daily" and "weekly" run at time_utc; "hourly" runs every interval_hours.
    frequency = Column(String(10), nullable=False)
    time_utc = Column(String(5), nullable=False, default="00:00")
    # 0 is Monday, as in datetime.weekday().
    weekday = Column(Integer, nullable=False, default=0)
    interval_hours = Column(Integer, nullable=False, default=24)
    accelerator = Column(String(3), nullable=False, default="cpu")
    # active, paused or disabled (after repeated failures).
    status = Column(String(10), nullable=False, default="active")
    consecutive_failures = Column(Integer, nullable=False, default=0)
    # Epoch seconds (UTC). Hourly schedules count intervals from anchor_at.
    next_run_at = Column(Float, nullable=True, index=True)
    anchor_at = Column(Float, nullable=False)
    disabled_reason = Column(Text, nullable=False, default="")
    created_at = Column(String, default=now)
    updated_at = Column(String, default=now, onupdate=now)


class GpuUsage(Base):
    """One GPU allocation; open rows (ended_at null) hold GPU capacity."""

    __tablename__ = "gpu_usage"
    __table_args__ = (Index("ix_gpu_usage_user_started", "user_id", "started_at"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    # session, run or attempt (charged to the weekly quota); commit or benchmark.
    kind = Column(String(12), nullable=False)
    ref_id = Column(Integer, nullable=True)
    gpus = Column(Integer, nullable=False, default=1)
    # Epoch seconds (UTC).
    started_at = Column(Float, nullable=False)
    ended_at = Column(Float, nullable=True, index=True)
    # Last time the Hub reported an interactive GPU session running.
    last_seen_at = Column(Float, nullable=True)
    created_at = Column(String, default=now)


class NotebookDraftExercise(Base):
    """Exercise whose prompt and starter code seed a new notebook draft."""

    __tablename__ = "notebook_draft_exercises"
    draft_id = Column(
        String(32),
        ForeignKey("notebook_drafts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    exercise_id = Column(Integer, ForeignKey("course_exercises.id"), nullable=False)


class UserProgression(Base):
    """Recomputable medal counts and tier per user and category; see progression.py."""

    __tablename__ = "user_progression"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    category = Column(String(20), primary_key=True)
    tier = Column(Integer, nullable=False, default=0)
    gold = Column(Integer, nullable=False, default=0)
    silver = Column(Integer, nullable=False, default=0)
    bronze = Column(Integer, nullable=False, default=0)
    # When the current medal count was reached; earlier ranks first on ties.
    achieved_at = Column(String, nullable=True)
    updated_at = Column(String, default=now, onupdate=now)
