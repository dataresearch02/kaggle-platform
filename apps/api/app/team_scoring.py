"""Historical team attribution and ranking independent of later membership."""

from sqlalchemy import select, func, or_
from .models import (
    Submission,
    SubmissionTeam,
    CompetitionTeam,
    CompetitionTeamMember,
    User,
)


def attach_team(db, submission):
    member = db.scalar(
        select(CompetitionTeamMember).where(
            CompetitionTeamMember.competition_id == submission.competition_id,
            CompetitionTeamMember.user_id == submission.user_id,
        )
    )
    if member:
        db.flush()
        db.add(SubmissionTeam(submission_id=submission.id, team_id=member.team_id))


def history_filter(db, competition_id, user):
    member = db.scalar(
        select(CompetitionTeamMember).where(
            CompetitionTeamMember.competition_id == competition_id,
            CompetitionTeamMember.user_id == user.id,
        )
    )
    if not member:
        return Submission.user_id == user.id
    return or_(
        Submission.user_id == user.id,
        Submission.id.in_(
            select(SubmissionTeam.submission_id).where(
                SubmissionTeam.team_id == member.team_id
            )
        ),
    )


def leaderboard(db, competition):
    from sqlalchemy import case

    score = (
        func.max(Submission.score)
        if competition.metric == "Accuracy"
        else func.min(Submission.score)
    )
    identity = case(
        (SubmissionTeam.team_id.is_not(None), SubmissionTeam.team_id),
        else_=Submission.user_id,
    )
    kind = case((SubmissionTeam.team_id.is_not(None), "team"), else_="user")
    name = func.coalesce(CompetitionTeam.name, User.username)
    rows = db.execute(
        select(SubmissionTeam.team_id, name.label("name"), score.label("score"))
        .select_from(Submission)
        .join(User, User.id == Submission.user_id)
        .outerjoin(SubmissionTeam, SubmissionTeam.submission_id == Submission.id)
        .outerjoin(CompetitionTeam, CompetitionTeam.id == SubmissionTeam.team_id)
        .where(Submission.competition_id == competition.id)
        .group_by(kind, identity, SubmissionTeam.team_id, name)
        .order_by(score.desc() if competition.metric == "Accuracy" else score, name)
        .limit(100)
    ).all()
    return [
        {
            "rank": index + 1,
            "username": (
                f"{row.name} (Team #{row.team_id})" if row.team_id else row.name
            ),
            "score": row.score,
            **({"team_id": row.team_id} if row.team_id else {}),
        }
        for index, row in enumerate(rows)
    ]
