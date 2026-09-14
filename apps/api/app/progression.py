"""Medals, tiers and rankings in four categories (see docs/community.md).

`user_progression` is a cache: `compute` derives every number from source rows
(competition results, votes and publication state), so recalculating from
scratch always gives the correct result. Request handlers call `mark_dirty` for
affected users; the cache rows are refreshed just before the transaction commits.
"""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from .code_pages import optional_user
from .community import listed_users, public_topics, restricted_profiles, target_row
from .dataset_access import visible_datasets
from .db import get_db
from .models import (
    CompetitionPost,
    CompetitionResult,
    ContentReply,
    Dataset,
    ModelCard,
    Notebook,
    NotebookComment,
    Submission,
    User,
    UserProgression,
    Vote,
    now,
)
from .notebook_visibility import visible_notebooks
from .pagination import Page, page, set_total
from .permissions import require_admin

router = APIRouter(prefix="/api", tags=["Progression"])

CATEGORIES = ("competitions", "datasets", "notebooks", "discussions")
TIERS = ("Novice", "Contributor", "Expert", "Master", "Grandmaster")
# Upvotes from other users needed per item: (gold, silver, bronze).
VOTE_THRESHOLDS = {
    "notebooks": (50, 20, 5),
    "datasets": (50, 20, 5),
    "discussions": (10, 5, 1),
}


def tier_for(category, gold, silver, bronze, solo_gold=0, contributor=False):
    """Highest tier whose requirements hold. A medal fills a requirement for its
    own or any lower medal, so "1 gold + 2 silver" means gold >= 1 and
    gold + silver >= 3."""
    silver_plus = gold + silver
    total = silver_plus + bronze
    levels = {
        "competitions": (
            gold >= 5 and solo_gold >= 1,
            gold >= 1 and silver_plus >= 3,
            total >= 2,
        ),
        "datasets": (
            gold >= 5 and silver_plus >= 10,
            gold >= 1 and silver_plus >= 5,
            total >= 3,
        ),
        "notebooks": (gold >= 15, silver_plus >= 10, total >= 5),
        "discussions": (
            gold >= 50 and total >= 500,
            silver_plus >= 50 and total >= 200,
            total >= 50,
        ),
    }[category]
    for tier, met in zip((4, 3, 2), levels):
        if met:
            return tier
    return 1 if contributor or total else 0


def vote_medals(db, category, kind, ids):
    """[(medal, achieved_at)] for items of one kind: the medal and when the
    vote that reached its threshold was cast."""
    ids = list(ids)
    if not ids:
        return []
    times = {}
    for target_id, created_at in db.execute(
        select(Vote.target_id, Vote.created_at)
        .where(Vote.target_kind == kind, Vote.target_id.in_(ids))
        .order_by(Vote.created_at, Vote.id)
    ):
        times.setdefault(target_id, []).append(created_at or "")
    medals = []
    for values in times.values():
        for threshold, medal in zip(
            VOTE_THRESHOLDS[category], ("gold", "silver", "bronze")
        ):
            if len(values) >= threshold:
                medals.append((medal, values[threshold - 1]))
                break
    return medals


def public_discussion_items(db, user_id):
    """Public, non-deleted topics, comments/replies and notebook comments by a user."""
    topics = list(
        db.scalars(
            select(CompetitionPost.id).where(
                CompetitionPost.owner_id == user_id, public_topics()
            )
        )
    )
    replies = [
        id
        for id in db.scalars(
            select(ContentReply.id).where(
                ContentReply.owner_id == user_id,
                ContentReply.hidden == 0,
                ContentReply.deleted_at.is_(None),
            )
        )
        if target_row(db, "reply", id, None) is not None
    ]
    comments = [
        id
        for id in db.scalars(
            select(NotebookComment.id).where(
                NotebookComment.owner_id == user_id,
                NotebookComment.hidden == 0,
                NotebookComment.deleted_at.is_(None),
            )
        )
        if target_row(db, "notebook-comment", id, None) is not None
    ]
    return {"competition-post": topics, "reply": replies, "notebook-comment": comments}


