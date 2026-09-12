"""Team publishing attribution, independent of later membership changes."""

import json
from sqlalchemy import select
from .models import NotebookPublisher, CompetitionTeam, CompetitionTeamMember, User


def record_publisher(db, notebook, competition_id):
    team = db.scalar(
        select(CompetitionTeam)
        .join(
            CompetitionTeamMember, CompetitionTeamMember.team_id == CompetitionTeam.id
        )
        .where(
            CompetitionTeamMember.competition_id == competition_id,
            CompetitionTeamMember.user_id == notebook.owner_id,
        )
    )
    if not team:
        return
    members = list(
        db.scalars(
            select(User.username)
            .join(CompetitionTeamMember, CompetitionTeamMember.user_id == User.id)
            .where(CompetitionTeamMember.team_id == team.id)
            .order_by(User.id)
        )
    )
    db.merge(
        NotebookPublisher(
            notebook_id=notebook.id,
            identity=json.dumps(
                {
                    "kind": "team",
                    "name": team.name,
                    "team_id": team.id,
                    "members": members,
                }
            ),
        )
    )


def publishers_for(db, ids):
    return {
        row.notebook_id: json.loads(row.identity)
        for row in db.scalars(
            select(NotebookPublisher).where(NotebookPublisher.notebook_id.in_(ids))
        )
    }
