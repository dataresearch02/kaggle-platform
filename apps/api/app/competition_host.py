"""Host tools, rules, final submission selection and the metric registry API."""

import csv
import io
import json
from datetime import datetime
from typing import Literal, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .auth import current_user
from .competition_policy import (
    has_deadline,
    metric_info,
    require_host,
    set_timeline,
    solution_usage,
    submission_json,
    team_for,
    timeline,
)
from .competition_results import (
    board_rows,
    finalize,
    finalize_if_due,
    refresh_results,
    rescore,
)
from .db import get_db
from .models import (
    Competition,
    CompetitionDisqualification,
    CompetitionResult,
    CompetitionTeam,
    Entry,
    Submission,
    SubmissionPrediction,
    SubmissionTeam,
    User,
    now,
)
from .moderation import record
from .pagination import Page, count, page, set_total, window
from .scoring import (
    DEFAULT_K,
    METRICS,
    assign_usage,
    get_metric,
    normalize_answers,
    read_answers,
    split,
    storable,
    validate_split,
)
from .team_scoring import disqualified, owner_filter

router = APIRouter(prefix="/api", tags=["Competition hosting"])


@router.get("/metrics")
def metrics():
    return [metric.describe() for metric in METRICS.values()]


def host_state(db, competition):
    solution = json.loads(competition.solution)
    public, private = split(solution, solution_usage(competition))
    return {
        "id": competition.id,
        **timeline(db, competition).json(),
        "has_deadline": has_deadline(db, competition),
        "metric": competition.metric,
        "metric_k": competition.metric_k,
        **metric_info(competition),
        "max_daily_submissions": competition.max_daily_submissions,
        "max_final_submissions": competition.max_final_submissions,
        "rules": competition.rules,
        "rules_revision": competition.rules_revision,
        "rules_updated_at": competition.rules_updated_at,
        "evaluation_available": bool(solution),
        "public_rows": len(public) if solution else 0,
        "private_rows": len(private or []),
        "finalized_at": competition.finalized_at,
        "participants": db.scalar(
            select(func.count())
            .select_from(Entry)
            .where(Entry.competition_id == competition.id)
        ),
        "submissions": db.scalar(
            select(func.count())
            .select_from(Submission)
            .where(Submission.competition_id == competition.id)
        ),
        "rescorable": db.scalar(
            select(func.count())
            .select_from(SubmissionPrediction)
            .join(Submission, Submission.id == SubmissionPrediction.submission_id)
            .where(Submission.competition_id == competition.id)
        ),
    }