def stats(category, medals, solo_gold=0, contributor=False):
    counts = {
        medal: sum(1 for name, _ in medals if name == medal)
        for medal in ("gold", "silver", "bronze")
    }
    return {
        **counts,
        "tier": tier_for(
            category,
            counts["gold"],
            counts["silver"],
            counts["bronze"],
            solo_gold,
            contributor,
        ),
        "achieved_at": max((time for _, time in medals), default=None),
    }


def compute(db, user_id):
    """Medal counts and tier per category, derived from source rows only."""
    results = db.execute(
        select(
            CompetitionResult.medal,
            CompetitionResult.team_id,
            CompetitionResult.created_at,
        ).where(
            CompetitionResult.user_id == user_id, CompetitionResult.medal.is_not(None)
        )
    ).all()
    submitted = db.scalar(
        select(Submission.id).where(Submission.user_id == user_id).limit(1)
    )
    notebooks = list(
        db.scalars(
            select(Notebook.id).where(
                Notebook.owner_id == user_id, visible_notebooks(None)
            )
        )
    )
    datasets = list(
        db.scalars(
            select(Dataset.id).where(
                Dataset.owner_id == user_id, visible_datasets(None)
            )
        )
    )
    discussions = public_discussion_items(db, user_id)
    discussion_medals = [
        medal
        for kind, ids in discussions.items()
        for medal in vote_medals(db, "discussions", kind, ids)
    ]
    return {
        "competitions": stats(
            "competitions",
            [(medal, created_at or "") for medal, _, created_at in results],
            solo_gold=sum(
                1 for medal, team, _ in results if medal == "gold" and team is None
            ),
            contributor=submitted is not None,
        ),
        "notebooks": stats(
            "notebooks",
            vote_medals(db, "notebooks", "code", notebooks),
            contributor=bool(notebooks),
        ),
        "datasets": stats(
            "datasets",
            vote_medals(db, "datasets", "dataset", datasets),
            contributor=bool(datasets),
        ),
        "discussions": stats(
            "discussions", discussion_medals, contributor=any(discussions.values())
        ),
    }


def refresh(db, user_ids):
    for user_id in sorted({id for id in user_ids if id is not None}):
        if not db.get(User, user_id):
            continue
        for category, values in compute(db, user_id).items():
            row = db.get(UserProgression, (user_id, category))
            if not row:
                row = UserProgression(user_id=user_id, category=category)
                db.add(row)
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = now()


def recalculate_all(db):
    """Rebuild the cache for every user. Callers commit."""
    db.query(UserProgression).delete()
    users = list(db.scalars(select(User.id).order_by(User.id)))
    refresh(db, users)
    return len(users)


def ensure_progression(db):
    """Fill an empty cache once after upgrading (existing results and votes count)."""
    if db.scalar(select(UserProgression.user_id).limit(1)) is None and db.scalar(
        select(User.id).limit(1)
    ):
        recalculate_all(db)
        db.commit()


def mark_dirty(db, *user_ids):
    db.info.setdefault("progression_dirty", set()).update(
        id for id in user_ids if id is not None
    )


def discussion_owners(db, kind, ids):
    """Owners of topics/comments/replies attached to the given items."""
    ids = list(ids)
    owners = set()
    if not ids:
        return owners
    if kind in ("dataset", "model"):
        topics = list(
            db.scalars(
                select(CompetitionPost.id).where(
                    CompetitionPost.scope == kind, CompetitionPost.scope_id.in_(ids)
                )
            )
        )
        owners |= set(
            db.scalars(
                select(CompetitionPost.owner_id).where(CompetitionPost.id.in_(topics))
            )
        )
        return owners | discussion_owners(db, "competition-post", topics)
    if kind == "code":
        comments = list(
            db.scalars(
                select(NotebookComment.id).where(NotebookComment.notebook_id.in_(ids))
            )
        )
        owners |= set(
            db.scalars(
                select(NotebookComment.owner_id).where(NotebookComment.id.in_(comments))
            )
        )
        return owners | discussion_owners(db, "notebook-comment", comments)
    child_kind = {
        "competition-post": "competition-post",
        "reply": "competition-comment",
        "notebook-comment": "notebook-comment",
    }.get(kind)
    if not child_kind:
        return owners
    children = db.execute(
        select(ContentReply.id, ContentReply.owner_id).where(
            ContentReply.target_kind == child_kind, ContentReply.target_id.in_(ids)
        )
    ).all()
    owners |= {owner for _, owner in children}
    if kind == "competition-post":
        owners |= discussion_owners(db, "reply", [id for id, _ in children])
    return owners


