"""Offset pagination that keeps JSON array responses; totals use X-Total-Count."""

from dataclasses import dataclass

from fastapi import Query
from sqlalchemy import func, select

MAX_LIMIT = 100
TOTAL_HEADER = "X-Total-Count"


@dataclass
class Page:
    offset: int
    limit: int

    def slice(self, rows):
        return rows[self.offset : self.offset + self.limit]


def page(
    offset: int = Query(0, ge=0, le=10_000_000),
    limit: int = Query(MAX_LIMIT, ge=1, description=f"Capped at {MAX_LIMIT}"),
):
    return Page(offset, min(limit, MAX_LIMIT))


def count(db, query):
    return db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))


def window(query, pagination):
    return query.offset(pagination.offset).limit(pagination.limit)


def set_total(response, total):
    response.headers[TOTAL_HEADER] = str(total)
