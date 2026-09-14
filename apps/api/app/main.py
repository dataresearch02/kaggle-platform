import asyncio
import contextlib
import csv
import hashlib
import io
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy import delete, func, select, text, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from .auth import (
    COOKIE,
    SUSPENDED,
    current_user,
    hash_password,
    new_session,
    verify_password,
)
from .moderation import record
from .pagination import Page, count, page, set_total, window
from .permissions import can_manage, is_admin, not_hidden
from .site_settings import can_create_competitions, setting
from .db import Base, DATA_DIR, SessionLocal, engine, get_db
from .models import (
    ChallengeDetails,
    Competition,
    CompetitionResource,
    CompetitionPost,
    Dataset,
    Entry,
    ModelCard,
    Notebook,
    NotebookDraft,
    WorkFileDeletion,
    Session,
    Submission,
    SubmissionTeam,
    User,
    now,
)
from .schemas import (
    Credentials,
    ModelInput,
    NotebookInput,
    WorkUpdate,
)
from .competition_teams import router as team_router
from .models import CompetitionTeam, CompetitionTeamMember
from .notebook_commits import router as commit_router, commit_worker, migrate_forks
from .notebook_visibility import visible_notebooks, require_visible
from .code_pages import optional_user
from .models import NotebookWorkingCopy, NotebookCommit
from .code_pages import router as code_router
from .engagement import router as engagement_router, remove_engagement
from .models import (
    NotebookPublication,
    NotebookBookmark,
    NotebookShare,
    NotebookComment,
)
from .metadata_routes import router as metadata_router
from .competition_metadata import (
    backfill_metadata,
    initialize_competition,
    ensure_profile,
    require_data_access,
)
from .models import CompetitionOverview, CompetitionDataFile, DatasetProfile
from sqlalchemy import update
from .competition_pages import router as competition_pages_router
from .work_cleanup import cleanup_work_files, remove_work_file
from .notebook_drafts import user_lock
from .notebook_editor import router as editor_router
from .notebook_drafts import router as draft_router, cleanup_drafts
from .challenges import validate_challenge
from .scoring import (
    DEFAULT_K,
    assign_usage,
    evaluate,
    get_metric,
    storable,
    validate_split,
)
from .seed import seed
from .notebook_runtime import router as notebook_router, notebook_document


@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    from .migrations import run_migrations

    run_migrations(engine)
    from .storage_indexes import ensure_storage_indexes

    ensure_storage_indexes(engine)
    with SessionLocal() as db:
        seed(db)
        from .admin import bootstrap_admins

        bootstrap_admins(db)
        backfill_metadata(db)
        from .progression import ensure_progression

        ensure_progression(db)
        if os.getenv("ARENA_IMPORT_PRACTICE", "true").lower() not in ("0", "false"):
            from .practice_competitions import import_practice_competitions

            try:
                import_practice_competitions(db)
            except Exception:
                db.rollback()
                logging.getLogger(__name__).exception(
                    "Practice competition import failed; it is retried at next start"
                )
        migrate_forks(db, recover=os.getenv("EVALUATION_BACKEND") != "isolated")
    commits = (
        asyncio.create_task(commit_worker())
        if os.getenv("EVALUATION_BACKEND") != "isolated"
        else None
    )
    cleanup = asyncio.create_task(cleanup_drafts())
    work_cleanup = asyncio.create_task(cleanup_work_files())
    from .notebook_runtime import reconcile_gpu_sessions

    gpu_sessions = asyncio.create_task(reconcile_gpu_sessions())
    try:
        yield
    finally:
        gpu_sessions.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await gpu_sessions
        if commits:
            commits.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await commits
        work_cleanup.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await work_cleanup
        cleanup.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await cleanup


app = FastAPI(
    title="Arena API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)
app.include_router(notebook_router)
app.include_router(draft_router)
app.include_router(editor_router)
app.include_router(competition_pages_router)
from .discussion_feed import router as discussion_feed_router

app.include_router(discussion_feed_router)
app.include_router(metadata_router)
app.include_router(code_router)
app.include_router(commit_router)
from .notebook_versions import router as version_router

from .dataset_access import (
    router as access_router,
    readable as readable_dataset,
    visible_datasets,
)
from .models import DatasetAccess, DatasetShare

app.include_router(access_router)
app.include_router(version_router)
app.include_router(team_router)
from .competition_host import router as host_router
from .competition_results import router as results_router

app.include_router(host_router)
app.include_router(results_router)
app.include_router(engagement_router)
from .accounts import router as account_router
from .auth import has_usable_password
from .oidc import end_session_url, router as oidc_router

app.include_router(account_router)
app.include_router(oidc_router)
from .moderation import router as moderation_router
from .admin import router as admin_router
from .site_settings import router as site_router

app.include_router(moderation_router)
app.include_router(admin_router)
app.include_router(site_router)
from .artifacts import router as artifacts_router, delete_artifacts

app.include_router(artifacts_router)
from .forums import router as forums_router
from .votes import router as votes_router
from .notifications import router as notifications_router
from .follows import router as follows_router
from .search import router as search_router
from .progression import router as progression_router

from .learn import router as learn_router
from .notebook_runs import router as runs_router
from .compute import router as compute_router

for community_router in (
    learn_router,
    runs_router,
    compute_router,
    forums_router,
    votes_router,
    notifications_router,
    follows_router,
    search_router,
    progression_router,
):
    app.include_router(community_router)


@app.middleware("http")
async def same_origin_mutations(request: Request, call_next):
    # Browser clients use same-origin proxies. JSON/form mutations require a custom
    # header (not available to cross-origin HTML forms) and reject foreign origins.
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        allowed = set(
            os.getenv(
                "ALLOWED_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080,http://127.0.0.1:8080",
            ).split(",")
        )
        origin = request.headers.get("origin")
        bearer = request.headers.get("authorization", "").lower().startswith("bearer ")
        if (request.headers.get("x-arena-client") != "web" and not bearer) or (
            origin and origin not in allowed
        ):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "Invalid request origin or missing X-Arena-Client header"
                },
            )
    response = await call_next(request)
    if request.url.path.startswith("/api/account/"):
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