def mark_related(db, kind, id):
    """Mark the owner of an item and of discussion content that depends on its visibility."""
    model = {
        "code": Notebook,
        "dataset": Dataset,
        "model": ModelCard,
        "competition-post": CompetitionPost,
        "reply": ContentReply,
        "notebook-comment": NotebookComment,
    }.get(kind)
    row = db.get(model, id) if model else None
    if kind == "profile":
        mark_dirty(db, id)
    if row is not None:
        mark_dirty(db, row.owner_id, *discussion_owners(db, kind, [id]))


@event.listens_for(Session, "before_commit")
def _refresh_dirty(session):
    dirty = session.info.pop("progression_dirty", None)
    if dirty:
        refresh(session, dirty)


def tier_json(tier):
    return {"tier": tier, "tier_name": TIERS[tier]}


def tiers_for(db, user_ids, viewer=None):
    """{user_id: overall tier} for badges; restricted profiles get no badge."""
    ids = {id for id in user_ids if id is not None}
    if not ids:
        return {}
    from .models import UserProfile

    hidden = set(
        db.scalars(
            select(UserProfile.user_id).where(
                UserProfile.user_id.in_(ids),
                UserProfile.user_id.in_(restricted_profiles(viewer)),
            )
        )
    ) - ({viewer.id} if viewer else set())
    tiers = {id: 0 for id in ids - hidden}
    for user_id, tier in db.execute(
        select(UserProgression.user_id, func.max(UserProgression.tier))
        .where(UserProgression.user_id.in_(ids - hidden))
        .group_by(UserProgression.user_id)
    ):
        tiers[user_id] = tier or 0
    return tiers


def tier_name(tiers, user_id):
    tier = tiers.get(user_id)
    return TIERS[tier] if tier is not None else None


def progression_json(db, user_id):
    rows = {
        row.category: row
        for row in db.scalars(
            select(UserProgression).where(UserProgression.user_id == user_id)
        )
    }
    categories = []
    for category in CATEGORIES:
        row = rows.get(category)
        categories.append(
            {
                "category": category,
                **tier_json(row.tier if row else 0),
                "gold": row.gold if row else 0,
                "silver": row.silver if row else 0,
                "bronze": row.bronze if row else 0,
            }
        )
    return {
        **tier_json(max((item["tier"] for item in categories), default=0)),
        "categories": categories,
    }


@router.get("/profiles/{username}/progression")
def profile_progression(username: str, user=Depends(optional_user), db=Depends(get_db)):
    from .accounts import visible_profile

    return progression_json(db, visible_profile(db, username, user).id)


@router.get("/rankings/{category}")
def rankings(
    category: str,
    response: Response,
    pagination: Page = Depends(page),
    user=Depends(optional_user),
    db=Depends(get_db),
):
    """Users with medals, by gold, then silver, then bronze, then earliest achievement."""
    if category not in CATEGORIES:
        raise HTTPException(404, "Unknown ranking category")
    query = (
        select(UserProgression, User.username)
        .join(User, User.id == UserProgression.user_id)
        .where(
            UserProgression.category == category,
            UserProgression.gold + UserProgression.silver + UserProgression.bronze > 0,
            listed_users(user),
        )
    )
    set_total(response, db.scalar(select(func.count()).select_from(query.subquery())))
    rows = db.execute(
        query.order_by(
            UserProgression.gold.desc(),
            UserProgression.silver.desc(),
            UserProgression.bronze.desc(),
            UserProgression.achieved_at,
            User.id,
        )
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).all()
    return [
        {
            "rank": pagination.offset + index + 1,
            "username": username,
            "user_id": row.user_id,
            **tier_json(row.tier),
            "gold": row.gold,
            "silver": row.silver,
            "bronze": row.bronze,
            "achieved_at": row.achieved_at,
        }
        for index, (row, username) in enumerate(rows)
    ]


@router.post("/admin/progression/recalculate")
def recalculate(admin=Depends(require_admin), db=Depends(get_db)):
    from .moderation import record

    users = recalculate_all(db)
    record(db, admin, "progression.recalculate", "progression", "", {"users": users})
    db.commit()
    return {"users": users}
