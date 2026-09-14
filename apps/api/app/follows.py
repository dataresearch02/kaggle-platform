"""Follows, follower lists and public activity feeds.

Activity is derived from the source tables, never stored, so hiding content or
making it private removes it from every feed immediately.
"""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, literal_column, select, union_all

from .accounts import visible_profile
from .auth import current_user
from .code_pages import optional_user
from .community import listed_users, public_topics, restricted_profiles, target_url
from .dataset_access import visible_datasets
from .db import get_db
from .models import (
    Competition,
    CompetitionPost,
    CompetitionResult,
    Dataset,
    Follow,
    ModelCard,
    Notebook,
    NotebookPublication,
    User,
    now,
)
from .notebook_visibility import visible_notebooks
from .pagination import Page, page, set_total

router = APIRouter(prefix="/api", tags=["Follows and activity"])


def people_count(db, column, other, target, viewer):
    return db.scalar(
        select(func.count())
        .select_from(Follow)
        .join(User, User.id == other)
        .where(column == target.id, listed_users(viewer))
    )


def follow_summary(db, target, viewer):
    return {
        "followers": people_count(
            db, Follow.followee_id, Follow.follower_id, target, viewer
        ),
        "following": people_count(
            db, Follow.follower_id, Follow.followee_id, target, viewer
        ),
        "is_following": bool(viewer and db.get(Follow, (viewer.id, target.id))),
        "can_follow": bool(viewer and viewer.id != target.id),
    }


@router.get("/profiles/{username}/follows")
def follows(username: str, user=Depends(optional_user), db=Depends(get_db)):
    return follow_summary(db, visible_profile(db, username, user), user)


@router.put("/profiles/{username}/follow")
def follow(username: str, user=Depends(current_user), db=Depends(get_db)):
    target = visible_profile(db, username, user)
    if target.id == user.id:
        raise HTTPException(422, "You cannot follow yourself")
    db.refresh(user, with_for_update=True)
    if not db.get(Follow, (user.id, target.id)):
        db.add(Follow(follower_id=user.id, followee_id=target.id, created_at=now()))
        from .notifications import notify

        notify(
            db,
            target.id,
            "follow",
            actor=user,
            target_kind="profile",
            target_id=user.id,
        )
        db.commit()
    return follow_summary(db, target, user)


@router.delete("/profiles/{username}/follow")
def unfollow(username: str, user=Depends(current_user), db=Depends(get_db)):
    # Unfollowing works even after the profile became private.
    target = db.scalar(select(User).where(User.username == username.lower()))
    row = db.get(Follow, (user.id, target.id)) if target else None
    if not row:
        raise HTTPException(404, "You do not follow this user")
    db.delete(row)
    db.commit()
    return follow_summary(db, target, user) if target.id else {}


def people(db, response, pagination, column, other, target, viewer):
    from .progression import tier_name, tiers_for

    query = (
        select(User, Follow.created_at)
        .join(Follow, User.id == other)
        .where(column == target.id, listed_users(viewer))
    )
    set_total(response, db.scalar(select(func.count()).select_from(query.subquery())))
    rows = db.execute(
        query.order_by(Follow.created_at.desc(), User.id)
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).all()
    tiers = tiers_for(db, [row.id for row, _ in rows], viewer)
    return [
        {
            "id": row.id,
            "username": row.username,
            "tier_name": tier_name(tiers, row.id),
            "followed_at": created_at,
        }
        for row, created_at in rows
    ]


@router.get("/profiles/{username}/followers")
def followers(
    username: str,
    response: Response,
    pagination: Page = Depends(page),
    user=Depends(optional_user),
    db=Depends(get_db),
):
    target = visible_profile(db, username, user)
    return people(
        db, response, pagination, Follow.followee_id, Follow.follower_id, target, user
    )


@router.get("/profiles/{username}/following")
def following(
    username: str,
    response: Response,
    pagination: Page = Depends(page),
    user=Depends(optional_user),
    db=Depends(get_db),
):
    target = visible_profile(db, username, user)
    return people(
        db, response, pagination, Follow.follower_id, Follow.followee_id, target, user
    )


