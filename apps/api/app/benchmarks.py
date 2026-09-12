"""Versioned task collections and reproducible, model-oriented evaluations."""

import ast
import csv
import hashlib
import io
import json
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, func, or_
from .auth import current_user
from .code_pages import optional_user
from .db import get_db
from .models import (
    BenchmarkAsset,
    BenchmarkAssetVersion,
    BenchmarkCollection,
    BenchmarkRun,
    User,
    now,
)

router = APIRouter(prefix="/api/benchmark-hub", tags=["Benchmarks"])


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


def visible(model, user):
    return or_(
        model.visibility == "public", model.owner_id == (user.id if user else -1)
    )


def get_visible(db, model, id, user, owner=False):
    row = db.scalar(select(model).where(model.id == id, visible(model, user)))
    if not row:
        raise HTTPException(404, "Resource not found")
    if owner and (not user or row.owner_id != user.id):
        raise HTTPException(403, "Only the owner can change this resource")
    return row


class AssetInput(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(default="", max_length=10000)
    visibility: Literal["private", "public"] = "private"
    source: str = Field(
        default="def predict(prompt):\n    return prompt\n",
        min_length=3,
        max_length=100000,
    )
    provider_id: Optional[str] = Field(default=None, max_length=128)
    cases: list[dict] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_code(self):
        if not self.title.strip():
            raise ValueError("Enter a title")
        try:
            ast.parse(self.source)
        except SyntaxError as exc:
            raise ValueError(f"Python syntax error on line {exc.lineno}: {exc.msg}")
        if len(json.dumps(self.cases, allow_nan=False)) > 500000:
            raise ValueError("Evaluation cases must be under 500 KB")
        return self


def asset_json(db, asset, version=None):
    version = version or db.scalar(
        select(BenchmarkAssetVersion)
        .where(BenchmarkAssetVersion.asset_id == asset.id)
        .order_by(BenchmarkAssetVersion.id.desc())
        .limit(1)
    )
    return {
        "id": asset.id,
        "kind": asset.kind,
        "owner_id": asset.owner_id,
        "owner": db.get(User, asset.owner_id).username,
        "title": asset.title,
        "description": asset.description,
        "visibility": asset.visibility,
        "version_id": version.id,
        "digest": version.digest,
        "provider_id": version.provider_id,
        "created_at": asset.created_at,
    }


@router.get("/assets")
def assets(
    kind: Literal["task", "model"] = "task",
    q: str = Query("", max_length=160),
    owned: bool = False,
    visibility: Literal["all", "public", "private"] = "all",
    before: int = 2147483647,
    user=Depends(optional_user),
    db=Depends(get_db),
):
    query = select(BenchmarkAsset).where(
        BenchmarkAsset.kind == kind,
        visible(BenchmarkAsset, user),
        BenchmarkAsset.id < before,
    )
    if visibility != "all":
        query = query.where(BenchmarkAsset.visibility == visibility)
    if owned:
        query = query.where(BenchmarkAsset.owner_id == (user.id if user else -1))
    if q.strip():
        query = query.where(BenchmarkAsset.title.icontains(q.strip(), autoescape=True))
    rows = list(db.scalars(query.order_by(BenchmarkAsset.id.desc()).limit(31)))
    return {
        "items": [asset_json(db, row) for row in rows[:30]],
        "next_cursor": rows[29].id if len(rows) > 30 else None,
    }


@router.get("/assets/{id}")
def asset_detail(id: int, user=Depends(optional_user), db=Depends(get_db)):
    row = get_visible(db, BenchmarkAsset, id, user)
    versions = list(
        db.scalars(
            select(BenchmarkAssetVersion)
            .where(BenchmarkAssetVersion.asset_id == id)
            .order_by(BenchmarkAssetVersion.id.desc())
        )
    )
    return {
        **asset_json(db, row, versions[0]),
        "versions": [
            {
                "id": v.id,
                "source": v.source,
                "cases": json.loads(v.cases),
                "digest": v.digest,
                "created_at": v.created_at,
            }
            for v in versions
        ],
    }


@router.get("/providers")
def provider_list():
    from .benchmark_providers import catalog

    return catalog()


def save_asset(db, row, data):
    from .benchmark_providers import signature

    if data.provider_id:
        from .benchmark_providers import configured

        if row.kind != "model" or data.provider_id not in configured():
            raise HTTPException(422, "Select a configured model provider")
    entry = "evaluate" if row.kind == "task" else "predict"
    if not any(
        isinstance(node, ast.FunctionDef) and node.name == entry
        for node in ast.parse(data.source).body
    ):
        raise HTTPException(422, f"Define a top-level {entry} function")
    if row.kind == "task" and not data.cases:
        raise HTTPException(422, "Add at least one evaluation case")
    # Dependencies may already be public: access cannot be silently withdrawn.
    if row.visibility == "public" and data.visibility != "public":
        raise HTTPException(
            409, "Published tasks and models stay public; create a private copy instead"
        )
    row.title, row.description, row.visibility = (
        data.title.strip(),
        data.description,
        data.visibility,
    )
    db.add(row)
    db.flush()
    version = BenchmarkAssetVersion(
        asset_id=row.id,
        source=data.source,
        provider_id=data.provider_id,
        cases=json.dumps(data.cases),
        digest=digest(
            [data.source, data.cases, data.provider_id, signature(data.provider_id)]
        ),
    )
    db.add(version)
    db.commit()
    return asset_json(db, row, version)


@router.post("/assets/{kind}", status_code=201)
def create_asset(
    kind: Literal["task", "model"],
    data: AssetInput,
    user=Depends(current_user),
    db=Depends(get_db),
):
    return save_asset(
        db,
        BenchmarkAsset(
            kind=kind, owner_id=user.id, title=data.title, visibility="private"
        ),
        data,
    )


@router.put("/assets/{id}")
def update_asset(
    id: int, data: AssetInput, user=Depends(current_user), db=Depends(get_db)
):
    return save_asset(db, get_visible(db, BenchmarkAsset, id, user, True), data)


class CollectionInput(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(default="", max_length=10000)
    visibility: Literal["private", "public"] = "private"
    tasks: list[int] = Field(default_factory=list, max_length=20)
    models: list[int] = Field(default_factory=list, max_length=10)


def validate_versions(db, ids, kind, user, public=False):
    if len(ids) != len(set(ids)):
        raise HTTPException(422, "Select each version only once")
    rows = []
    seen = set()
    for id in ids:
        version = db.get(BenchmarkAssetVersion, id)
        if not version:
            raise HTTPException(404, "Version not found")
        asset = get_visible(db, BenchmarkAsset, version.asset_id, user)
        if asset.kind != kind or asset.id in seen:
            raise HTTPException(422, "Choose one version of each task or model")
        if public and asset.visibility != "public":
            raise HTTPException(
                422, "Public benchmarks require public tasks and models"
            )
        seen.add(asset.id)
        rows.append(
            {
                **asset_json(db, asset, version),
                "source": version.source,
                "cases": json.loads(version.cases),
            }
        )
    return rows


def collection_json(row):
    config = json.loads(row.configuration)
    return {
        "id": row.id,
        "owner_id": row.owner_id,
        "title": row.title,
        "description": row.description,
        "visibility": row.visibility,
        "created_at": row.created_at,
        **config,
        "fingerprint": digest(config),
    }


def save_collection(db, row, data, user):
    for kind, ids in [("task", data.tasks), ("model", data.models)]:
        validate_versions(db, ids, kind, user, data.visibility == "public")
    row.title, row.description, row.visibility = (
        data.title.strip(),
        data.description,
        data.visibility,
    )
    row.configuration = json.dumps({"tasks": data.tasks, "models": data.models})
    db.add(row)
    db.commit()
    return collection_json(row)


@router.get("/collections")
def collections(
    q: str = Query("", max_length=160),
    owned: bool = False,
    visibility: Literal["all", "public", "private"] = "all",
    before: int = 2147483647,
    user=Depends(optional_user),
    db=Depends(get_db),
):
    query = select(BenchmarkCollection).where(
        visible(BenchmarkCollection, user), BenchmarkCollection.id < before
    )
    if visibility != "all":
        query = query.where(BenchmarkCollection.visibility == visibility)
    if owned:
        query = query.where(BenchmarkCollection.owner_id == (user.id if user else -1))
    if q.strip():
        query = query.where(
            BenchmarkCollection.title.icontains(q.strip(), autoescape=True)
        )
    rows = list(db.scalars(query.order_by(BenchmarkCollection.id.desc()).limit(31)))
    page = rows[:30]
    owners = dict(
        db.execute(
            select(User.id, User.username).where(
                User.id.in_([r.owner_id for r in page])
            )
        ).all()
    )
    fingerprints = {r.id: digest(json.loads(r.configuration)) for r in page}
    run_ids = list(
        db.scalars(
            select(func.max(BenchmarkRun.id))
            .where(
                BenchmarkRun.collection_id.in_(fingerprints),
                BenchmarkRun.status == "succeeded",
                BenchmarkRun.fingerprint.in_(fingerprints.values()),
            )
            .group_by(BenchmarkRun.collection_id, BenchmarkRun.fingerprint)
        )
    )
    latest = {}
    for run in db.scalars(select(BenchmarkRun).where(BenchmarkRun.id.in_(run_ids))):
        if run.fingerprint == fingerprints[run.collection_id]:
            latest[run.collection_id] = run
    return {
        "items": [
            {
                **collection_json(r),
                "owner": owners[r.owner_id],
                "top_models": [
                    {"model": m["model"], "score": m["score"]}
                    for m in rank_run(latest.get(r.id))
                    if m["score"] is not None
                ][:3],
            }
            for r in page
        ],
        "next_cursor": rows[29].id if len(rows) > 30 else None,
    }


@router.post("/collections", status_code=201)
def create_collection(
    data: CollectionInput, user=Depends(current_user), db=Depends(get_db)
):
    return save_collection(db, BenchmarkCollection(owner_id=user.id), data, user)


@router.put("/collections/{id}")
def update_collection(
    id: int, data: CollectionInput, user=Depends(current_user), db=Depends(get_db)
):
    row = get_visible(db, BenchmarkCollection, id, user, True)
    db.refresh(row, with_for_update=True)
    return save_collection(db, row, data, user)


@router.get("/collections/{id}")
def collection_detail(id: int, user=Depends(optional_user), db=Depends(get_db)):
    row = get_visible(db, BenchmarkCollection, id, user)
    config = json.loads(row.configuration)
    return {
        **collection_json(row),
        "task_details": validate_versions(db, config["tasks"], "task", user),
        "model_details": validate_versions(db, config["models"], "model", user),
    }


@router.post("/collections/{id}/runs", status_code=202)
def start_run(id: int, user=Depends(current_user), db=Depends(get_db)):
    row = get_visible(db, BenchmarkCollection, id, user, True)
    db.refresh(row, with_for_update=True)
    if db.scalar(
        select(BenchmarkRun.id).where(
            BenchmarkRun.collection_id == id,
            BenchmarkRun.status.in_(["queued", "running"]),
        )
    ):
        raise HTTPException(409, "An evaluation is already queued or running")
    config = json.loads(row.configuration)
    if not config["tasks"] or not config["models"]:
        raise HTTPException(422, "Add tasks and models before running an evaluation")
    # Serialize the per-user queue quota across different collections.
    db.refresh(user, with_for_update=True)
    if (
        db.scalar(
            select(func.count())
            .select_from(BenchmarkRun)
            .where(
                BenchmarkRun.owner_id == user.id,
                BenchmarkRun.status.in_(["queued", "running"]),
            )
        )
        >= 3
    ):
        raise HTTPException(429, "At most three active benchmark evaluations per user")
    snapshot = {
        "tasks": validate_versions(db, config["tasks"], "task", user),
        "models": validate_versions(db, config["models"], "model", user),
    }
    from .benchmark_providers import configured, signature

    providers = configured()
    for model in snapshot["models"]:
        if model.get("provider_id"):
            provider = providers.get(model["provider_id"])
            if not provider:
                raise HTTPException(409, "A selected provider is no longer configured")
            if model["digest"] != digest(
                [
                    model["source"],
                    model["cases"],
                    model["provider_id"],
                    signature(model["provider_id"]),
                ]
            ):
                raise HTTPException(
                    409, "Provider configuration changed; save a new model version"
                )
            model["provider_model"] = provider["model"]
            model["provider_revision"] = signature(model["provider_id"])
    if sum(len(t["cases"]) for t in snapshot["tasks"]) * len(snapshot["models"]) > 1000:
        raise HTTPException(422, "Limit each run to 1,000 model/case evaluations")
    job = BenchmarkRun(
        collection_id=id,
        owner_id=user.id,
        snapshot=json.dumps(snapshot),
        fingerprint=digest(config),
    )
    db.add(job)
    db.commit()
    return run_json(job)


def run_json(row, full=False):
    result = {
        "id": row.id,
        "collection_id": row.collection_id,
        "status": row.status,
        "fingerprint": row.fingerprint,
        "created_at": row.created_at,
        "finished_at": row.finished_at,
        "error": row.error,
    }
    if full:
        result.update(
            results=json.loads(row.results),
            logs=row.logs,
            snapshot=json.loads(row.snapshot),
        )
    return result


@router.get("/collections/{id}/runs")
def runs(
    id: int, before: int = 2147483647, user=Depends(optional_user), db=Depends(get_db)
):
    get_visible(db, BenchmarkCollection, id, user)
    rows = list(
        db.scalars(
            select(BenchmarkRun)
            .where(BenchmarkRun.collection_id == id, BenchmarkRun.id < before)
            .order_by(BenchmarkRun.id.desc())
            .limit(31)
        )
    )
    return {
        "items": [run_json(r) for r in rows[:30]],
        "next_cursor": rows[29].id if len(rows) > 30 else None,
    }


@router.get("/runs/{id}")
def run_detail(id: int, user=Depends(optional_user), db=Depends(get_db)):
    row = db.get(BenchmarkRun, id)
    if not row:
        raise HTTPException(404, "Run not found")
    get_visible(db, BenchmarkCollection, row.collection_id, user)
    # Private historical dependencies must never leak after making a collection public.
    snapshot = json.loads(row.snapshot)
    for kind in ("tasks", "models"):
        validate_versions(
            db, [v["version_id"] for v in snapshot[kind]], kind[:-1], user
        )
    return run_json(row, True)


@router.post("/runs/{id}/cancel")
def cancel_run(id: int, user=Depends(current_user), db=Depends(get_db)):
    row = db.scalar(select(BenchmarkRun).where(BenchmarkRun.id == id).with_for_update())
    if not row:
        raise HTTPException(404, "Run not found")
    get_visible(db, BenchmarkCollection, row.collection_id, user, True)
    if row.status in ("queued", "running"):
        row.status, row.finished_at = "cancelled", now()
        db.commit()
    return run_json(row)


@router.get("/collections/{id}/leaderboard")
def leaderboard(
    id: int,
    format: Literal["json", "csv"] = "json",
    user=Depends(optional_user),
    db=Depends(get_db),
):
    collection = get_visible(db, BenchmarkCollection, id, user)
    config = json.loads(collection.configuration)
    fingerprint = digest(config)
    latest = db.scalar(
        select(BenchmarkRun)
        .where(
            BenchmarkRun.collection_id == id,
            BenchmarkRun.fingerprint == fingerprint,
            BenchmarkRun.status == "succeeded",
        )
        .order_by(BenchmarkRun.id.desc())
        .limit(1)
    )
    board = rank_run(latest)
    if format == "csv":
        stream = io.StringIO()
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "rank",
                "model",
                "model_version_id",
                "score",
                "completed_tasks",
                "total_tasks",
                "run_id",
            ],
        )
        writer.writeheader()
        writer.writerows({k: row[k] for k in writer.fieldnames} for row in board)
        return Response(
            stream.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="benchmark-{id}-leaderboard.csv"'
            },
        )
    return {
        "fingerprint": fingerprint,
        "items": board,
        "aggregation": "Equal-weight mean of task scores (0–1); all tasks required",
    }


def rank_run(latest):
    board = []
    if latest:
        snapshot = json.loads(latest.snapshot)
        results = json.loads(latest.results)
        for model in snapshot["models"]:
            cells = [r for r in results if r["model_version_id"] == model["version_id"]]
            complete = len(cells) == len(snapshot["tasks"]) and all(
                r["status"] == "succeeded" for r in cells
            )
            board.append(
                {
                    "model": model["title"],
                    "model_version_id": model["version_id"],
                    "score": (
                        sum(r["score"] for r in cells) / len(cells)
                        if complete and cells
                        else None
                    ),
                    "completed_tasks": sum(r["status"] == "succeeded" for r in cells),
                    "total_tasks": len(snapshot["tasks"]),
                    "run_id": latest.id,
                    "tasks": cells,
                }
            )
        board.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0), r["model"]))
        for i, row in enumerate(board):
            row["rank"] = i + 1 if row["score"] is not None else None
    return board
