"""Competition lifecycle policy: timeline, rules acceptance, daily limits and hosts."""

import json
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, select

from .models import (
    ChallengeDetails,
    Competition,
    CompetitionOverview,
    CompetitionSource,
    CompetitionTeamMember,
    Entry,
    NotebookCommit,
    Submission,
    SubmissionPrediction,
    SubmissionTeam,
)
from .permissions import can_manage
from .scoring import get_metric


def utcnow():
    return datetime.now(timezone.utc)


def parse_time(value):
    """Aware datetime from a stored ISO string; naive values are treated as UTC."""
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def iso(value):
    return value.astimezone(timezone.utc).isoformat() if value else None


def has_deadline(db, competition):
    """Practice competitions, ongoing imports and CSV benchmarks never close."""
    if competition.deadline.startswith("9999-"):
        return False
    source = db.get(CompetitionSource, competition.id)
    details = db.get(ChallengeDetails, competition.id)
    return not (source and source.ongoing) and not (
        details and details.kind == "benchmark"
    )


@dataclass
class Timeline:
    starts_at: Optional[datetime] = None
    entry_deadline: Optional[datetime] = None
    merger_deadline: Optional[datetime] = None
    ends_at: Optional[datetime] = None

    def passed(self, *limits):
        """True after the earliest of the given deadlines and the end."""
        values = [value for value in (*limits, self.ends_at) if value]
        return bool(values and utcnow() > min(values))

    def started(self):
        return not self.starts_at or utcnow() >= self.starts_at

    def ended(self):
        return self.passed()

    def entry_open(self):
        return not self.passed(self.entry_deadline)

    def team_forming_open(self):
        return not self.passed(self.entry_deadline, self.merger_deadline)

    def team_changes_open(self):
        return not self.passed(self.merger_deadline)

    def json(self):
        return {
            "starts_at": iso(self.starts_at),
            "entry_deadline": iso(self.entry_deadline),
            "merger_deadline": iso(self.merger_deadline),
            "ends_at": iso(self.ends_at),
            "started": self.started(),
            "entry_open": self.entry_open(),
            "team_forming_open": self.team_forming_open(),
            "team_changes_open": self.team_changes_open(),
            "ended": self.ended(),
        }


def timeline(db, competition):
    """Effective timeline; competitions without a deadline have no time limits."""
    if not has_deadline(db, competition):
        return Timeline()
    overview = db.get(CompetitionOverview, competition.id)
    return Timeline(
        parse_time(overview.starts_at if overview else None),
        parse_time(competition.entry_deadline),
        parse_time(competition.merger_deadline),
        parse_time(competition.deadline),
    )


def require_submission_window(db, competition):
    times = timeline(db, competition)
    if not times.started():
        raise HTTPException(
            409,
            f"Submissions open when the competition starts at {iso(times.starts_at)}",
        )
    if times.ended():
        raise HTTPException(409, "Competition has closed")
    return times


def set_timeline(db, competition, starts, entry, merger, ends):
    values = [value for value in (starts, entry, merger, ends) if value is not None]
    if ends is None or any(value.tzinfo is None for value in values):
        raise HTTPException(
            422, "Use timezone-aware dates; the start must precede the deadline"
        )
    if starts and starts >= ends:
        raise HTTPException(422, "The start must precede the deadline")
    for label, value in (("entry deadline", entry), ("team merger deadline", merger)):
        if value and (value > ends or (starts and value <= starts)):
            raise HTTPException(
                422, f"The {label} must fall between the start and the end"
            )
    overview = db.get(CompetitionOverview, competition.id)
    if not overview:
        overview = CompetitionOverview(competition_id=competition.id)
        db.add(overview)
    overview.starts_at = iso(starts)
    competition.entry_deadline = iso(entry)
    competition.merger_deadline = iso(merger)
    competition.deadline = iso(ends)
    return overview


def entry_for(db, competition_id, user):
    return db.scalar(
        select(Entry).where(
            Entry.competition_id == competition_id, Entry.user_id == user.id
        )
    )


def needs_rules(competition, entry):
    return bool(entry) and (entry.rules_revision or 0) < competition.rules_revision


