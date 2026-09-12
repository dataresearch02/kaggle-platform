import asyncio
import contextlib
import csv
import hashlib
import io
import json
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal

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
from sqlalchemy import delete, func, select, text, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from .auth import COOKIE, current_user, hash_password, new_session, verify_password
from .db import Base, DATA_DIR, SessionLocal, engine, get_db
from .models import (
    ChallengeDetails,
    Comment,
    Competition,
    CompetitionResource,
    CompetitionPost,
    Course,
    Dataset,
    Discussion,
    Entry,
    ModelCard,
    Notebook,
    NotebookDraft,
    WorkFileDeletion,
    Progress,
    Session,
    Submission,
    User,
)
from .schemas import (
    CommentInput,
    Credentials,
    DiscussionInput,
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
from .scoring import score_csv
from .seed import seed
from .notebook_runtime import router as notebook_router, notebook_document


@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    from .storage_indexes import ensure_storage_indexes

    ensure_storage_indexes(engine)
    with SessionLocal() as db:
        seed(db)
        backfill_metadata(db)
        migrate_forks(db, recover=os.getenv("EVALUATION_BACKEND") != "isolated")
    commits = (
        asyncio.create_task(commit_worker())
        if os.getenv("EVALUATION_BACKEND") != "isolated"
        else None
    )
    cleanup = asyncio.create_task(cleanup_drafts())
    work_cleanup = asyncio.create_task(cleanup_work_files())
    try:
        yield
    finally:
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
app.include_router(engagement_router)
from .accounts import router as account_router

app.include_router(account_router)
from .artifacts import router as artifacts_router, delete_artifacts

app.include_router(artifacts_router)


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
    hidden = {"password_hash", "solution", "storage_key"}
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

        result["evaluation_available"] = bool(json.loads(obj.solution))
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
    return result


def listing(db, cls, q):
    query = select(cls)
    if q:
        query = query.where(cls.title.ilike(f"%{q[:100]}%"))
    return [
        public(row, db) for row in db.scalars(query.order_by(cls.id.desc()).limit(100))
    ]


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
            ("learners", User),
        ]
    }

    result["benchmarks"] = db.scalar(
        select(func.count())
        .select_from(ChallengeDetails)
        .where(ChallengeDetails.kind == "benchmark")
    )
    result["competitions"] -= result["benchmarks"]
    return result


@app.post("/api/auth/register", status_code=201)
def register(data: Credentials, response: Response, db: DBSession = Depends(get_db)):
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
    return public(user)


@app.post("/api/auth/login")
def login(data: Credentials, response: Response, db: DBSession = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == data.username.lower()))
    # A dummy hash also performs password work for unknown users.
    stored = user.password_hash if user else "0" * 32 + ":" + "0" * 128
    if not verify_password(data.password, stored) or not user:
        raise HTTPException(401, "Incorrect username or password")
    new_session(db, user, response)
    return public(user)


@app.get("/api/auth/me")
def me(user: User = Depends(current_user)):
    return public(user)


@app.post("/api/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: DBSession = Depends(get_db)):
    token = request.cookies.get(COOKIE)
    session = (
        db.get(Session, hashlib.sha256(token.encode()).hexdigest()) if token else None
    )
    if session:
        db.delete(session)
        db.commit()
    response.delete_cookie(COOKIE, path="/")


@app.get("/api/datasets")
def datasets(
    q: str = "",
    before: int = 2147483647,
    user=Depends(optional_user),
    db: DBSession = Depends(get_db),
):
    return [
        public(row, db)
        for row in db.scalars(
            select(Dataset)
            .where(
                visible_datasets(user),
                Dataset.id < before,
                or_(
                    Dataset.title.icontains(q[:100], autoescape=True),
                    Dataset.filename.icontains(q[:100], autoescape=True),
                ),
            )
            .order_by(Dataset.id.desc())
            .limit(100)
        )
    ]


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
    return {**public(obj, db), "preview": preview}


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
    q: str = "",
    status: Literal["all", "open", "closed"] = "all",
    category: str = "",
    sort: Literal["newest", "closing", "title"] = "newest",
    db: DBSession = Depends(get_db),
):
    return challenge_listing(db, q, "competition", status, category, sort)


@app.get("/api/competitions/filters")
def competition_filters(db: DBSession = Depends(get_db)):
    categories = db.scalars(
        challenge_query("competition")
        .with_only_columns(Competition.category)
        .distinct()
    )
    return {"categories": sorted(category for category in categories if category)}