def label(value):
    return literal_column(f"'{value}'").label("kind")


def activity_events(actors):
    """Public events by the given actor ids (a list or a select of user ids)."""
    return union_all(
        select(
            label("notebook"),
            Notebook.id.label("id"),
            Notebook.owner_id.label("actor_id"),
            NotebookPublication.updated_at.label("created_at"),
        )
        .join(NotebookPublication, NotebookPublication.notebook_id == Notebook.id)
        .where(visible_notebooks(None), Notebook.owner_id.in_(actors)),
        select(
            label("dataset"), Dataset.id, Dataset.owner_id, Dataset.created_at
        ).where(visible_datasets(None), Dataset.owner_id.in_(actors)),
        select(
            label("model"), ModelCard.id, ModelCard.owner_id, ModelCard.created_at
        ).where(ModelCard.hidden == 0, ModelCard.owner_id.in_(actors)),
        select(
            label("topic"),
            CompetitionPost.id,
            CompetitionPost.owner_id,
            CompetitionPost.created_at,
        ).where(public_topics(), CompetitionPost.owner_id.in_(actors)),
        select(
            label("medal"),
            CompetitionResult.id,
            CompetitionResult.user_id,
            CompetitionResult.created_at,
        ).where(
            CompetitionResult.medal.is_not(None), CompetitionResult.user_id.in_(actors)
        ),
    ).subquery()


def activity_page(db, response, pagination, actors):
    events = activity_events(actors)
    set_total(response, db.scalar(select(func.count()).select_from(events)))
    rows = db.execute(
        select(events.c.kind, events.c.id, events.c.actor_id, events.c.created_at)
        .order_by(events.c.created_at.desc(), events.c.id.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).all()
    items = []
    for kind, id, actor_id, created_at in rows:
        actor = db.get(User, actor_id)
        item = {
            "kind": kind,
            "id": id,
            "actor": actor.username if actor else "Deleted user",
            "created_at": created_at,
            "detail": {},
        }
        if kind == "notebook":
            row = db.get(Notebook, id)
            item.update(
                title=row.title, url=f"#code/{id}", message="published a notebook"
            )
        elif kind == "dataset":
            row = db.get(Dataset, id)
            item.update(
                title=row.title, url=f"#datasets/{id}", message="published a dataset"
            )
        elif kind == "model":
            row = db.get(ModelCard, id)
            item.update(title=row.title, url=f"#models/{id}", message="shared a model")
        elif kind == "topic":
            row = db.get(CompetitionPost, id)
            item.update(
                title=row.title,
                url=target_url(db, "competition-post", row),
                message="started a discussion",
                detail={"scope": row.scope},
            )
        else:
            result = db.get(CompetitionResult, id)
            competition = db.get(Competition, result.competition_id)
            item.update(
                title=competition.title if competition else "Competition",
                url=f"#competitions/{result.competition_id}/leaderboard",
                message=f"won a {result.medal} medal",
                detail={
                    "medal": result.medal,
                    "rank": result.rank,
                    "team_count": result.team_count,
                },
            )
        items.append(item)
    return items


@router.get("/feed")
def feed(
    response: Response,
    pagination: Page = Depends(page),
    user=Depends(current_user),
    db=Depends(get_db),
):
    """Public activity from people you follow, plus your own."""
    followed = select(Follow.followee_id).where(
        Follow.follower_id == user.id,
        Follow.followee_id.not_in(restricted_profiles(None)),
    )
    actors = select(User.id).where((User.id == user.id) | User.id.in_(followed))
    return activity_page(db, response, pagination, actors)


@router.get("/profiles/{username}/activity")
def profile_activity(
    username: str,
    response: Response,
    pagination: Page = Depends(page),
    user=Depends(optional_user),
    db=Depends(get_db),
):
    target = visible_profile(db, username, user)
    return activity_page(db, response, pagination, [target.id])
