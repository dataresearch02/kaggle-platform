import csv
import hashlib
import io
import json
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone

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
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from .auth import COOKIE, current_user, hash_password, new_session, verify_password
from .db import Base, DATA_DIR, SessionLocal, engine, get_db
from .models import (
    Comment,
    Competition,
    Course,
    Dataset,
    Discussion,
    Entry,
    ModelCard,
    Notebook,
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
)
from .scoring import score_csv
from .seed import seed
from .notebook_runtime import router as notebook_router, notebook_document


@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
    yield


app = FastAPI(
    title="Arena API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)
app.include_router(notebook_router)


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
        if request.headers.get("x-arena-client") != "web" or (
            origin and origin not in allowed
        ):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "Invalid request origin or missing X-Arena-Client header"
                },
            )
    response = await call_next(request)
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
    return {
        name: db.scalar(select(func.count()).select_from(cls))
        for name, cls in [
            ("datasets", Dataset),
            ("competitions", Competition),
            ("notebooks", Notebook),
            ("learners", User),
        ]
    }


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
def datasets(q: str = "", db: DBSession = Depends(get_db)):
    return listing(db, Dataset, q)


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
        db.commit()
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    return public(obj, db)


@app.get("/api/datasets/{id}")
def dataset_detail(id: int, db: DBSession = Depends(get_db)):
    obj = require(db, Dataset, id)
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
def download_dataset(id: int, db: DBSession = Depends(get_db)):
    obj = require(db, Dataset, id)
    return FileResponse(
        DATA_DIR / "uploads" / obj.storage_key,
        filename=obj.filename,
        media_type="text/csv",
    )


@app.get("/api/competitions")
def competitions(q: str = "", db: DBSession = Depends(get_db)):
    return listing(db, Competition, q)


@app.get("/api/competitions/{id}")
def competition(id: int, db: DBSession = Depends(get_db)):
    obj = require(db, Competition, id)
    scores = db.execute(
        select(User.username, func.min(Submission.score).label("score"))
        .join(Submission, Submission.user_id == User.id)
        .where(Submission.competition_id == id)
        .group_by(User.id, User.username)
        .order_by(func.min(Submission.score), User.username)
        .limit(100)
    ).all()
    return {
        **public(obj),
        "participants": db.scalar(
            select(func.count()).select_from(Entry).where(Entry.competition_id == id)
        ),
        "leaderboard": [
            {"rank": i + 1, "username": row.username, "score": row.score}
            for i, row in enumerate(scores)
        ],
    }


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


@app.get("/api/competitions/{id}/sample")
def sample(id: int, db: DBSession = Depends(get_db)):
    obj = require(db, Competition, id)
    content = "id,prediction\n" + "".join(
        f"{key},0\n" for key in json.loads(obj.solution)
    )
    return Response(
        content,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="sample_submission.csv"'},
    )


@app.get("/api/competitions/{id}/test")
def test_features(id: int, db: DBSession = Depends(get_db)):
    require(db, Competition, id)
    return Response(
        "id,temperature,working_day\n7,20,1\n8,10,1\n9,23,0\n",
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="test.csv"'},
    )


@app.post("/api/competitions/{id}/submissions", status_code=201)
async def submit(
    id: int,
    file: UploadFile = File(),
    user: User = Depends(current_user),
    db: DBSession = Depends(get_db),
):
    obj = require(db, Competition, id)
    if datetime.fromisoformat(obj.deadline) < datetime.now(timezone.utc):
        raise HTTPException(409, "Competition has closed")
    if not db.scalar(
        select(Entry).where(Entry.user_id == user.id, Entry.competition_id == id)
    ):
        raise HTTPException(403, "Join the competition before submitting")
    content = await read_upload(file, 1024 * 1024)
    try:
        score = score_csv(content, json.loads(obj.solution))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    submission = Submission(
        user_id=user.id,
        competition_id=id,
        filename=os.path.basename(file.filename or "submission.csv"),
        score=score,
    )
    db.add(submission)
    db.commit()
    return public(submission)


@app.get("/api/competitions/{id}/submissions")
def my_submissions(
    id: int, user: User = Depends(current_user), db: DBSession = Depends(get_db)
):
    require(db, Competition, id)
    return [
        public(row)
        for row in db.scalars(
            select(Submission)
            .where(Submission.user_id == user.id, Submission.competition_id == id)
            .order_by(Submission.id.desc())
            .limit(100)
        )
    ]


@app.get("/api/notebooks")
def notebooks(q: str = "", db: DBSession = Depends(get_db)):
    return listing(db, Notebook, q)


@app.post("/api/notebooks", status_code=201)
def create_notebook(
    data: NotebookInput,
    user: User = Depends(current_user),
    db: DBSession = Depends(get_db),
):
    obj = Notebook(owner_id=user.id, **data.model_dump())
    db.add(obj)
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
    db.commit()
    return public(obj, db)


@app.get("/api/notebooks/{id}/download")
def download_notebook(id: int, db: DBSession = Depends(get_db)):
    obj = require(db, Notebook, id)
    notebook = notebook_document(obj)
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


@app.post("/api/models", status_code=201)
def create_model(
    data: ModelInput,
    user: User = Depends(current_user),
    db: DBSession = Depends(get_db),
):
    obj = ModelCard(owner_id=user.id, **{**data.model_dump(), "url": str(data.url)})
    db.add(obj)
    db.commit()
    return public(obj, db)