def challenge_listing(db, q, kind, status="all", category="", sort="newest"):
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
    return [public(row, db) for row in rows[:100]]


@app.get("/api/benchmarks")
def benchmarks(q: str = "", db: DBSession = Depends(get_db)):
    return challenge_listing(db, q, "benchmark")


@app.post("/api/competitions", status_code=201)
@app.post("/api/benchmarks", status_code=201)
async def create_challenge(
    request: Request,
    title: str = Form(min_length=3, max_length=160),
    description: str = Form(min_length=3, max_length=5000),
    category: str = Form(default="Regression", min_length=1, max_length=80),
    prize: str = Form(default="Knowledge", max_length=80),
    metric: Literal["RMSE", "MAE", "Accuracy", "LogLoss"] = Form(default="RMSE"),
    deadline: str = Form(default=""),
    test_file: UploadFile = File(),
    solution_file: UploadFile = File(),
    user: User = Depends(current_user),
    db: DBSession = Depends(get_db),
):
    kind = "benchmark" if request.url.path.endswith("benchmarks") else "competition"
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
    try:
        test_text, solution = validate_challenge(test_content, answer_content)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if metric == "LogLoss" and any(value not in (0, 1) for value in solution.values()):
        raise HTTPException(422, "Binary log loss answers must be 0 or 1")
    obj = Competition(
        title=title,
        description=description,
        category=category,
        prize=prize,
        metric=metric,
        deadline=closes.astimezone(timezone.utc).isoformat(),
        solution=json.dumps(solution),
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
    db.commit()
    return public(obj, db)


@app.get("/api/benchmarks/{id}")
@app.get("/api/competitions/{id}")
def competition(id: int, db: DBSession = Depends(get_db)):
    obj = require(db, Competition, id)
    from .team_scoring import leaderboard

    return {
        **public(obj, db),
        "participants": db.scalar(
            select(func.count()).select_from(Entry).where(Entry.competition_id == id)
        ),
        "leaderboard": leaderboard(db, obj),
    }


@app.post("/api/benchmarks/{id}/join")
@app.post("/api/competitions/{id}/join")
def join(id: int, user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    obj = require(db, Competition, id)
    if datetime.fromisoformat(obj.deadline) < datetime.now(timezone.utc):
        raise HTTPException(409, "Competition has closed")
    if not db.scalar(
        select(Entry).where(Entry.user_id == user.id, Entry.competition_id == id)
    ):
        db.add(Entry(user_id=user.id, competition_id=id))
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
    details = db.get(ChallengeDetails, id)
    return Response(
        (
            details.test_csv
            if details
            else "id,temperature,working_day\n7,20,1\n8,10,1\n9,23,0\n"
        ),
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
    obj = db.scalar(select(Competition).where(Competition.id == id).with_for_update())
    if not obj:
        raise HTTPException(404, "Competition not found")
    if datetime.fromisoformat(obj.deadline) < datetime.now(timezone.utc):
        raise HTTPException(409, "Competition has closed")
    if not db.scalar(
        select(Entry).where(Entry.user_id == user.id, Entry.competition_id == id)
    ):
        raise HTTPException(403, "Join the competition before submitting")
    if not json.loads(obj.solution):
        raise HTTPException(
            409,
            "Local scoring is unavailable: official evaluation answers were not imported",
        )
    content = await read_upload(file, 1024 * 1024)
    try:
        score = score_csv(content, json.loads(obj.solution), obj.metric)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    submission = Submission(
        user_id=user.id,
        competition_id=id,
        filename=os.path.basename(file.filename or "submission.csv"),
        score=score,
    )
    db.add(submission)
    from .team_scoring import attach_team

    attach_team(db, submission)
    db.commit()
    return public(submission)


@app.get("/api/benchmarks/{id}/submissions")
@app.get("/api/competitions/{id}/submissions")
def my_submissions(
    id: int, user: User = Depends(current_user), db: DBSession = Depends(get_db)
):
    from .team_scoring import history_filter

    require(db, Competition, id)
    return [
        public(row)
        for row in db.scalars(
            select(Submission)
            .where(history_filter(db, id, user), Submission.competition_id == id)
            .order_by(Submission.id.desc())
            .limit(100)
        )
    ]


@app.get("/api/notebooks")
def notebooks(
    q: str = "", user=Depends(optional_user), db: DBSession = Depends(get_db)
):
    return [
        public(row, db)
        for row in db.scalars(
            select(Notebook)
            .where(
                visible_notebooks(user),
                Notebook.title.icontains(q[:100], autoescape=True),
            )
            .order_by(Notebook.id.desc())
            .limit(100)
        )
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
    if obj.owner_id != user.id:
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


@app.get("/api/courses")
def courses(q: str = "", db: DBSession = Depends(get_db)):
    return [
        {**item, "lessons": json.loads(item["lessons"])}
        for item in listing(db, Course, q)
    ]


@app.get("/api/courses/{id}/progress")
def progress(
    id: int, user: User = Depends(current_user), db: DBSession = Depends(get_db)
):
    require(db, Course, id)
    return list(
        db.scalars(
            select(Progress.lesson_index).where(
                Progress.user_id == user.id, Progress.course_id == id
            )
        )
    )


@app.post("/api/courses/{id}/lessons/{index}/complete")
def complete(
    id: int,
    index: int,
    user: User = Depends(current_user),
    db: DBSession = Depends(get_db),
):
    course = require(db, Course, id)
    if not 0 <= index < len(json.loads(course.lessons)):
        raise HTTPException(404, "Lesson not found")
    if not db.scalar(
        select(Progress).where(
            Progress.user_id == user.id,
            Progress.course_id == id,
            Progress.lesson_index == index,
        )
    ):
        db.add(Progress(user_id=user.id, course_id=id, lesson_index=index))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    return {"completed": True}


@app.get("/api/discussions")
def discussions(q: str = "", db: DBSession = Depends(get_db)):
    return listing(db, Discussion, q)


@app.post("/api/discussions", status_code=201)
def create_discussion(
    data: DiscussionInput,
    user: User = Depends(current_user),
    db: DBSession = Depends(get_db),
):
    obj = Discussion(owner_id=user.id, **data.model_dump())
    db.add(obj)
    db.commit()
    return public(obj, db)


@app.get("/api/discussions/{id}/comments")
def comments(id: int, db: DBSession = Depends(get_db)):
    require(db, Discussion, id)
    return [
        public(row, db)
        for row in db.scalars(
            select(Comment)
            .where(Comment.discussion_id == id)
            .order_by(Comment.id)
            .limit(100)
        )
    ]


@app.post("/api/discussions/{id}/comments", status_code=201)
def add_comment(
    id: int,
    data: CommentInput,
    user: User = Depends(current_user),
    db: DBSession = Depends(get_db),
):
    require(db, Discussion, id)
    obj = Comment(discussion_id=id, owner_id=user.id, body=data.body)
    db.add(obj)
    db.commit()
    return public(obj, db)


@app.get("/api/models")
def models(q: str = "", db: DBSession = Depends(get_db)):
    return listing(db, ModelCard, q)


@app.get("/api/models/{id}")
def model_detail(id: int, user=Depends(optional_user), db: DBSession = Depends(get_db)):
    from .artifacts import resource
    from .models import ArtifactVersion

    return {
        **public(resource(db, "models", id, user), db),
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
    if kind in WORK_MODELS:
        row = db.get(WORK_MODELS[kind], id)
        owner_id = row.owner_id if row else None
    elif kind in ("competitions", "benchmarks"):
        details = db.get(ChallengeDetails, id)
        expected = "benchmark" if kind == "benchmarks" else "competition"
        row = db.get(Competition, id) if details and details.kind == expected else None
        owner_id = details.owner_id if row else None
    else:
        raise HTTPException(404, "Work not found")
    if row is None or owner_id != user.id:
        raise HTTPException(404, "Work not found")
    return row


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
    async with user_lock(user.id):
        row = owned_work(kind, id, user, db)
        db.refresh(row, with_for_update=True)
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
                            owner_id=user.id, kind="benchmark-run", path=directory.name
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
            delete_artifacts(db, kind, id, user.id)
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
                owner_id=user.id, kind="upload", path=row.storage_key
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
                    WorkFileDeletion(owner_id=user.id, kind="notebook-output", path=key)
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
                owner_id=user.id, kind="notebook", path=f"arena-notebook-{id}.ipynb"
            )
            db.add(task)
        elif kind in ("competitions", "benchmarks"):
            from .models import SubmissionTeam

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
    return Response(status_code=204)


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