def require(db, cls, id):
    obj = db.get(cls, id)
    if obj is None:
        raise HTTPException(404, "Not found")
    return obj


def public(obj, db=None):
    hidden = {"password_hash", "solution", "solution_usage", "storage_key"}
    result = {
        c.name: getattr(obj, c.name)
        for c in obj.__table__.columns
        if c.name not in hidden
    }
    if db and hasattr(obj, "owner_id"):
        owner = db.get(User, obj.owner_id)
        result["owner"] = owner.username if owner else "Deleted user"
    if db and isinstance(obj, Notebook):
        from .notebook_visibility import published_code

        result["code"] = published_code(db, obj)
    if db and isinstance(obj, Competition):
        from .models import CompetitionSource
        from .competition_policy import has_private_split, metric_info

        result["evaluation_available"] = bool(json.loads(obj.solution))
        result.update(metric_info(obj), leaderboard_split=has_private_split(obj))
        if obj.deadline.startswith("9999-"):
            result["deadline"] = None  # Practice competitions have no deadline.
        source = db.get(CompetitionSource, obj.id)
        if source:
            result.update(
                source_url=source.source_url,
                rules_url=source.rules_url,
                rules_content=source.rules_content,
            )
            if source.ongoing:
                result["deadline"] = None
        details = db.get(ChallengeDetails, obj.id)
        if details:
            owner = db.get(User, details.owner_id)
            result.update(
                owner_id=details.owner_id,
                owner=owner.username if owner else "Deleted user",
                kind=details.kind,
            )
            if details.kind == "benchmark":
                result["deadline"] = None
        if result["deadline"] is None:  # Without a deadline there is no timeline.
            result.update(entry_deadline=None, merger_deadline=None)
    return result


def listing(db, cls, q, pagination=None, response=None, where=None):
    query = select(cls)
    if q:
        query = query.where(cls.title.ilike(f"%{q[:100]}%"))
    if where is not None:
        query = query.where(where)
    if response is not None:
        set_total(response, count(db, query))
    query = query.order_by(cls.id.desc())
    query = window(query, pagination) if pagination else query.limit(100)
    return [public(row, db) for row in db.scalars(query)]


async def read_upload(file, limit=10 * 1024 * 1024):
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"File exceeds {limit // 1024 // 1024} MB limit")
    if not data:
        raise HTTPException(422, "File is empty")
    return data