@router.get("/competitions/{id}/host")
def host_overview(id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    competition = require_host(db, id, user)
    finalize_if_due(db, competition)
    return host_state(db, competition)


class SettingsInput(BaseModel):
    starts_at: Optional[datetime] = None
    entry_deadline: Optional[datetime] = None
    merger_deadline: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    max_daily_submissions: int = Field(ge=1, le=100)
    max_final_submissions: int = Field(ge=1, le=10)
    metric: str = Field(max_length=30)
    metric_k: Optional[int] = Field(default=None, ge=1, le=100)


@router.put("/competitions/{id}/host/settings")
def update_settings(
    id: int,
    data: SettingsInput,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    competition = require_host(db, id, user, lock=True)
    before = host_state(db, competition)
    if has_deadline(db, competition):
        set_timeline(
            db,
            competition,
            data.starts_at,
            data.entry_deadline,
            data.merger_deadline,
            data.ends_at,
        )
    elif any((data.starts_at, data.entry_deadline, data.merger_deadline, data.ends_at)):
        raise HTTPException(
            422, "Practice competitions and benchmarks have no timeline to edit"
        )
    try:
        metric = get_metric(data.metric)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    k = (data.metric_k or DEFAULT_K) if metric.uses_k else None
    metric_changed = (metric.name, k) != (competition.metric, competition.metric_k)
    if metric_changed and json.loads(competition.solution):
        try:
            answers = normalize_answers(json.loads(competition.solution), metric)
            validate_split(answers, solution_usage(competition), metric, k)
        except ValueError as exc:
            raise HTTPException(
                422, f"The current answers cannot be scored with {metric.label}: {exc}"
            )
        competition.solution = json.dumps(storable(answers))
    competition.metric, competition.metric_k = metric.name, k
    competition.max_daily_submissions = data.max_daily_submissions
    competition.max_final_submissions = data.max_final_submissions
    rescored = rescore(db, competition) if metric_changed else None
    db.flush()
    after = host_state(db, competition)
    changes = {
        key: {"from": before[key], "to": after[key]}
        for key in (
            "starts_at",
            "entry_deadline",
            "merger_deadline",
            "ends_at",
            "metric",
            "metric_k",
            "max_daily_submissions",
            "max_final_submissions",
        )
        if before[key] != after[key]
    }
    if changes:
        record(
            db,
            user,
            "competition.settings",
            "competition",
            id,
            {"changes": changes, **({"rescore": rescored} if rescored else {})},
        )
    refresh_results(db, competition, user)
    db.commit()
    return {**host_state(db, competition), "rescore": rescored}


class RulesInput(BaseModel):
    content: str = Field(default="", max_length=50000)
    # Material changes require every member to accept the rules again.
    material: bool = False


@router.put("/competitions/{id}/rules")
def update_rules(
    id: int, data: RulesInput, user=Depends(current_user), db: Session = Depends(get_db)
):
    competition = require_host(db, id, user, lock=True)
    competition.rules = data.content
    if data.material:
        competition.rules_revision += 1
    competition.rules_updated_at = now()
    record(
        db,
        user,
        "competition.rules",
        "competition",
        id,
        {"revision": competition.rules_revision, "material": data.material},
    )
    db.commit()
    return {
        "rules": competition.rules,
        "rules_revision": competition.rules_revision,
        "rules_updated_at": competition.rules_updated_at,
    }


@router.put("/competitions/{id}/host/solution")
async def replace_solution(
    id: int,
    solution_file: UploadFile = File(),
    public_fraction: Optional[float] = Form(default=None, gt=0, lt=1),
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    competition = require_host(db, id, user, lock=True)
    current = json.loads(competition.solution)
    if not current:
        raise HTTPException(409, "This competition has no local answers to replace")
    content = await solution_file.read(1024 * 1024 + 1)
    if len(content) > 1024 * 1024:
        raise HTTPException(413, "File exceeds 1 MB limit")
    metric = get_metric(competition.metric)
    try:
        answers, usage = read_answers(content, list(current), metric)
        if usage is None:
            usage = (
                assign_usage(answers, public_fraction)
                if public_fraction is not None
                else solution_usage(competition)
            )
        validate_split(answers, usage, metric, competition.metric_k)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    competition.solution = json.dumps(storable(answers))
    competition.solution_usage = json.dumps(usage)
    counts = rescore(db, competition)
    public, private = split(answers, usage)
    record(
        db,
        user,
        "competition.solution",
        "competition",
        id,
        {"public_rows": len(public), "private_rows": len(private or []), **counts},
    )
    refresh_results(db, competition, user)
    db.commit()
    return {**host_state(db, competition), "rescore": counts}


@router.post("/competitions/{id}/host/rescore")
def rescore_all(id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    competition = require_host(db, id, user, lock=True)
    if not json.loads(competition.solution):
        raise HTTPException(409, "Local scoring is unavailable for this competition")
    counts = rescore(db, competition)
    record(db, user, "competition.rescore", "competition", id, counts)
    refresh_results(db, competition, user)
    db.commit()
    return counts


@router.post("/competitions/{id}/host/finalize")
def finalize_now(id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    competition = require_host(db, id, user, lock=True)
    if not has_deadline(db, competition):
        raise HTTPException(
            409, "Practice competitions and benchmarks have no final results"
        )
    if not timeline(db, competition).ended():
        raise HTTPException(409, "The competition has not ended yet")
    finalize(db, competition, user, force=True)
    db.commit()
    results = list(
        db.scalars(
            select(CompetitionResult).where(CompetitionResult.competition_id == id)
        )
    )
    return {
        "finalized_at": competition.finalized_at,
        "teams": results[0].team_count if results else 0,
        "medals": {
            medal: len(
                {row.team_id or -row.user_id for row in results if row.medal == medal}
            )
            for medal in ("gold", "silver", "bronze")
        },
    }


@router.get("/competitions/{id}/host/submissions")
def host_submissions(
    id: int,
    response: Response,
    q: str = Query("", max_length=80),
    final: Optional[bool] = None,
    team_id: Optional[int] = None,
    user_id: Optional[int] = None,
    pagination: Page = Depends(page),
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    require_host(db, id, user)
    query = (
        select(
            Submission,
            User.username,
            SubmissionTeam.team_id,
            CompetitionTeam.name,
            SubmissionPrediction.submission_id,
        )
        .join(User, User.id == Submission.user_id)
        .outerjoin(SubmissionTeam, SubmissionTeam.submission_id == Submission.id)
        .outerjoin(CompetitionTeam, CompetitionTeam.id == SubmissionTeam.team_id)
        .outerjoin(
            SubmissionPrediction, SubmissionPrediction.submission_id == Submission.id
        )
        .where(Submission.competition_id == id)
    )
    if q.strip():
        query = query.where(
            or_(
                User.username.icontains(q.strip(), autoescape=True),
                CompetitionTeam.name.icontains(q.strip(), autoescape=True),
            )
        )
    if final is not None:
        query = query.where(Submission.final_selected == int(final))
    if team_id is not None:
        query = query.where(SubmissionTeam.team_id == team_id)
    if user_id is not None:
        query = query.where(Submission.user_id == user_id)
    set_total(response, count(db, query))
    teams, users = disqualified(db, id)
    return [
        {
            **submission_json(submission, True, team, username),
            "team_name": team_name,
            "has_predictions": stored is not None,
            "disqualified": (
                team in teams if team is not None else submission.user_id in users
            ),
        }
        for submission, username, team, team_name, stored in db.execute(
            window(query.order_by(Submission.id.desc()), pagination)
        )
    ]


@router.get("/competitions/{id}/host/leaderboard.csv")
def export_leaderboard(
    id: int,
    board: Literal["public", "private"] = "public",
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    competition = require_host(db, id, user)
    finalize_if_due(db, competition)
    output = io.StringIO()
    writer = csv.writer(output)
    columns = ["rank", "participant", "team_id", "score", "entries"]
    if board == "private":
        columns += ["public_rank", "medal"]
    writer.writerow(columns)
    for row in board_rows(db, competition, board):
        writer.writerow(
            [
                # Leading formula characters are neutralized for spreadsheet safety.
                (
                    "'" + str(value)
                    if isinstance(value, str) and value[:1] in "=+-@"
                    else value
                )
                for value in (
                    row.get(column if column != "participant" else "username", "")
                    for column in columns
                )
            ]
        )
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="competition-{id}-{board}-leaderboard.csv"'
        },
    )


def disqualification_json(db, row):
    team = db.get(CompetitionTeam, row.team_id) if row.team_id else None
    target = db.get(User, row.user_id) if row.user_id else None
    actor = db.get(User, row.actor_id) if row.actor_id else None
    return {
        "id": row.id,
        "team_id": row.team_id,
        "user_id": row.user_id,
        "name": (
            f"{team.name} (Team #{team.id})"
            if team
            else target.username if target else "Deleted"
        ),
        "reason": row.reason,
        "actor": actor.username if actor else None,
        "created_at": row.created_at,
    }


@router.get("/competitions/{id}/host/disqualifications")
def disqualifications(
    id: int, user=Depends(current_user), db: Session = Depends(get_db)
):
    require_host(db, id, user)
    return [
        disqualification_json(db, row)
        for row in db.scalars(
            select(CompetitionDisqualification)
            .where(CompetitionDisqualification.competition_id == id)
            .order_by(CompetitionDisqualification.id.desc())
        )
    ]


class DisqualifyInput(BaseModel):
    user_id: Optional[int] = None
    team_id: Optional[int] = None
    reason: str = Field(min_length=3, max_length=1000)


@router.post("/competitions/{id}/host/disqualifications", status_code=201)
def disqualify(
    id: int,
    data: DisqualifyInput,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    competition = require_host(db, id, user, lock=True)
    if (data.user_id is None) == (data.team_id is None):
        raise HTTPException(422, "Choose either a user or a team")
    if not data.reason.strip() or len(data.reason.strip()) < 3:
        raise HTTPException(422, "Give a reason of at least three characters")
    if data.team_id is not None:
        team = db.get(CompetitionTeam, data.team_id)
        if not team or team.competition_id != id:
            raise HTTPException(404, "Team not found in this competition")
        name = team.name
        existing = CompetitionDisqualification.team_id == data.team_id
    else:
        target = db.get(User, data.user_id)
        if not target or not db.scalar(
            select(Entry.id).where(
                Entry.competition_id == id, Entry.user_id == target.id
            )
        ):
            raise HTTPException(404, "Participant not found in this competition")
        name = target.username
        existing = CompetitionDisqualification.user_id == data.user_id
    if db.scalar(
        select(CompetitionDisqualification.id).where(
            CompetitionDisqualification.competition_id == id, existing
        )
    ):
        raise HTTPException(409, "Already disqualified")
    row = CompetitionDisqualification(
        competition_id=id,
        team_id=data.team_id,
        user_id=data.user_id,
        reason=data.reason.strip(),
        actor_id=user.id,
    )
    db.add(row)
    record(
        db,
        user,
        "competition.disqualify",
        "competition",
        id,
        {
            "team_id": data.team_id,
            "user_id": data.user_id,
            "name": name,
            "reason": row.reason,
        },
    )
    db.flush()
    refresh_results(db, competition, user)
    db.commit()
    return disqualification_json(db, row)


@router.delete("/competitions/{id}/host/disqualifications/{row_id}", status_code=204)
def reinstate(
    id: int, row_id: int, user=Depends(current_user), db: Session = Depends(get_db)
):
    competition = require_host(db, id, user, lock=True)
    row = db.get(CompetitionDisqualification, row_id)
    if not row or row.competition_id != id:
        raise HTTPException(404, "Disqualification not found")
    record(
        db,
        user,
        "competition.reinstate",
        "competition",
        id,
        {**disqualification_json(db, row), "id": None},
    )
    db.delete(row)
    db.flush()
    refresh_results(db, competition, user)
    db.commit()
    return Response(status_code=204)


class FinalInput(BaseModel):
    selected: bool


@router.put("/competitions/{id}/submissions/{submission_id}/final")
def select_final(
    id: int,
    submission_id: int,
    data: FinalInput,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    """Choose submissions for final private scoring; shared by the whole team."""
    competition = db.scalar(
        select(Competition).where(Competition.id == id).with_for_update()
    )
    if not competition:
        raise HTTPException(404, "Competition not found")
    submission = db.get(Submission, submission_id)
    if not submission or submission.competition_id != id:
        raise HTTPException(404, "Submission not found")
    owner_team = db.scalar(
        select(SubmissionTeam.team_id).where(
            SubmissionTeam.submission_id == submission.id
        )
    )
    if (
        owner_team != team_for(db, id, user.id)
        if owner_team is not None
        else submission.user_id != user.id
    ):
        raise HTTPException(404, "Submission not found")
    if timeline(db, competition).ended():
        raise HTTPException(
            409, "Final submissions are locked after the competition ends"
        )
    if data.selected and not submission.final_selected:
        selected = db.scalar(
            select(func.count())
            .select_from(Submission)
            .where(
                Submission.competition_id == id,
                Submission.final_selected == 1,
                owner_filter(owner_team, submission.user_id),
            )
        )
        if selected >= competition.max_final_submissions:
            raise HTTPException(
                409,
                f"Select at most {competition.max_final_submissions} final submissions; "
                "clear one first",
            )
    submission.final_selected = int(data.selected)
    db.commit()
    return submission_json(submission, False, owner_team)