def require_current_rules(db, competition, user, action="submitting"):
    entry = entry_for(db, competition.id, user)
    if not entry:
        raise HTTPException(403, f"Join the competition before {action}")
    if needs_rules(competition, entry):
        raise HTTPException(
            409,
            f"The competition rules changed (revision {competition.rules_revision}). "
            f"Review and accept the current rules before {action}.",
        )
    return entry


def team_for(db, competition_id, user_id):
    return db.scalar(
        select(CompetitionTeamMember.team_id).where(
            CompetitionTeamMember.competition_id == competition_id,
            CompetitionTeamMember.user_id == user_id,
        )
    )


def submissions_today(db, competition, user):
    """(Used today, team id): scored submissions this UTC day plus pending commits."""
    today = utcnow().date()
    team_id = team_for(db, competition.id, user.id)
    scored = (
        select(func.count())
        .select_from(Submission)
        .outerjoin(SubmissionTeam, SubmissionTeam.submission_id == Submission.id)
        .where(
            Submission.competition_id == competition.id,
            # Timestamps are UTC ISO strings, so date prefixes order correctly.
            Submission.created_at >= today.isoformat(),
            Submission.created_at < (today + timedelta(days=1)).isoformat(),
        )
    )
    if team_id:
        scored = scored.where(SubmissionTeam.team_id == team_id)
        owners = list(
            db.scalars(
                select(CompetitionTeamMember.user_id).where(
                    CompetitionTeamMember.team_id == team_id
                )
            )
        )
    else:
        scored = scored.where(
            SubmissionTeam.team_id.is_(None), Submission.user_id == user.id
        )
        owners = [user.id]
    # Queued and running commits become scored submissions when they finish.
    pending = (
        select(func.count())
        .select_from(NotebookCommit)
        .where(
            NotebookCommit.competition_id == competition.id,
            NotebookCommit.owner_id.in_(owners),
            NotebookCommit.status.in_(["queued", "running"]),
        )
    )
    return db.scalar(scored) + db.scalar(pending), team_id


def require_daily_capacity(db, competition, user):
    used, team_id = submissions_today(db, competition, user)
    if used >= competition.max_daily_submissions:
        raise HTTPException(
            429,
            f"Daily submission limit reached: {competition.max_daily_submissions} per "
            f"UTC day for your {'team' if team_id else 'entry'}, including queued "
            "notebook commits. The count resets at 00:00 UTC.",
        )


def store_predictions(db, submission, content):
    db.flush()
    db.add(
        SubmissionPrediction(
            submission_id=submission.id, content=zlib.compress(content)
        )
    )


def competition_owner(db, competition_id):
    details = db.get(ChallengeDetails, competition_id)
    return details.owner_id if details else None


def can_host(db, competition, user):
    """Creators host their competitions; administrators host any, including legacy."""
    return can_manage(user, competition_owner(db, competition.id))


def require_host(db, id, user, lock=False):
    query = select(Competition).where(Competition.id == id)
    competition = db.scalar(query.with_for_update() if lock else query)
    if not competition:
        raise HTTPException(404, "Competition not found")
    if not can_host(db, competition, user):
        raise HTTPException(403, "Only the competition host can use host tools")
    return competition


def solution_usage(competition):
    return json.loads(competition.solution_usage or "{}")


def has_private_split(competition):
    return {"Public", "Private"} <= set(solution_usage(competition).values())


def reveal_private(db, competition, user):
    """Private scores are published at the end; hosts may preview them earlier."""
    return timeline(db, competition).ended() or can_host(db, competition, user)


def metric_info(competition):
    try:
        metric = get_metric(competition.metric)
    except ValueError:
        return {
            "metric_label": competition.metric,
            "metric_direction": "lower",
            "metric_uses_k": False,
        }
    return {
        "metric_label": metric.display(competition.metric_k),
        "metric_direction": metric.direction,
        "metric_uses_k": metric.uses_k,
    }


def submission_json(submission, reveal, team_id=None, submitter=None):
    """Participant view of a submission; the private score only when revealed."""
    row = {
        "id": submission.id,
        "competition_id": submission.competition_id,
        "user_id": submission.user_id,
        "filename": submission.filename,
        "score": submission.score,
        "created_at": submission.created_at,
        "final_selected": bool(submission.final_selected),
        "team_id": team_id,
    }
    if submitter is not None:
        row["submitter"] = submitter
    if reveal:
        row["private_score"] = submission.private_score
    return row
