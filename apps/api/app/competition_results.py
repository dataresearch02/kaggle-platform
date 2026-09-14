"""Idempotent finalization: final private ranks, medals, leaderboards and rescoring."""

import json
import zlib

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .accounts import visible_profile
from .code_pages import optional_user
from .competition_policy import has_deadline, solution_usage, timeline
from .db import get_db
from .models import (
    ChallengeDetails,
    Competition,
    CompetitionResult,
    CompetitionTeam,
    CompetitionTeamMember,
    Entry,
    Submission,
    SubmissionPrediction,
    now,
)
from .moderation import record
from .scoring import evaluate
from .team_scoring import entity_key, final_ranking, public_ranking

router = APIRouter(prefix="/api", tags=["Competition results"])


def medal_cutoffs(teams):
    """Last (gold, silver, bronze) ranks under Kaggle's thresholds for `teams`."""
    if teams < 100:
        return teams * 10 // 100, teams * 20 // 100, teams * 40 // 100
    if teams < 250:
        return 10, teams * 20 // 100, teams * 40 // 100
    if teams < 1000:
        return 10 + teams * 2 // 1000, 50, 100
    return 10 + teams * 2 // 1000, teams * 5 // 100, teams * 10 // 100


def medal_for(rank, teams):
    gold, silver, bronze = medal_cutoffs(teams)
    if rank <= gold:
        return "gold"
    if rank <= silver:
        return "silver"
    if rank <= bronze:
        return "bronze"
    return None


def awards_medals(db, competition):
    """Practice competitions (no deadline) and CSV benchmarks award no medals."""
    details = db.get(ChallengeDetails, competition.id)
    return has_deadline(db, competition) and not (
        details and details.kind == "benchmark"
    )