@app.get("/api/health")
def health(db: DBSession = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/api/stats")
def stats(db: DBSession = Depends(get_db)):
    result = {
        name: db.scalar(select(func.count()).select_from(cls))
        for name, cls in [
            ("datasets", Dataset),
            ("competitions", Competition),
            ("notebooks", Notebook),
        ]
    }
    # Internal curator accounts (the seed user and sample importers) are not people.
    result["learners"] = db.scalar(
        select(func.count())
        .select_from(User)
        .where(
            User.username != "arena",
            User.username.not_like("examples\\_%", escape="\\"),
        )
    )

    result["benchmarks"] = db.scalar(
        select(func.count())
        .select_from(ChallengeDetails)
        .where(ChallengeDetails.kind == "benchmark")
    )
    result["competitions"] -= result["benchmarks"]
    return result


@app.post("/api/auth/register", status_code=201)
def register(data: Credentials, response: Response, db: DBSession = Depends(get_db)):
    if not setting(db, "registration_open"):
        raise HTTPException(403, "Registration is closed on this site")
    user = User(
        username=data.username.lower(), password_hash=hash_password(data.password)
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Username already exists")
    new_session(db, user, response)
    from .models import ServiceNotice

    db.add(
        ServiceNotice(
            user_id=user.id,
            title="Welcome to Arena",
            body="Your account is ready. Complete your profile, explore community work, and manage your API tokens from the account menu.",
        )
    )
    db.commit()
    return account_json(db, user)


@app.post("/api/auth/login")
def login(data: Credentials, response: Response, db: DBSession = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == data.username.lower()))
    # A dummy hash also performs password work for unknown users.
    stored = user.password_hash if user else "0" * 32 + ":" + "0" * 128
    if not verify_password(data.password, stored) or not user:
        raise HTTPException(401, "Incorrect username or password")
    if user.status == "suspended":
        raise HTTPException(403, SUSPENDED)
    # Administrators keep local sign-in as a break-glass path.
    if not setting(db, "local_login_enabled") and not is_admin(user):
        raise HTTPException(403, "Local sign-in is disabled on this site")
    new_session(db, user, response)
    return account_json(db, user)


def account_json(db, user):
    return {
        **public(user),
        "can_create_competitions": can_create_competitions(db, user),
        # False for accounts created by Keycloak sign-in.
        "has_password": has_usable_password(user.password_hash),
    }


@app.get("/api/auth/me")
def me(user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    return account_json(db, user)


@app.post(
    "/api/auth/logout",
    status_code=204,
    responses={200: {"description": "Signed out; also visit `end_session_url`"}},
)
def logout(request: Request, response: Response, db: DBSession = Depends(get_db)):
    token = request.cookies.get(COOKIE)
    session = (
        db.get(Session, hashlib.sha256(token.encode()).hexdigest()) if token else None
    )
    single_sign_out = None
    if session:
        if session.auth_method == "oidc":
            # No ID token is kept, so the URL carries client_id instead of a hint.
            single_sign_out = end_session_url(request)
        db.delete(session)
        db.commit()
    if single_sign_out:
        result = JSONResponse({"end_session_url": single_sign_out})
        result.delete_cookie(COOKIE, path="/")
        return result
    response.delete_cookie(COOKIE, path="/")


@app.get("/api/datasets")
def datasets(
    response: Response,
    q: str = "",
    before: int = 2147483647,
    sort: Literal["newest", "votes"] = "newest",
    pagination: Page = Depends(page),
    user=Depends(optional_user),
    db: DBSession = Depends(get_db),
):
    query = select(Dataset).where(
        visible_datasets(user),
        Dataset.id < before,
        or_(
            Dataset.title.icontains(q[:100], autoescape=True),
            Dataset.filename.icontains(q[:100], autoescape=True),
        ),
    )
    set_total(response, count(db, query))
    return with_votes(db, "dataset", Dataset, query, sort, pagination, user)


def with_votes(db, kind, model, query, sort, pagination, user):
    """A catalog page in newest or most-voted order, with vote counts and state."""
    from .votes import vote_count, vote_states

    order = (
        [vote_count(kind, model.id).desc(), model.id.desc()]
        if sort == "votes"
        else [model.id.desc()]
    )
    rows = list(db.scalars(window(query.order_by(*order), pagination)))
    states = vote_states(db, kind, [row.id for row in rows], user)
    return [{**public(row, db), **states[row.id]} for row in rows]


@app.post("/api/datasets", status_code=201)
async def upload_dataset(
    title: str = Form(min_length=3, max_length=160),
    description: str = Form(min_length=3, max_length=5000),
    tags: str = Form(default="", max_length=300),
    license: str = Form(default="CC0-1.0", max_length=80),
    file: UploadFile = File(),
    user: User = Depends(current_user),
    db: DBSession = Depends(get_db),
):
    content = await read_upload(file)
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(422, "This milestone supports CSV datasets")
    try:
        reader = csv.reader(io.StringIO(content.decode("utf-8-sig")))
        header = next(reader)
        if (
            not header
            or len(set(header)) != len(header)
            or any(not col.strip() for col in header)
        ):
            raise ValueError()
        rows = 0
        for row in reader:
            if len(row) != len(header):
                raise ValueError()
            rows += 1
        if rows == 0:
            raise ValueError()
    except (UnicodeError, StopIteration, ValueError, csv.Error):
        raise HTTPException(
            422, "CSV needs unique, nonempty headers and consistently sized data rows"
        )
    key = secrets.token_hex(16) + ".csv"
    folder = DATA_DIR / "uploads"
    folder.mkdir(exist_ok=True)
    path = folder / key
    path.write_bytes(content)
    obj = Dataset(
        owner_id=user.id,
        title=title,
        description=description,
        tags=tags,
        license=license,
        filename=os.path.basename(file.filename),
        storage_key=key,
        size=len(content),
    )
    db.add(obj)
    try:
        db.flush()
        ensure_profile(db, obj)
        db.add(DatasetAccess(dataset_id=obj.id, visibility="private"))
        db.commit()
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    return public(obj, db)


@app.get("/api/datasets/{id}")
def dataset_detail(
    id: int, user=Depends(optional_user), db: DBSession = Depends(get_db)
):
    from .votes import summary

    obj = readable_dataset(db, id, user)
    with (DATA_DIR / "uploads" / obj.storage_key).open(
        encoding="utf-8-sig", newline=""
    ) as file:
        reader = csv.DictReader(file)
        preview = []
        for row in reader:
            preview.append(row)
            if len(preview) == 10:
                break
    return {**public(obj, db), "preview": preview, **summary(db, "dataset", id, user)}


@app.get("/api/datasets/{id}/download")
def download_dataset(
    id: int, user=Depends(optional_user), db: DBSession = Depends(get_db)
):
    obj = readable_dataset(db, id, user)
    return FileResponse(
        DATA_DIR / "uploads" / obj.storage_key,
        filename=obj.filename,
        media_type="text/csv",
    )


def challenge_query(kind):
    query = select(Competition).outerjoin(ChallengeDetails)
    if kind == "benchmark":
        return query.where(ChallengeDetails.kind == "benchmark")
    return query.where(
        (ChallengeDetails.kind == "competition") | (ChallengeDetails.kind.is_(None))
    )


@app.get("/api/competitions")
def competitions(
    response: Response,
    q: str = "",
    status: Literal["all", "open", "closed"] = "all",
    category: str = "",
    sort: Literal["newest", "closing", "title"] = "newest",
    pagination: Page = Depends(page),
    db: DBSession = Depends(get_db),
):
    return challenge_listing(
        db, q, "competition", status, category, sort, pagination, response
    )


@app.get("/api/competitions/filters")
def competition_filters(db: DBSession = Depends(get_db)):
    categories = db.scalars(
        challenge_query("competition")
        .with_only_columns(Competition.category)
        .distinct()
    )
    return {"categories": sorted(category for category in categories if category)}


def challenge_listing(
    db,
    q,
    kind,
    status="all",
    category="",
    sort="newest",
    pagination=None,
    response=None,
):
    query = challenge_query(kind)
    if q.strip():
        term = f"%{q.strip()[:100]}%"
        query = query.where(
            Competition.title.ilike(term) | Competition.description.ilike(term)
        )
    if category:
        query = query.where(Competition.category == category)
    rows = list(db.scalars(query.order_by(Competition.id.desc())))
    now = datetime.now(timezone.utc)

    def deadline(row):
        value = datetime.fromisoformat(row.deadline.replace("Z", "+00:00"))
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

    if status != "all":
        rows = [row for row in rows if (deadline(row) > now) == (status == "open")]
    if sort == "closing":
        rows.sort(key=lambda row: (deadline(row) <= now, deadline(row), -row.id))
    elif sort == "title":
        rows.sort(key=lambda row: (row.title.casefold(), -row.id))
    if response is not None:
        set_total(response, len(rows))
    rows = pagination.slice(rows) if pagination else rows[:100]
    return [public(row, db) for row in rows]


@app.get("/api/benchmarks")
def benchmarks(
    response: Response,
    q: str = "",
    pagination: Page = Depends(page),
    db: DBSession = Depends(get_db),
):
    return challenge_listing(
        db, q, "benchmark", pagination=pagination, response=response
    )


@app.post("/api/competitions", status_code=201)
@app.post("/api/benchmarks", status_code=201)
async def create_challenge(
    request: Request,
    title: str = Form(min_length=3, max_length=160),
    description: str = Form(min_length=3, max_length=5000),
    category: str = Form(default="Regression", min_length=1, max_length=80),
    prize: str = Form(default="Knowledge", max_length=80),
    metric: str = Form(default="RMSE", max_length=30),
    metric_k: Optional[int] = Form(default=None, ge=1, le=100),
    # Share of answer rows on the public leaderboard when there is no Usage column.
    public_fraction: Optional[float] = Form(default=None, gt=0, lt=1),
    rules: str = Form(default="", max_length=50000),
    max_daily_submissions: Optional[int] = Form(default=None, ge=1, le=100),
    max_final_submissions: int = Form(default=2, ge=1, le=10),
    deadline: str = Form(default=""),
    test_file: UploadFile = File(),
    solution_file: UploadFile = File(),
    user: User = Depends(current_user),
    db: DBSession = Depends(get_db),
):
    kind = "benchmark" if request.url.path.endswith("benchmarks") else "competition"
    if not can_create_competitions(db, user):
        raise HTTPException(
            403,
            "Only hosts and administrators can create competitions and benchmarks here",
        )
    try:
        chosen = get_metric(metric)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    closes = datetime(9999, 1, 1, tzinfo=timezone.utc)
    if kind == "competition":
        try:
            closes = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
            if closes.tzinfo is None or closes <= datetime.now(timezone.utc):
                raise ValueError()
        except ValueError:
            raise HTTPException(422, "Choose a future deadline including its timezone")
    test_content = await read_upload(test_file)
    answer_content = await read_upload(solution_file, 1024 * 1024)
    k = (metric_k or DEFAULT_K) if chosen.uses_k else None
    try:
        test_text, solution, usage = validate_challenge(
            test_content, answer_content, chosen
        )
        if usage is None and public_fraction is not None:
            usage = assign_usage(solution, public_fraction)
        validate_split(solution, usage, chosen, k)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    obj = Competition(
        title=title,
        description=description,
        category=category,
        prize=prize,
        metric=chosen.name,
        metric_k=k,
        deadline=closes.astimezone(timezone.utc).isoformat(),
        solution=json.dumps(storable(solution)),
        solution_usage=json.dumps(usage or {}),
        rules=rules,
        max_daily_submissions=max_daily_submissions
        or (5 if kind == "competition" else 20),
        max_final_submissions=max_final_submissions,
    )
    db.add(obj)
    db.flush()
    db.add(
        ChallengeDetails(
            competition_id=obj.id, owner_id=user.id, kind=kind, test_csv=test_text
        )
    )
    db.flush()
    initialize_competition(db, obj)
    record(db, user, "competition.create", kind, obj.id, {"title": obj.title})
    db.commit()
    return public(obj, db)


@app.get("/api/benchmarks/{id}")
@app.get("/api/competitions/{id}")
def competition(id: int, db: DBSession = Depends(get_db)):
    obj = require(db, Competition, id)
    from .team_scoring import leaderboard
    from .competition_policy import timeline
    from .competition_results import finalize_if_due

    finalize_if_due(db, obj)

    template = db.scalar(
        select(CompetitionDataFile)
        .where(
            CompetitionDataFile.competition_id == id,
            CompetitionDataFile.role == "submission",
        )
        .order_by(CompetitionDataFile.id)
        .limit(1)
    )
    return {
        **public(obj, db),
        "participants": db.scalar(
            select(func.count()).select_from(Entry).where(Entry.competition_id == id)
        ),
        "leaderboard": leaderboard(db, obj),
        "timeline": timeline(db, obj).json(),
        "submission_columns": (
            [column["name"] for column in json.loads(template.columns_json)]
            if template
            else ["id", "prediction"]
        ),
    }


@app.get("/api/benchmarks/{id}/leaderboard")
@app.get("/api/competitions/{id}/leaderboard")
def competition_leaderboard(
    id: int,
    response: Response,
    board: Literal["public", "private"] = "public",
    pagination: Page = Depends(page),
    user=Depends(optional_user),
    db: DBSession = Depends(get_db),
):
    """Public scores while running; final private standings after the end."""
    from .team_scoring import leaderboard, leaderboard_size

    obj = require(db, Competition, id)
    if board == "public":
        set_total(response, leaderboard_size(db, obj))
        return with_tiers(
            db, leaderboard(db, obj, pagination.offset, pagination.limit), user
        )
    from .competition_policy import reveal_private
    from .competition_results import board_rows, finalize_if_due

    finalize_if_due(db, obj)
    if not reveal_private(db, obj, user):
        raise HTTPException(
            403, "The private leaderboard is published when the competition ends"
        )
    rows = board_rows(db, obj, "private")
    set_total(response, len(rows))
    return with_tiers(db, pagination.slice(rows), user)


def with_tiers(db, rows, viewer):
    """Add the overall tier of solo participants (team rows show a team name)."""
    from .progression import tier_name, tiers_for

    names = [row["username"] for row in rows if row.get("team_id") is None]
    ids = dict(
        db.execute(select(User.username, User.id).where(User.username.in_(names))).all()
    )
    tiers = tiers_for(db, ids.values(), viewer)
    return [
        {
            **row,
            "tier": (
                tier_name(tiers, ids.get(row["username"]))
                if row.get("team_id") is None
                else None
            ),
        }
        for row in rows
    ]


class JoinInput(BaseModel):
    accept_rules: bool = False
    # The revision the participant read; a newer one must be reviewed first.
    rules_revision: Optional[int] = None


@app.post("/api/benchmarks/{id}/join")
@app.post("/api/competitions/{id}/join")
def join(
    id: int,
    data: Optional[JoinInput] = None,
    user: User = Depends(current_user),
    db: DBSession = Depends(get_db),
):
    """Join, or accept updated rules as an existing member."""
    from .competition_policy import entry_for, timeline

    obj = db.scalar(select(Competition).where(Competition.id == id).with_for_update())
    if not obj:
        raise HTTPException(404, "Not found")
    if datetime.fromisoformat(obj.deadline) < datetime.now(timezone.utc):
        raise HTTPException(409, "Competition has closed")
    if not data or not data.accept_rules:
        raise HTTPException(422, "Accept the competition rules to join")
    if data.rules_revision is not None and data.rules_revision != obj.rules_revision:
        raise HTTPException(
            409, "The rules were updated while you were reading them; review them again"
        )
    entry = entry_for(db, id, user)
    if not entry:
        if not timeline(db, obj).entry_open():
            raise HTTPException(409, "The entry deadline has passed")
        entry = Entry(user_id=user.id, competition_id=id)
        db.add(entry)
    if entry.rules_revision != obj.rules_revision:
        entry.rules_revision, entry.rules_accepted_at = obj.rules_revision, now()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    return {"joined": True}


@app.get("/api/benchmarks/{id}/sample")
@app.get("/api/competitions/{id}/sample")
def sample(
    id: int, db: DBSession = Depends(get_db), user: User = Depends(current_user)
):
    obj = require(db, Competition, id)
    require_data_access(db, id, user)
    if not json.loads(obj.solution):
        from .models import CompetitionDataFile

        original = db.scalar(
            select(CompetitionDataFile).where(
                CompetitionDataFile.competition_id == id,
                CompetitionDataFile.role == "submission",
            )
        )
        if not original:
            raise HTTPException(409, "No submission template is available")
        return Response(
            original.content,
            media_type="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="sample_submission.csv"'
            },
        )
    content = "id,prediction\n" + "".join(
        f"{key},0\n" for key in json.loads(obj.solution)
    )
    return Response(
        content,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="sample_submission.csv"'},
    )


@app.get("/api/benchmarks/{id}/test")
@app.get("/api/competitions/{id}/test")
def test_features(
    id: int, db: DBSession = Depends(get_db), user: User = Depends(current_user)
):
    require(db, Competition, id)
    require_data_access(db, id, user)
    from .competition_metadata import test_csv

    content = test_csv(db, id)
    if content is None:
        raise HTTPException(404, "Test data is not available for this competition")
    return Response(
        content,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="test.csv"'},
    )


@app.post("/api/benchmarks/{id}/submissions", status_code=201)
@app.post("/api/competitions/{id}/submissions", status_code=201)
async def submit(
    id: int,
    file: UploadFile = File(),
    user: User = Depends(current_user),
    db: DBSession = Depends(get_db),
):
    from .competition_policy import (
        require_current_rules,
        require_daily_capacity,
        require_submission_window,
        solution_usage,
        store_predictions,
        submission_json,
    )

    obj = db.scalar(select(Competition).where(Competition.id == id).with_for_update())
    if not obj:
        raise HTTPException(404, "Competition not found")
    require_submission_window(db, obj)
    require_current_rules(db, obj, user)
    if not json.loads(obj.solution):
        raise HTTPException(
            409,
            "Local scoring is unavailable: official evaluation answers were not imported",
        )
    # Checked before scoring; rejected uploads do not use the allowance.
    require_daily_capacity(db, obj, user)
    content = await read_upload(file, 1024 * 1024)
    try:
        score, private_score = evaluate(
            content,
            json.loads(obj.solution),
            obj.metric,
            solution_usage(obj),
            obj.metric_k,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    submission = Submission(
        user_id=user.id,
        competition_id=id,
        filename=os.path.basename(file.filename or "submission.csv"),
        score=score,
        private_score=private_score,
    )
    db.add(submission)
    from .team_scoring import attach_team

    team_id = attach_team(db, submission)
    store_predictions(db, submission, content)
    from .progression import mark_dirty

    mark_dirty(db, user.id)
    db.commit()
    return submission_json(submission, False, team_id)


@app.get("/api/benchmarks/{id}/submissions")
@app.get("/api/competitions/{id}/submissions")
def my_submissions(
    id: int,
    response: Response,
    pagination: Page = Depends(page),
    user: User = Depends(current_user),
    db: DBSession = Depends(get_db),
):
    from .team_scoring import history_filter
    from .competition_policy import reveal_private, submission_json

    obj = require(db, Competition, id)
    query = (
        select(Submission, SubmissionTeam.team_id, User.username)
        .join(User, User.id == Submission.user_id)
        .outerjoin(SubmissionTeam, SubmissionTeam.submission_id == Submission.id)
        .where(history_filter(db, id, user), Submission.competition_id == id)
    )
    set_total(response, count(db, query))
    # Private scores stay hidden from participants until the competition ends.
    reveal = reveal_private(db, obj, user)
    return [
        submission_json(row, reveal, team_id, username)
        for row, team_id, username in db.execute(
            window(query.order_by(Submission.id.desc()), pagination)
        )
    ]


@app.get("/api/notebooks")
def notebooks(
    response: Response,
    q: str = "",
    pagination: Page = Depends(page),
    user=Depends(optional_user),
    db: DBSession = Depends(get_db),
):
    query = select(Notebook).where(
        visible_notebooks(user),
        Notebook.title.icontains(q[:100], autoescape=True),
    )
    set_total(response, count(db, query))
    return [
        public(row, db)
        for row in db.scalars(window(query.order_by(Notebook.id.desc()), pagination))
    ]


@app.post("/api/notebooks", status_code=201)
def create_notebook(
    data: NotebookInput,
    user: User = Depends(current_user),
    db: DBSession = Depends(get_db),
):
    obj = Notebook(owner_id=user.id, **data.model_dump())
    db.add(obj)
    db.flush()
    document = notebook_document(obj)
    db.add(
        NotebookWorkingCopy(
            notebook_id=obj.id, document=json.dumps(document), private=1
        )
    )
    from .notebook_versions import save_version

    save_version(db, obj, document)
    db.commit()
    return public(obj, db)


@app.put("/api/notebooks/{id}")
def save_notebook(
    id: int,
    data: NotebookInput,
    user: User = Depends(current_user),
    db: DBSession = Depends(get_db),
):
    obj = require(db, Notebook, id)
    if not can_manage(user, obj.owner_id):
        raise HTTPException(
            403, "Only the owner can edit this notebook; save your own copy"
        )
    for key, value in data.model_dump().items():
        setattr(obj, key, value)
    working = db.get(NotebookWorkingCopy, id)
    if not working:
        working = NotebookWorkingCopy(notebook_id=id, private=0)
        db.add(working)
    working.document = json.dumps(notebook_document(obj))
    db.commit()
    return public(obj, db)


@app.get("/api/notebooks/{id}/download")
def download_notebook(
    id: int, user=Depends(optional_user), db: DBSession = Depends(get_db)
):
    obj = require_visible(db, id, user)
    notebook = notebook_document(
        obj, db, working=bool(user and obj.owner_id == user.id)
    )
    return Response(
        json.dumps(notebook),
        media_type="application/x-ipynb+json",
        headers={"Content-Disposition": f'attachment; filename="notebook-{id}.ipynb"'},
    )


@app.get("/api/models")
def models(
    response: Response,
    q: str = "",
    sort: Literal["newest", "votes"] = "newest",
    pagination: Page = Depends(page),
    user=Depends(optional_user),
    db: DBSession = Depends(get_db),
):
    query = select(ModelCard).where(not_hidden(ModelCard, user))
    if q:
        query = query.where(ModelCard.title.ilike(f"%{q[:100]}%"))
    set_total(response, count(db, query))
    return with_votes(db, "model", ModelCard, query, sort, pagination, user)


@app.get("/api/models/{id}")
def model_detail(id: int, user=Depends(optional_user), db: DBSession = Depends(get_db)):
    from .artifacts import resource
    from .models import ArtifactVersion
    from .votes import summary

    return {
        **public(resource(db, "models", id, user), db),
        **summary(db, "model", id, user),
        "input_available": bool(
            db.scalar(
                select(ArtifactVersion.id)
                .where(
                    ArtifactVersion.kind == "models", ArtifactVersion.resource_id == id
                )
                .limit(1)
            )
        ),
    }


@app.post("/api/models", status_code=201)
def create_model(
    data: ModelInput,
    user: User = Depends(current_user),
    db: DBSession = Depends(get_db),
):
    obj = ModelCard(
        owner_id=user.id,
        **{**data.model_dump(), "url": str(data.url) if data.url else ""},
    )
    db.add(obj)
    db.commit()
    return public(obj, db)


from .models import BenchmarkCollection

WORK_MODELS = {
    "datasets": Dataset,
    "notebooks": Notebook,
    "models": ModelCard,
    "benchmark-collections": BenchmarkCollection,
}
# Audit and moderation names for work kinds.
AUDIT_KINDS = {
    "datasets": "dataset",
    "notebooks": "code",
    "models": "model",
    "benchmark-collections": "benchmark-collection",
    "competitions": "competition",
    "benchmarks": "benchmark",
}


@app.get("/api/work")
def your_work(user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    items = []
    for kind, model in WORK_MODELS.items():
        for row in db.scalars(select(model).where(model.owner_id == user.id)):
            items.append(
                {
                    **public(row, db),
                    "work_kind": (
                        "benchmarks" if kind == "benchmark-collections" else kind
                    ),
                    "work_resource": kind,
                }
            )
    for details in db.scalars(
        select(ChallengeDetails).where(ChallengeDetails.owner_id == user.id)
    ):
        row = db.get(Competition, details.competition_id)
        items.append(
            {
                **public(row, db),
                "work_kind": (
                    "benchmarks" if details.kind == "benchmark" else "competitions"
                ),
                "created_at": details.created_at,
            }
        )
    return sorted(
        items, key=lambda item: (item.get("created_at") or "", item["id"]), reverse=True
    )


def owned_work(kind, id, user, db):
    """Work the user may change: their own, or anything for administrators."""
    if kind in WORK_MODELS:
        row = db.get(WORK_MODELS[kind], id)
    elif kind in ("competitions", "benchmarks"):
        details = db.get(ChallengeDetails, id)
        expected = "benchmark" if kind == "benchmarks" else "competition"
        # Legacy competitions without creator details can be managed by admins.
        allowed = (
            details.kind == expected
            if details
            else kind == "competitions" and is_admin(user)
        )
        row = db.get(Competition, id) if allowed else None
    else:
        raise HTTPException(404, "Work not found")
    if row is None or not can_manage(user, work_owner(kind, row, db)):
        raise HTTPException(404, "Work not found")
    return row


def work_owner(kind, row, db):
    if kind in WORK_MODELS:
        return row.owner_id
    details = db.get(ChallengeDetails, row.id)
    return details.owner_id if details else None


@app.patch("/api/work/{kind}/{id}")
def update_work(
    kind: str,
    id: int,
    data: WorkUpdate,
    user: User = Depends(current_user),
    db: DBSession = Depends(get_db),
):
    row = owned_work(kind, id, user, db)
    if len(data.title.strip()) < 3:
        raise HTTPException(422, "Title must contain at least three characters")
    owner_id = work_owner(kind, row, db)
    if owner_id != user.id:
        record(
            db,
            user,
            "content.update",
            AUDIT_KINDS[kind],
            id,
            {"title": data.title.strip(), "owner_id": owner_id},
        )
    row.title = data.title.strip()
    row.description = data.description
    db.commit()
    return {**public(row, db), "work_kind": kind}


@app.delete("/api/work/{kind}/{id}", status_code=204)
async def delete_work(
    kind: str,
    id: int,
    user: User = Depends(current_user),
    db: DBSession = Depends(get_db),
):
    await remove_work(kind, id, user, db)
    return Response(status_code=204)


async def remove_work(kind, id, user, db, moderated=False):
    """Delete work with its dependent records; commits together with the audit entry."""
    owner_id = work_owner(kind, owned_work(kind, id, user, db), db)
    # Cleanup jobs run in the owner's workspace, even when an administrator deletes.
    cleanup_owner = owner_id if owner_id is not None else user.id
    async with user_lock(cleanup_owner):
        row = owned_work(kind, id, user, db)
        db.refresh(row, with_for_update=True)
        from .progression import mark_dirty, mark_related
        from .votes import remove_votes

        if kind in ("datasets", "notebooks", "models"):
            mark_related(db, AUDIT_KINDS[kind], id)
            remove_votes(db, AUDIT_KINDS[kind], [id])
        if kind in ("datasets", "models"):
            topics = list(
                db.scalars(
                    select(CompetitionPost.id).where(
                        CompetitionPost.scope == AUDIT_KINDS[kind],
                        CompetitionPost.scope_id == id,
                    )
                )
            )
            remove_engagement(db, "competition-post", topics)
            db.execute(delete(CompetitionPost).where(CompetitionPost.id.in_(topics)))
        if kind in ("competitions", "benchmarks"):
            record(
                db,
                user,
                "competition.delete",
                AUDIT_KINDS[kind],
                id,
                {"title": row.title, "owner_id": owner_id},
            )
        elif moderated or owner_id != user.id:
            record(
                db,
                user,
                "content.delete",
                AUDIT_KINDS[kind],
                id,
                {"title": row.title, "owner_id": owner_id},
            )
        task = None
        if kind == "benchmark-collections":
            from .models import BenchmarkRun

            jobs = list(
                db.scalars(select(BenchmarkRun).where(BenchmarkRun.collection_id == id))
            )
            if any(job.status in ("queued", "running") for job in jobs):
                raise HTTPException(409, "Cancel active benchmark runs before deleting")
            for job in jobs:
                for directory in (DATA_DIR / "evaluations").glob(
                    f"benchmark-{job.id}-*"
                ):
                    db.add(
                        WorkFileDeletion(
                            owner_id=cleanup_owner,
                            kind="benchmark-run",
                            path=directory.name,
                        )
                    )
                db.delete(job)
            db.flush()
        if kind in ("competitions", "benchmarks"):
            from .models import NotebookDraftCompetition
            import time

            linked_drafts = select(NotebookDraftCompetition.draft_id).where(
                NotebookDraftCompetition.competition_id == id
            )
            if db.scalar(
                select(NotebookDraft.id)
                .where(
                    NotebookDraft.id.in_(linked_drafts),
                    NotebookDraft.expires_at > time.time(),
                )
                .limit(1)
            ):
                raise HTTPException(
                    409,
                    "Close active competition notebook drafts before deleting this competition",
                )
            db.execute(
                delete(NotebookDraftCompetition).where(
                    NotebookDraftCompetition.competition_id == id
                )
            )
        if kind in ("datasets", "models"):
            delete_artifacts(db, kind, id, cleanup_owner)
        if kind == "datasets":
            db.execute(delete(DatasetShare).where(DatasetShare.dataset_id == id))
            db.execute(delete(DatasetAccess).where(DatasetAccess.dataset_id == id))
            db.execute(delete(DatasetProfile).where(DatasetProfile.dataset_id == id))
            db.execute(
                update(CompetitionDataFile)
                .where(CompetitionDataFile.source_dataset_id == id)
                .values(source_dataset_id=None)
            )
            task = WorkFileDeletion(
                owner_id=cleanup_owner, kind="upload", path=row.storage_key
            )
            db.add(task)
        elif kind == "notebooks":
            db.execute(
                update(NotebookWorkingCopy)
                .where(NotebookWorkingCopy.forked_from == id)
                .values(forked_from=None)
            )
            if db.scalar(
                select(NotebookCommit.id).where(
                    NotebookCommit.notebook_id == id,
                    NotebookCommit.status.in_(["queued", "running"]),
                )
            ):
                raise HTTPException(
                    409, "Wait for the notebook commit to finish before deleting"
                )
            from .models import NotebookRun, NotebookSchedule

            if db.scalar(
                select(NotebookRun.id).where(
                    NotebookRun.notebook_id == id,
                    NotebookRun.status.in_(["queued", "running"]),
                )
            ):
                raise HTTPException(
                    409, "Cancel the notebook's background run before deleting"
                )
            db.execute(
                delete(NotebookSchedule).where(NotebookSchedule.notebook_id == id)
            )
            db.execute(delete(NotebookRun).where(NotebookRun.notebook_id == id))
            from .models import (
                NotebookVersion,
                NotebookSettings,
                NotebookOutput,
                NotebookWorkspaceFolder,
            )

            db.execute(
                delete(NotebookWorkspaceFolder).where(
                    NotebookWorkspaceFolder.notebook_id == id
                )
            )
            for key in db.scalars(
                select(NotebookOutput.storage_key)
                .where(NotebookOutput.notebook_id == id)
                .distinct()
            ):
                db.add(
                    WorkFileDeletion(
                        owner_id=cleanup_owner, kind="notebook-output", path=key
                    )
                )
            db.execute(delete(NotebookOutput).where(NotebookOutput.notebook_id == id))

            db.execute(
                delete(NotebookSettings).where(NotebookSettings.notebook_id == id)
            )

            from .models import NotebookPublisher

            db.execute(
                delete(NotebookPublisher).where(NotebookPublisher.notebook_id == id)
            )
            db.execute(delete(NotebookVersion).where(NotebookVersion.notebook_id == id))
            db.execute(delete(NotebookCommit).where(NotebookCommit.notebook_id == id))
            db.execute(
                delete(NotebookWorkingCopy).where(NotebookWorkingCopy.notebook_id == id)
            )
            db.execute(
                update(NotebookPublication)
                .where(NotebookPublication.forked_from == id)
                .values(forked_from=None)
            )
            db.execute(
                delete(NotebookPublication).where(NotebookPublication.notebook_id == id)
            )
            db.execute(
                delete(NotebookBookmark).where(NotebookBookmark.notebook_id == id)
            )
            remove_engagement(
                db,
                "notebook-comment",
                select(NotebookComment.id).where(NotebookComment.notebook_id == id),
            )
            db.execute(delete(NotebookComment).where(NotebookComment.notebook_id == id))
            db.execute(delete(NotebookShare).where(NotebookShare.notebook_id == id))
            # Expire linked editors before deleting the record, so Save cannot recreate it.
            for draft in db.scalars(
                select(NotebookDraft)
                .where(NotebookDraft.notebook_id == id)
                .with_for_update()
            ):
                draft.expires_at = 0
                draft.notebook_id = None
            db.flush()
            task = WorkFileDeletion(
                owner_id=cleanup_owner,
                kind="notebook",
                path=f"arena-notebook-{id}.ipynb",
            )
            db.add(task)
        elif kind in ("competitions", "benchmarks"):
            from .models import (
                CompetitionDisqualification,
                CompetitionResult,
                SubmissionPrediction,
            )

            competition_submissions = select(Submission.id).where(
                Submission.competition_id == id
            )
            db.execute(
                delete(SubmissionPrediction).where(
                    SubmissionPrediction.submission_id.in_(competition_submissions)
                )
            )
            mark_dirty(
                db,
                *db.scalars(
                    select(CompetitionResult.user_id).where(
                        CompetitionResult.competition_id == id
                    )
                ),
                *db.scalars(
                    select(Submission.user_id).where(Submission.competition_id == id)
                ),
            )
            for model in (CompetitionDisqualification, CompetitionResult):
                db.execute(delete(model).where(model.competition_id == id))
            db.execute(
                delete(SubmissionTeam).where(
                    SubmissionTeam.submission_id.in_(
                        select(Submission.id).where(Submission.competition_id == id)
                    )
                )
            )
            db.execute(delete(Submission).where(Submission.competition_id == id))
            db.execute(
                delete(CompetitionTeamMember).where(
                    CompetitionTeamMember.competition_id == id
                )
            )
            db.execute(
                delete(CompetitionTeam).where(CompetitionTeam.competition_id == id)
            )
            db.execute(delete(Entry).where(Entry.competition_id == id))
            db.execute(
                delete(ChallengeDetails).where(ChallengeDetails.competition_id == id)
            )
        if kind in ("competitions", "benchmarks"):
            from .models import CompetitionSource, DiscussionImage

            for image in db.scalars(
                select(DiscussionImage).where(DiscussionImage.competition_id == id)
            ):
                db.add(
                    WorkFileDeletion(
                        owner_id=image.owner_id, kind="discussion-image", path=image.id
                    )
                )
                db.delete(image)
            db.flush()

            db.execute(
                delete(CompetitionSource).where(CompetitionSource.competition_id == id)
            )
            db.execute(
                delete(CompetitionOverview).where(
                    CompetitionOverview.competition_id == id
                )
            )
            db.execute(
                delete(CompetitionDataFile).where(
                    CompetitionDataFile.competition_id == id
                )
            )
            db.execute(
                delete(CompetitionResource).where(
                    CompetitionResource.competition_id == id
                )
            )
            if db.scalar(
                select(NotebookCommit.id).where(
                    NotebookCommit.competition_id == id,
                    NotebookCommit.status.in_(["queued", "running"]),
                )
            ):
                raise HTTPException(
                    409, "Wait for competition commits to finish before deleting"
                )
            db.execute(
                delete(NotebookCommit).where(NotebookCommit.competition_id == id)
            )
            db.execute(
                update(NotebookWorkingCopy)
                .where(NotebookWorkingCopy.competition_id == id)
                .values(competition_id=None)
            )
            for topic in db.scalars(
                select(CompetitionPost.id).where(CompetitionPost.competition_id == id)
            ).all():
                mark_related(db, "competition-post", topic)
            remove_engagement(
                db,
                "competition-post",
                select(CompetitionPost.id).where(CompetitionPost.competition_id == id),
            )
            db.execute(
                delete(CompetitionPost).where(CompetitionPost.competition_id == id)
            )
        elif kind in ("notebooks", "models"):
            db.execute(
                delete(CompetitionResource).where(
                    CompetitionResource.kind == kind,
                    CompetitionResource.resource_id == id,
                )
            )
        db.delete(row)
        db.commit()
        if task and kind == "datasets":
            try:
                await remove_work_file(task, db)
            except OSError:
                db.rollback()  # The durable cleanup job remains for retry.


@app.get("/api/active-events")
def active_events(user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    """Return only the signed-in user's queued and running evaluations."""
    from .models import NotebookCommit

    rows = db.execute(
        select(NotebookCommit, Notebook.title)
        .join(Notebook, Notebook.id == NotebookCommit.notebook_id)
        .where(
            NotebookCommit.owner_id == user.id,
            NotebookCommit.status.in_(["queued", "running"]),
        )
        .order_by(NotebookCommit.id.desc())
    ).all()
    events = [
        {
            "id": job.id,
            "notebook_id": job.notebook_id,
            "title": title,
            "status": job.status,
        }
        for job, title in rows
    ]

    from .models import BenchmarkRun, BenchmarkCollection

    events.extend(
        {
            "id": -job.id,
            "benchmark_id": job.collection_id,
            "title": title,
            "status": job.status,
        }
        for job, title in db.execute(
            select(BenchmarkRun, BenchmarkCollection.title)
            .join(
                BenchmarkCollection,
                BenchmarkRun.collection_id == BenchmarkCollection.id,
            )
            .where(
                BenchmarkRun.owner_id == user.id,
                BenchmarkRun.status.in_(["queued", "running"]),
            )
        )
    )
    return events


from .notebook_outputs import router as notebook_outputs_router

from . import input_sources

app.include_router(notebook_outputs_router)

from .benchmarks import router as benchmark_router

app.include_router(benchmark_router)
