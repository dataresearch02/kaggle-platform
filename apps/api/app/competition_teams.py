"""Competition-scoped teams with one team per participant."""

import secrets
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from .auth import current_user
from .db import get_db
from .models import Competition, CompetitionTeam, CompetitionTeamMember, Entry, User

router = APIRouter(prefix="/api/competitions", tags=["Competition teams"])


def membership(db, id, user):
    return db.scalar(
        select(CompetitionTeamMember).where(
            CompetitionTeamMember.competition_id == id,
            CompetitionTeamMember.user_id == user.id,
        )
    )


def can_change(db, id, user):
    competition = db.scalar(
        select(Competition).where(Competition.id == id).with_for_update()
    )
    if not competition:
        raise HTTPException(404, "Competition not found")
    if datetime.fromisoformat(competition.deadline) < datetime.now(timezone.utc):
        raise HTTPException(409, "Team changes are closed for this competition")
    if not db.scalar(
        select(Entry.id).where(Entry.competition_id == id, Entry.user_id == user.id)
    ):
        raise HTTPException(403, "Join the competition before managing a team")

    from .models import Submission, SubmissionTeam, NotebookCommit

    member = membership(db, id, user)
    submitted = db.scalar(
        select(Submission.id).where(
            Submission.competition_id == id, Submission.user_id == user.id
        )
    )
    team_submitted = member and db.scalar(
        select(SubmissionTeam.submission_id).where(
            SubmissionTeam.team_id == member.team_id
        )
    )
    active = db.scalar(
        select(NotebookCommit.id).where(
            NotebookCommit.competition_id == id,
            NotebookCommit.owner_id == user.id,
            NotebookCommit.status.in_(["queued", "running"]),
        )
    )
    if submitted or team_submitted or active:
        raise HTTPException(
            409,
            "Team membership is locked after submission or while a commit is running",
        )


def team_view(db, team):
    members = db.execute(
        select(CompetitionTeamMember, User.username)
        .join(User, User.id == CompetitionTeamMember.user_id)
        .where(CompetitionTeamMember.team_id == team.id)
        .order_by(CompetitionTeamMember.id)
    ).all()
    return {
        "id": team.id,
        "name": team.name,
        "owner_id": team.owner_id,
        "invite_code": team.invite_code,
        "members": [
            {"id": row.user_id, "username": username, "joined_at": row.created_at}
            for row, username in members
        ],
    }


@router.get("/{id}/team")
def my_team(id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    if not db.get(Competition, id):
        raise HTTPException(404, "Competition not found")
    member = membership(db, id, user)
    return team_view(db, db.get(CompetitionTeam, member.team_id)) if member else None


class TeamInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class JoinInput(BaseModel):
    invite_code: str = Field(min_length=1, max_length=40)


@router.post("/{id}/team", status_code=201)
def create_team(
    id: int, data: TeamInput, user=Depends(current_user), db: Session = Depends(get_db)
):
    can_change(db, id, user)
    if membership(db, id, user):
        raise HTTPException(409, "You already belong to a team in this competition")
    if not data.name.strip():
        raise HTTPException(422, "Enter a team name")
    team = CompetitionTeam(
        competition_id=id,
        owner_id=user.id,
        name=data.name.strip(),
        invite_code=secrets.token_urlsafe(18),
    )
    db.add(team)
    db.flush()
    db.add(CompetitionTeamMember(competition_id=id, team_id=team.id, user_id=user.id))
    db.commit()
    return team_view(db, team)


@router.post("/{id}/team/join")
def join_team(
    id: int, data: JoinInput, user=Depends(current_user), db: Session = Depends(get_db)
):
    can_change(db, id, user)
    if membership(db, id, user):
        raise HTTPException(409, "Leave your current team before joining another")
    team = db.scalar(
        select(CompetitionTeam).where(
            CompetitionTeam.competition_id == id,
            CompetitionTeam.invite_code == data.invite_code.strip(),
        )
    )
    if not team:
        raise HTTPException(404, "Invite code was not found for this competition")
    db.add(CompetitionTeamMember(competition_id=id, team_id=team.id, user_id=user.id))
    db.commit()
    return team_view(db, team)


@router.delete("/{id}/team", status_code=204)
def leave_team(id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    can_change(db, id, user)
    member = membership(db, id, user)
    if not member:
        return
    team = db.get(CompetitionTeam, member.team_id)
    db.delete(member)
    db.flush()
    remaining = db.scalar(
        select(CompetitionTeamMember)
        .where(CompetitionTeamMember.team_id == team.id)
        .order_by(CompetitionTeamMember.id)
    )
    if not remaining:
        db.delete(team)
    elif team.owner_id == user.id:
        team.owner_id = remaining.user_id
    db.commit()
