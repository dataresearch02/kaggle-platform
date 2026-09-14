"""Site search across competitions, datasets, code, models, topics, courses and users.

Relevance is deliberately simple: an exact title (or username) match scores 3, a
title match 2 and a description or body match 1. Every source applies the same
visibility filters as its own listing.
"""

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import case, func, literal_column, or_, select, union_all

from .code_pages import optional_user
from .community import listed_users, target_url, visible_topics
from .dataset_access import visible_datasets
from .db import get_db
from .models import (
    Competition,
    CompetitionPost,
    Course,
    Dataset,
    ModelCard,
    Notebook,
    User,
)
from .notebook_visibility import visible_notebooks
from .pagination import Page, page, set_total
from .permissions import not_hidden

router = APIRouter(prefix="/api", tags=["Search"])

TYPES = (
    "competitions",
    "datasets",
    "notebooks",
    "models",
    "topics",
    "courses",
    "users",
)
SearchType = Literal[
    "competitions", "datasets", "notebooks", "models", "topics", "courses", "users"
]


def relevance(title, term):
    lowered = func.lower(title)
    return case(
        (lowered == term, 3),
        (lowered.contains(term, autoescape=True), 2),
        else_=1,
    )


def matching(term, *columns):
    return or_(*(column.icontains(term, autoescape=True) for column in columns))


def source(kind, model, title, term, where, *text_columns, id_column=None):
    id_column = id_column if id_column is not None else model.id
    return select(
        literal_column(f"'{kind}'").label("type"),
        id_column.label("id"),
        relevance(title, term).label("score"),
    ).where(matching(term, title, *text_columns), where)


def sources(term, user):
    return {
        "competitions": source(
            "competitions",
            Competition,
            Competition.title,
            term,
            Competition.id > 0,
            Competition.description,
        ),
        "datasets": source(
            "datasets",
            Dataset,
            Dataset.title,
            term,
            visible_datasets(user),
            Dataset.description,
            Dataset.tags,
        ),
        "notebooks": source(
            "notebooks",
            Notebook,
            Notebook.title,
            term,
            visible_notebooks(user),
            Notebook.description,
        ),
        "models": source(
            "models",
            ModelCard,
            ModelCard.title,
            term,
            not_hidden(ModelCard, user),
            ModelCard.description,
        ),
        "topics": source(
            "topics",
            CompetitionPost,
            CompetitionPost.title,
            term,
            visible_topics(user) & CompetitionPost.deleted_at.is_(None),
            CompetitionPost.body,
        ),
        "courses": source(
            "courses", Course, Course.title, term, Course.id > 0, Course.description
        ),
        "users": source("users", User, User.username, term, listed_users(user)),
    }


def snippet(value):
    value = " ".join((value or "").split())
    return value if len(value) <= 200 else value[:199] + "…"


def describe(db, kind, id):
    if kind == "users":
        row = db.get(User, id)
        return {
            "title": row.username,
            "snippet": "",
            "url": f"#profile/{row.username}",
            "owner": None,
        }
    model = {
        "competitions": Competition,
        "datasets": Dataset,
        "notebooks": Notebook,
        "models": ModelCard,
        "topics": CompetitionPost,
        "courses": Course,
    }[kind]
    row = db.get(model, id)
    owner = db.get(User, row.owner_id) if hasattr(row, "owner_id") else None
    url = {
        "competitions": f"#competitions/{id}/overview",
        "datasets": f"#datasets/{id}",
        "notebooks": f"#code/{id}",
        "models": f"#models/{id}",
        "courses": "#courses",
    }.get(kind) or target_url(db, "competition-post", row)
    return {
        "title": row.title,
        "snippet": snippet(row.body if kind == "topics" else row.description),
        "url": url,
        "owner": owner.username if owner else None,
    }


@router.get("/search")
def search(
    response: Response,
    q: str = Query("", max_length=100),
    type: Optional[SearchType] = None,
    pagination: Page = Depends(page),
    user=Depends(optional_user),
    db=Depends(get_db),
):
    term = q.strip().lower()
    if not term:
        set_total(response, 0)
        return []
    selected = sources(term, user)
    parts = [selected[type]] if type else list(selected.values())
    results = (union_all(*parts) if len(parts) > 1 else parts[0]).subquery()
    set_total(response, db.scalar(select(func.count()).select_from(results)))
    rows = db.execute(
        select(results.c.type, results.c.id, results.c.score)
        .order_by(results.c.score.desc(), results.c.id.desc(), results.c.type)
        .offset(pagination.offset)
        .limit(pagination.limit)
    ).all()
    return [
        {"type": kind, "id": id, "score": score, **describe(db, kind, id)}
        for kind, id, score in rows
    ]


@router.get("/search/counts")
def search_counts(
    q: str = Query("", max_length=100), user=Depends(optional_user), db=Depends(get_db)
):
    term = q.strip().lower()
    if not term:
        return {kind: 0 for kind in TYPES}
    return {
        kind: db.scalar(select(func.count()).select_from(query.subquery()))
        for kind, query in sources(term, user).items()
    }
