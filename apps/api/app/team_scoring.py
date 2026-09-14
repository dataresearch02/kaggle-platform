"""Historical team attribution and rankings independent of later membership."""

from sqlalchemy import and_, case, func, or_, select
from .models import (
    CompetitionDisqualification,
    Submission,
    SubmissionTeam,
    CompetitionTeam,
    CompetitionTeamMember,
    User,
)
from .scoring import get_metric


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
    return member.team_id if member else None


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


def owner_filter(team_id, user_id):
    """Submissions of one leaderboard entry: a team, or a user's solo entry."""
    if team_id is not None:
        return Submission.id.in_(
            select(SubmissionTeam.submission_id).where(
                SubmissionTeam.team_id == team_id
            )
        )
    return and_(
        Submission.user_id == user_id,
        Submission.id.not_in(select(SubmissionTeam.submission_id)),
    )


def disqualified(db, competition_id):
    """(Team ids, solo user ids) excluded from leaderboards and medals."""
    rows = db.execute(
        select(
            CompetitionDisqualification.team_id, CompetitionDisqualification.user_id
        ).where(CompetitionDisqualification.competition_id == competition_id)
    ).all()
    return (
        sorted({row.team_id for row in rows if row.team_id is not None}),
        sorted({row.user_id for row in rows if row.user_id is not None}),
    )


def eligible(db, competition):
    teams, users = disqualified(db, competition.id)
    return or_(
        and_(SubmissionTeam.team_id.is_(None), Submission.user_id.not_in(users)),
        and_(SubmissionTeam.team_id.is_not(None), SubmissionTeam.team_id.not_in(teams)),
    )


def higher_is_better(competition):
    try:
        return get_metric(competition.metric).higher_is_better
    except ValueError:
        return False


def leaderboard_size(db, competition):
    identity = func.coalesce(
        SubmissionTeam.team_id, -Submission.user_id
    )  # Team ids are positive; negated user ids cannot collide with them.
    return db.scalar(
        select(func.count(func.distinct(identity)))
        .select_from(Submission)
        .outerjoin(SubmissionTeam, SubmissionTeam.submission_id == Submission.id)
        .where(Submission.competition_id == competition.id, eligible(db, competition))
    )


def leaderboard(db, competition, offset=0, limit=100):
    """Public leaderboard: each entry's best public score."""
    higher = higher_is_better(competition)
    score = func.max(Submission.score) if higher else func.min(Submission.score)
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
        .where(Submission.competition_id == competition.id, eligible(db, competition))
        .group_by(kind, identity, SubmissionTeam.team_id, name)
        .order_by(score.desc() if higher else score, name)
        .offset(offset)
        .limit(limit)
    ).all()
    return [
        {
            "rank": offset + index + 1,
            "username": (
                f"{row.name} (Team #{row.team_id})" if row.team_id else row.name
            ),
            "score": row.score,
            **({"team_id": row.team_id} if row.team_id else {}),
        }
        for index, row in enumerate(rows)
    ]


def entities(db, competition):
    """Scored submissions grouped by team or solo user, without disqualified entries."""
    teams, users = disqualified(db, competition.id)
    groups = {}
    for submission, team_id, team_name, username in db.execute(
        select(Submission, SubmissionTeam.team_id, CompetitionTeam.name, User.username)
        .join(User, User.id == Submission.user_id)
        .outerjoin(SubmissionTeam, SubmissionTeam.submission_id == Submission.id)
        .outerjoin(CompetitionTeam, CompetitionTeam.id == SubmissionTeam.team_id)
        .where(Submission.competition_id == competition.id)
        .order_by(Submission.id)
    ):
        if team_id in teams if team_id is not None else submission.user_id in users:
            continue
        key = ("team", team_id) if team_id is not None else ("user", submission.user_id)
        group = groups.setdefault(
            key,
            {
                "team_id": team_id,
                "user_id": None if team_id is not None else submission.user_id,
                "name": (
                    f"{team_name or 'Deleted team'} (Team #{team_id})"
                    if team_id is not None
                    else username
                ),
                "submissions": [],
            },
        )
        group["submissions"].append(submission)
    return groups


def entity_key(row):
    if row["team_id"] is not None:
        return ("team", row["team_id"])
    return ("user", row["user_id"])


def summarize(group, best, score, **extra):
    return {
        "team_id": group["team_id"],
        "user_id": group["user_id"],
        "name": group["name"],
        "score": score,
        "submission_id": best.id,
        "entries": len(group["submissions"]),
        **extra,
    }


def ranked(rows, higher, tiebreak):
    rows.sort(
        key=lambda row: (-row["score"] if higher else row["score"], row[tiebreak])
    )
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def public_ranking(db, competition):
    """The public leaderboard order, as ranked by `leaderboard`."""
    higher = higher_is_better(competition)
    rows = []
    for group in entities(db, competition).values():
        best = min(
            group["submissions"],
            key=lambda row: (-row.score if higher else row.score, row.id),
        )
        rows.append(summarize(group, best, best.score))
    return ranked(rows, higher, "name")


def final_ranking(db, competition):
    """Each entry's best private score among its final submissions (Kaggle rules).

    Without an explicit selection the entry's best public submissions are used, up
    to the final-selection limit. Competitions without a split rank on all rows.
    Ties go to the earlier submission.
    """
    from .competition_policy import has_private_split

    higher = higher_is_better(competition)
    private = has_private_split(competition)

    def order(value, submission):
        return (-value if higher else value, submission.id)

    rows = []
    for group in entities(db, competition).values():
        chosen = [row for row in group["submissions"] if row.final_selected]
        automatic = not chosen
        if automatic:
            chosen = sorted(
                group["submissions"], key=lambda row: order(row.score, row)
            )[: competition.max_final_submissions]
        scored = [
            (row.private_score if private else row.score, row)
            for row in chosen
            if (row.private_score if private else row.score) is not None
        ]
        if not scored:
            continue  # Legacy submissions without stored predictions have no score.
        score, best = min(scored, key=lambda item: order(*item))
        rows.append(summarize(group, best, score, automatic_selection=automatic))
    return ranked(rows, higher, "submission_id")