def finalize(db, competition, actor=None, force=False):
    """Store final ranks and medals once the competition has ended. Callers commit.

    Safe to repeat: stored results are replaced, and without `force` an already
    finalized competition is left unchanged.
    """
    locked = db.scalar(
        select(Competition)
        .where(Competition.id == competition.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not timeline(db, locked).ended() or (locked.finalized_at and not force):
        return False
    ranking = final_ranking(db, locked)
    medals = awards_medals(db, locked)
    from .progression import mark_dirty

    mark_dirty(
        db,
        *db.scalars(
            select(CompetitionResult.user_id).where(
                CompetitionResult.competition_id == locked.id
            )
        ),
    )
    db.execute(
        delete(CompetitionResult).where(CompetitionResult.competition_id == locked.id)
    )
    awarded, placed = {}, set()
    for row in ranking:
        medal = medal_for(row["rank"], len(ranking)) if medals else None
        if medal:
            awarded[medal] = awarded.get(medal, 0) + 1
        # Team placements and medals go to every team member.
        members = (
            db.scalars(
                select(CompetitionTeamMember.user_id)
                .where(CompetitionTeamMember.team_id == row["team_id"])
                .order_by(CompetitionTeamMember.id)
            )
            if row["team_id"] is not None
            else [row["user_id"]]
        )
        for user_id in members:
            if user_id in placed:
                continue
            placed.add(user_id)
            db.add(
                CompetitionResult(
                    competition_id=locked.id,
                    user_id=user_id,
                    team_id=row["team_id"],
                    rank=row["rank"],
                    team_count=len(ranking),
                    medal=medal,
                    score=row["score"],
                )
            )
    locked.finalized_at = now()
    db.flush()
    from .notifications import notify

    mark_dirty(db, *placed)
    for result in db.scalars(
        select(CompetitionResult).where(CompetitionResult.competition_id == locked.id)
    ):
        notify(
            db,
            result.user_id,
            "result",
            target_kind="competition",
            target_id=locked.id,
            detail={
                "rank": result.rank,
                "team_count": result.team_count,
                "medal": result.medal,
            },
            # One notification per competition, refreshed if results change.
            group_key=f"result:{locked.id}",
            replace=True,
        )
    record(
        db,
        actor,
        "competition.finalize",
        "competition",
        locked.id,
        {"teams": len(ranking), "medals": awarded},
    )
    return True


def finalize_if_due(db, competition):
    """Lazy finalization on first access after the end."""
    if not competition.finalized_at and timeline(db, competition).ended():
        if finalize(db, competition):
            db.commit()


def refresh_results(db, competition, actor=None):
    """Keep stored results in step with rescoring, disqualification and timeline edits."""
    if timeline(db, competition).ended():
        finalize(db, competition, actor, force=True)
    elif competition.finalized_at:
        from .progression import mark_dirty

        mark_dirty(
            db,
            *db.scalars(
                select(CompetitionResult.user_id).where(
                    CompetitionResult.competition_id == competition.id
                )
            ),
        )
        db.execute(
            delete(CompetitionResult).where(
                CompetitionResult.competition_id == competition.id
            )
        )
        competition.finalized_at = None


def rescore(db, competition):
    """Rescore submissions whose original predictions are stored. Callers commit."""
    counts = {"rescored": 0, "skipped": 0, "failed": 0}
    solution = json.loads(competition.solution)
    if not solution:
        return counts
    usage = solution_usage(competition)
    for submission, content in db.execute(
        select(Submission, SubmissionPrediction.content)
        .outerjoin(
            SubmissionPrediction, SubmissionPrediction.submission_id == Submission.id
        )
        .where(Submission.competition_id == competition.id)
        .order_by(Submission.id)
    ).all():
        if content is None:
            counts["skipped"] += 1  # Legacy rows keep their score as public.
            continue
        try:
            submission.score, submission.private_score = evaluate(
                zlib.decompress(content),
                solution,
                competition.metric,
                usage,
                competition.metric_k,
            )
        except ValueError:
            counts["failed"] += 1  # Keeps the previous scores.
            continue
        counts["rescored"] += 1
    return counts


def board_rows(db, competition, board):
    """Public or final (private) leaderboard rows with shake-up and medals."""
    if board == "public":
        rows = public_ranking(db, competition)
    else:
        rows = final_ranking(db, competition)
        public = {
            entity_key(row): row["rank"] for row in public_ranking(db, competition)
        }
        medals = {}
        if competition.finalized_at:
            for result in db.scalars(
                select(CompetitionResult).where(
                    CompetitionResult.competition_id == competition.id
                )
            ):
                team = {"team_id": result.team_id, "user_id": result.user_id}
                medals[entity_key(team)] = result.medal
        for row in rows:
            row["public_rank"] = public.get(entity_key(row))
            row["medal"] = medals.get(entity_key(row))
    return [
        {
            "rank": row["rank"],
            "username": row["name"],
            "score": row["score"],
            "entries": row["entries"],
            **({"team_id": row["team_id"]} if row["team_id"] is not None else {}),
            **(
                {
                    "public_rank": row["public_rank"],
                    "medal": row["medal"],
                    "automatic_selection": row["automatic_selection"],
                }
                if board == "private"
                else {}
            ),
        }
        for row in rows
    ]


@router.get("/profiles/{username}/competitions")
def profile_results(
    username: str, user=Depends(optional_user), db: Session = Depends(get_db)
):
    """Final placements for a visible profile, newest first."""
    owner = visible_profile(db, username, user)
    for competition in list(
        db.scalars(
            select(Competition)
            .join(Entry, Entry.competition_id == Competition.id)
            .where(Entry.user_id == owner.id, Competition.finalized_at.is_(None))
        )
    ):
        finalize_if_due(db, competition)
    rows = db.execute(
        select(CompetitionResult, Competition.title, CompetitionTeam.name)
        .join(Competition, Competition.id == CompetitionResult.competition_id)
        .outerjoin(CompetitionTeam, CompetitionTeam.id == CompetitionResult.team_id)
        .where(CompetitionResult.user_id == owner.id)
        .order_by(CompetitionResult.id.desc())
    ).all()
    return [
        {
            "competition_id": result.competition_id,
            "title": title,
            "rank": result.rank,
            "team_count": result.team_count,
            "medal": result.medal,
            "score": result.score,
            "team_id": result.team_id,
            "team_name": team_name,
            "finalized_at": result.created_at,
        }
        for result, title, team_name in rows
    ]
