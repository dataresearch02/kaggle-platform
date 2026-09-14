"""Learn: course authoring, Markdown lessons, graded exercises and certificates.

Hosts and administrators create courses; hosts edit their own and administrators edit
any. Drafts are visible only to their author and administrators. Exercise checker code
and solutions never appear in learner responses: `exercise_json` reveals hints one at
a time and the solution only after a passing attempt or `reveal_after` finished
attempts. Only `exercise_source_json` (authors and administrators) includes them.

Attempts are queued here and executed by the evaluation worker in an isolated,
network-less runtime (compute_worker.py). The checker runs after the learner's code in
the same fresh kernel. Passing every exercise of a published course issues a
certificate with a random verification code.
"""

import json
import re
import secrets
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, or_, select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import current_user
from .code_pages import optional_user
from .compute import Accelerator, lock_pool, require_gpu
from .db import get_db
from .models import (
    Certificate,
    Course,
    CourseExercise,
    CourseLesson,
    ExerciseAttempt,
    ExerciseProgress,
    LessonProgress,
    NotebookDraftExercise,
    Progress,
    User,
    UserProfile,
    now,
)
from .moderation import record
from .pagination import Page, count, page, set_total, window
from .permissions import is_admin
from .practice_inputs import known_slugs, validate_slugs

router = APIRouter(prefix="/api", tags=["Learn"])
ACTIVE_ATTEMPT = ("queued", "running")
LIMITS = {"message": 2000, "stdout": 20000, "error": 8000}
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def clip(value, limit):
    """Remove terminal escapes and control characters, then truncate safely."""
    value = ANSI.sub("", str(value or "")).replace("\x00", "")
    if len(value) > limit:
        value = value[: limit - 30] + "\n… output truncated …"
    return value


def can_author(user):
    return bool(user and user.status == "active" and user.role in ("host", "admin"))


def can_edit(user, course):
    return can_author(user) and (
        is_admin(user) or (course.owner_id is not None and course.owner_id == user.id)
    )


def visible_courses(user):
    if is_admin(user):
        return true()
    if can_author(user):
        return or_(Course.status == "published", Course.owner_id == user.id)
    return Course.status == "published"


def course_for(db, id, user):
    course = db.get(Course, id)
    if not course or (course.status != "published" and not can_edit(user, course)):
        raise HTTPException(404, "Course not found")
    return course


def editable(db, id, user):
    course = course_for(db, id, user)
    if not can_edit(user, course):
        raise HTTPException(
            403, "Only the course author or an administrator can edit this course"
        )
    db.refresh(course, with_for_update=True)
    return course


def lessons_of(db, course_id):
    return list(
        db.scalars(
            select(CourseLesson)
            .where(CourseLesson.course_id == course_id)
            .order_by(CourseLesson.position, CourseLesson.id)
        )
    )


def exercises_of(db, lesson_id):
    return list(
        db.scalars(
            select(CourseExercise)
            .where(CourseExercise.lesson_id == lesson_id)
            .order_by(CourseExercise.position, CourseExercise.id)
        )
    )


def lesson_for(db, course, lesson_id):
    lesson = db.get(CourseLesson, lesson_id)
    if not lesson or lesson.course_id != course.id:
        raise HTTPException(404, "Lesson not found")
    return lesson


def exercise_context(db, id, user, edit=False):
    exercise = db.get(CourseExercise, id)
    lesson = db.get(CourseLesson, exercise.lesson_id) if exercise else None
    if not exercise or not lesson:
        raise HTTPException(404, "Exercise not found")
    course = (editable if edit else course_for)(db, lesson.course_id, user)
    return exercise, lesson, course


def course_exercise_ids(course_id):
    return (
        select(CourseExercise.id)
        .join(CourseLesson, CourseLesson.id == CourseExercise.lesson_id)
        .where(CourseLesson.course_id == course_id)
    )


def course_json(db, course, user):
    lessons = lessons_of(db, course.id)
    ids = [lesson.id for lesson in lessons]
    counts = dict(
        db.execute(
            select(CourseExercise.lesson_id, func.count())
            .where(CourseExercise.lesson_id.in_(ids))
            .group_by(CourseExercise.lesson_id)
        ).all()
    )
    owner = db.get(User, course.owner_id) if course.owner_id else None
    result = {
        "id": course.id,
        "title": course.title,
        "summary": course.description,
        "description": course.description,
        "difficulty": course.difficulty,
        "duration": course.duration,
        "status": course.status,
        "position": course.position,
        "owner_id": course.owner_id,
        "owner": owner.username if owner else "Arena",
        "created_at": course.created_at,
        "updated_at": course.updated_at,
        "published_at": course.published_at,
        "lesson_count": len(lessons),
        "exercise_count": sum(counts.values()),
        "lessons": [
            {
                "id": lesson.id,
                "title": lesson.title,
                "position": index,
                "exercise_count": counts.get(lesson.id, 0),
            }
            for index, lesson in enumerate(lessons)
        ],
        "can_edit": can_edit(user, course),
    }
    if user:
        completed = set(
            db.scalars(
                select(LessonProgress.lesson_id).where(
                    LessonProgress.user_id == user.id,
                    LessonProgress.lesson_id.in_(ids),
                )
            )
        )
        passed = db.scalar(
            select(func.count())
            .select_from(ExerciseProgress)
            .where(
                ExerciseProgress.user_id == user.id,
                ExerciseProgress.exercise_id.in_(course_exercise_ids(course.id)),
                ExerciseProgress.passed_at.is_not(None),
            )
        )
        certificate = db.scalar(
            select(Certificate.code).where(
                Certificate.user_id == user.id, Certificate.course_id == course.id
            )
        )
        for lesson in result["lessons"]:
            lesson["completed"] = lesson["id"] in completed
        result["progress"] = {
            "completed_lessons": len(completed),
            "passed_exercises": passed,
            "certificate": certificate,
        }
    return result


def attempt_json(row):
    return {
        "id": row.id,
        "exercise_id": row.exercise_id,
        "status": row.status,
        "accelerator": row.accelerator,
        "code": row.code,
        "message": row.message,
        "stdout": row.stdout,
        "error": row.error,
        "created_at": row.created_at,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
    }


def exercise_json(db, exercise, user):
    """Learner view. Never includes the checker; the solution only once allowed."""
    progress = db.get(ExerciseProgress, (user.id, exercise.id)) if user else None
    hints = json.loads(exercise.hints or "[]")
    attempts = progress.attempts if progress else 0
    passed = bool(progress and progress.passed_at)
    allowed = passed or (
        exercise.reveal_after > 0 and attempts >= exercise.reveal_after
    )
    latest = (
        db.scalar(
            select(ExerciseAttempt)
            .where(
                ExerciseAttempt.exercise_id == exercise.id,
                ExerciseAttempt.user_id == user.id,
            )
            .order_by(ExerciseAttempt.id.desc())
            .limit(1)
        )
        if user
        else None
    )
    return {
        "id": exercise.id,
        "lesson_id": exercise.lesson_id,
        "position": exercise.position,
        "title": exercise.title,
        "prompt": exercise.prompt,
        "starter_code": exercise.starter_code,
        "inputs": known_slugs(json.loads(exercise.inputs or "[]")),
        "hint_count": len(hints),
        "hints": hints[: min(progress.hints_revealed, len(hints)) if progress else 0],
        "reveal_after": exercise.reveal_after,
        "attempts": attempts,
        "passed": passed,
        "passed_at": progress.passed_at if progress else None,
        "solution_available": allowed,
        "solution": exercise.solution if allowed else None,
        "latest_attempt": attempt_json(latest) if latest else None,
    }


def exercise_source_json(exercise):
    """Author view, including the hidden checker and the solution."""
    return {
        "id": exercise.id,
        "lesson_id": exercise.lesson_id,
        "position": exercise.position,
        "title": exercise.title,
        "prompt": exercise.prompt,
        "starter_code": exercise.starter_code,
        "hints": json.loads(exercise.hints or "[]"),
        "solution": exercise.solution,
        "checker": exercise.checker,
        "reveal_after": exercise.reveal_after,
        "inputs": json.loads(exercise.inputs or "[]"),
        "updated_at": exercise.updated_at,
    }


def lesson_json(db, course, lesson, user, source=False):
    lessons = lessons_of(db, course.id)
    index = next(i for i, row in enumerate(lessons) if row.id == lesson.id)
    exercises = exercises_of(db, lesson.id)
    return {
        "id": lesson.id,
        "course_id": course.id,
        "course_title": course.title,
        "course_status": course.status,
        "title": lesson.title,
        "body": lesson.body,
        "position": index,
        "lesson_count": len(lessons),
        "previous_id": lessons[index - 1].id if index > 0 else None,
        "next_id": lessons[index + 1].id if index + 1 < len(lessons) else None,
        "completed": bool(user and db.get(LessonProgress, (user.id, lesson.id))),
        "can_edit": can_edit(user, course),
        "updated_at": lesson.updated_at,
        "exercises": [
            exercise_source_json(row) if source else exercise_json(db, row, user)
            for row in exercises
        ],
    }


def new_code():
    raw = secrets.token_hex(10).upper()
    return "-".join(raw[index : index + 5] for index in range(0, 20, 5))


def maybe_issue_certificate(db, user_id, course):
    """Issue once every exercise of a published course is passed; returns it or None."""
    if course is None or course.status != "published":
        return None
    existing = db.scalar(
        select(Certificate).where(
            Certificate.user_id == user_id, Certificate.course_id == course.id
        )
    )
    if existing:
        return existing
    total = db.scalar(
        select(func.count()).select_from(course_exercise_ids(course.id).subquery())
    )
    passed = db.scalar(
        select(func.count())
        .select_from(ExerciseProgress)
        .where(
            ExerciseProgress.user_id == user_id,
            ExerciseProgress.exercise_id.in_(course_exercise_ids(course.id)),
            ExerciseProgress.passed_at.is_not(None),
        )
    )
    if not total or passed < total:
        return None
    certificate = Certificate(
        code=new_code(),
        user_id=user_id,
        course_id=course.id,
        course_title=course.title,
        issued_at=now(),
    )
    db.add(certificate)
    db.flush()
    return certificate


def progress_row(db, user_id, exercise_id):
    row = db.get(ExerciseProgress, (user_id, exercise_id))
    if row is None:
        row = ExerciseProgress(
            user_id=user_id, exercise_id=exercise_id, attempts=0, hints_revealed=0
        )
        db.add(row)
    return row


def finish_attempt(db, attempt, status, message="", stdout="", error="", counted=True):
    """Record a verdict. Only checker verdicts and timeouts count as attempts."""
    attempt.status = status
    attempt.message = clip(message, LIMITS["message"])
    attempt.stdout = clip(stdout, LIMITS["stdout"])
    attempt.error = clip(error, LIMITS["error"])
    attempt.finished_at = now()
    if not counted or status not in ("passed", "failed"):
        return
    progress = progress_row(db, attempt.user_id, attempt.exercise_id)
    progress.attempts = (progress.attempts or 0) + 1
    if status == "passed" and not progress.passed_at:
        progress.passed_at = now()
    db.flush()
    if status == "passed":
        exercise = db.get(CourseExercise, attempt.exercise_id)
        lesson = db.get(CourseLesson, exercise.lesson_id) if exercise else None
        if lesson:
            maybe_issue_certificate(
                db, attempt.user_id, db.get(Course, lesson.course_id)
            )


def remove_exercises(db, exercise_ids):
    """Delete exercises with their attempts, progress and draft links."""
    for model in (NotebookDraftExercise, ExerciseAttempt, ExerciseProgress):
        db.execute(delete(model).where(model.exercise_id.in_(exercise_ids)))
    db.execute(delete(CourseExercise).where(CourseExercise.id.in_(exercise_ids)))


def remove_lessons(db, lesson_ids):
    remove_exercises(
        db,
        list(
            db.scalars(
                select(CourseExercise.id).where(
                    CourseExercise.lesson_id.in_(lesson_ids)
                )
            )
        ),
    )
    db.execute(delete(LessonProgress).where(LessonProgress.lesson_id.in_(lesson_ids)))
    db.execute(delete(CourseLesson).where(CourseLesson.id.in_(lesson_ids)))


def audit(db, user, course, action, detail=None):
    """Audit publishing, deletion and changes to someone else's course."""
    if action in ("course.publish", "course.unpublish", "course.delete") or (
        course.owner_id != user.id
    ):
        record(
            db,
            user,
            action,
            "course",
            course.id,
            {"title": course.title, "owner_id": course.owner_id, **(detail or {})},
        )


def plain(value, name):
    value = value.strip()
    if len(value) < 3:
        raise ValueError(f"{name} must contain at least three characters")
    return value


class CourseInput(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    summary: str = Field(min_length=3, max_length=2000)
    difficulty: Literal["beginner", "intermediate", "advanced"] = "beginner"
    duration: str = Field(default="", max_length=40)

    @field_validator("title")
    @classmethod
    def valid_title(cls, value):
        return plain(value, "Title")

    @field_validator("summary")
    @classmethod
    def valid_summary(cls, value):
        return plain(value, "Summary")


class LessonInput(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(default="", max_length=100000)

    @field_validator("title")
    @classmethod
    def valid_title(cls, value):
        if not value.strip():
            raise ValueError("Enter a lesson title")
        return value.strip()


class ExerciseInput(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    prompt: str = Field(min_length=1, max_length=20000)
    starter_code: str = Field(default="", max_length=50000)
    hints: list[str] = Field(default_factory=list, max_length=10)
    solution: str = Field(min_length=1, max_length=50000)
    checker: str = Field(min_length=1, max_length=50000)
    reveal_after: int = Field(default=3, ge=0, le=100)
    inputs: list[str] = Field(default_factory=list, max_length=4)

    @field_validator("title")
    @classmethod
    def valid_title(cls, value):
        return plain(value, "Title")

    @field_validator("hints")
    @classmethod
    def valid_hints(cls, values):
        if any(not value.strip() or len(value) > 2000 for value in values):
            raise ValueError("Hints must contain 1–2,000 characters")
        return [value.strip() for value in values]

    @field_validator("inputs")
    @classmethod
    def valid_inputs(cls, values):
        return validate_slugs(values)

    @field_validator("checker")
    @classmethod
    def compiles(cls, value):
        try:
            compile(value, "checker", "exec")
        except SyntaxError as error:
            raise ValueError(
                f"The checker has a syntax error on line {error.lineno}: {error.msg}"
            )
        return value


class OrderInput(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=1000)


class AttemptInput(BaseModel):
    code: str = Field(min_length=1, max_length=100000)
    accelerator: Accelerator = "cpu"


def reorder(rows, ids, start=0):
    if len(ids) != len(rows) or set(ids) != {row.id for row in rows}:
        raise HTTPException(422, "List every item exactly once")
    by_id = {row.id: row for row in rows}
    for position, id in enumerate(ids, start=start):
        by_id[id].position = position


@router.get("/learn/practice-inputs")
def practice_inputs():
    """Practice datasets exercises may use as input/<slug>/ (train and test files)."""
    from .practice_inputs import PRACTICE, practice_slugs

    return [
        {
            "slug": slug,
            "title": json.loads((PRACTICE / slug / "meta.json").read_text())["title"],
        }
        for slug in practice_slugs()
    ]


@router.get("/courses")
def list_courses(
    response: Response,
    q: str = "",
    pagination: Page = Depends(page),
    user=Depends(optional_user),
    db: Session = Depends(get_db),
):
    query = select(Course).where(visible_courses(user))
    if q.strip():
        query = query.where(Course.title.icontains(q.strip()[:100], autoescape=True))
    set_total(response, count(db, query))
    return [
        course_json(db, row, user)
        for row in db.scalars(
            window(query.order_by(Course.position, Course.id), pagination)
        )
    ]


@router.post("/courses", status_code=201)
def create_course(
    data: CourseInput, user=Depends(current_user), db: Session = Depends(get_db)
):
    if not can_author(user):
        raise HTTPException(403, "Only hosts and administrators can create courses")
    course = Course(
        title=data.title,
        description=data.summary,
        difficulty=data.difficulty,
        duration=data.duration.strip() or "Self-paced",
        lessons="[]",
        owner_id=user.id,
        status="draft",
        position=(db.scalar(select(func.max(Course.position))) or 0) + 1,
        created_at=now(),
        updated_at=now(),
    )
    db.add(course)
    db.commit()
    return course_json(db, course, user)


@router.put("/courses/order")
def reorder_courses(
    data: OrderInput, user=Depends(current_user), db: Session = Depends(get_db)
):
    if not is_admin(user):
        raise HTTPException(403, "Only administrators can reorder the course catalog")
    reorder(db.scalars(select(Course).with_for_update()).all(), data.ids, start=1)
    record(db, user, "course.reorder", "course", "", {"ids": data.ids})
    db.commit()
    return {"ids": data.ids}


@router.get("/courses/{id}")
def get_course(id: int, user=Depends(optional_user), db: Session = Depends(get_db)):
    course = course_for(db, id, user)
    if user and course.status == "published":
        # Learners who passed everything before publication receive it on their visit.
        try:
            if maybe_issue_certificate(db, user.id, course):
                db.commit()
        except IntegrityError:
            db.rollback()
    return course_json(db, course, user)


@router.put("/courses/{id}")
def update_course(
    id: int,
    data: CourseInput,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    course = editable(db, id, user)
    audit(db, user, course, "course.update", {"new_title": data.title})
    course.title, course.description = data.title, data.summary
    course.difficulty = data.difficulty
    course.duration = data.duration.strip() or course.duration or "Self-paced"
    course.updated_at = now()
    db.commit()
    return course_json(db, course, user)


@router.post("/courses/{id}/publish")
def publish_course(id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    course = editable(db, id, user)
    if not lessons_of(db, course.id):
        raise HTTPException(409, "Add at least one lesson before publishing")
    if course.status != "published":
        course.status, course.published_at, course.updated_at = (
            "published",
            now(),
            now(),
        )
        audit(db, user, course, "course.publish")
    db.commit()
    return course_json(db, course, user)


@router.post("/courses/{id}/unpublish")
def unpublish_course(
    id: int, user=Depends(current_user), db: Session = Depends(get_db)
):
    course = editable(db, id, user)
    if course.status != "draft":
        course.status, course.updated_at = "draft", now()
        audit(db, user, course, "course.unpublish")
    db.commit()
    return course_json(db, course, user)


@router.delete("/courses/{id}", status_code=204)
def delete_course(id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    course = editable(db, id, user)
    if course.status == "published":
        raise HTTPException(409, "Unpublish the course before deleting it")
    if db.scalar(select(Certificate.id).where(Certificate.course_id == id).limit(1)):
        raise HTTPException(
            409, "This course has issued certificates, so it cannot be deleted"
        )
    remove_lessons(db, [lesson.id for lesson in lessons_of(db, id)])
    db.execute(delete(Progress).where(Progress.course_id == id))
    audit(db, user, course, "course.delete")
    db.delete(course)
    db.commit()
    return Response(status_code=204)


@router.get("/courses/{id}/progress")
def legacy_progress(id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    """Completed lesson positions, for clients of the original course API."""
    lessons = lessons_of(db, course_for(db, id, user).id)
    completed = set(
        db.scalars(
            select(LessonProgress.lesson_id).where(
                LessonProgress.user_id == user.id,
                LessonProgress.lesson_id.in_([lesson.id for lesson in lessons]),
            )
        )
    )
    return [index for index, lesson in enumerate(lessons) if lesson.id in completed]


def mark_complete(db, user, lesson):
    if not db.get(LessonProgress, (user.id, lesson.id)):
        db.add(LessonProgress(user_id=user.id, lesson_id=lesson.id))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    return {"completed": True}


@router.post("/courses/{id}/lessons/{index}/complete")
def legacy_complete(
    id: int, index: int, user=Depends(current_user), db: Session = Depends(get_db)
):
    """Complete a lesson by position, for clients of the original course API."""
    lessons = lessons_of(db, course_for(db, id, user).id)
    if not 0 <= index < len(lessons):
        raise HTTPException(404, "Lesson not found")
    return mark_complete(db, user, lessons[index])


@router.post("/lessons/{lesson_id}/complete")
def complete_lesson(
    lesson_id: int, user=Depends(current_user), db: Session = Depends(get_db)
):
    lesson = db.get(CourseLesson, lesson_id)
    if not lesson:
        raise HTTPException(404, "Lesson not found")
    course_for(db, lesson.course_id, user)
    return mark_complete(db, user, lesson)


@router.post("/courses/{id}/lessons", status_code=201)
def create_lesson(
    id: int,
    data: LessonInput,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    course = editable(db, id, user)
    lesson = CourseLesson(
        course_id=course.id,
        position=len(lessons_of(db, course.id)),
        title=data.title,
        body=data.body,
        updated_at=now(),
    )
    db.add(lesson)
    course.updated_at = now()
    audit(db, user, course, "course.update", {"lesson": data.title})
    db.commit()
    return lesson_json(db, course, lesson, user, source=True)


@router.put("/courses/{id}/lessons/order")
def reorder_lessons(
    id: int,
    data: OrderInput,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    course = editable(db, id, user)
    reorder(lessons_of(db, course.id), data.ids)
    course.updated_at = now()
    db.commit()
    return course_json(db, course, user)


@router.get("/courses/{id}/lessons/{lesson_id}")
def get_lesson(
    id: int,
    lesson_id: int,
    user=Depends(optional_user),
    db: Session = Depends(get_db),
):
    course = course_for(db, id, user)
    return lesson_json(db, course, lesson_for(db, course, lesson_id), user)


@router.get("/courses/{id}/lessons/{lesson_id}/source")
def get_lesson_source(
    id: int,
    lesson_id: int,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    """Author view of a lesson with complete exercises."""
    course = editable(db, id, user)
    lesson = lesson_for(db, course, lesson_id)
    db.commit()  # Release the edit lock; this is a read.
    return lesson_json(db, course, lesson, user, source=True)


@router.put("/courses/{id}/lessons/{lesson_id}")
def update_lesson(
    id: int,
    lesson_id: int,
    data: LessonInput,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    course = editable(db, id, user)
    lesson = lesson_for(db, course, lesson_id)
    lesson.title, lesson.body, lesson.updated_at = data.title, data.body, now()
    course.updated_at = now()
    audit(db, user, course, "course.update", {"lesson": lesson.id})
    db.commit()
    return lesson_json(db, course, lesson, user, source=True)


@router.delete("/courses/{id}/lessons/{lesson_id}", status_code=204)
def delete_lesson(
    id: int,
    lesson_id: int,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    course = editable(db, id, user)
    lesson = lesson_for(db, course, lesson_id)
    remaining = [row for row in lessons_of(db, course.id) if row.id != lesson.id]
    if course.status == "published" and not remaining:
        raise HTTPException(409, "A published course needs at least one lesson")
    audit(db, user, course, "course.update", {"deleted_lesson": lesson.title})
    remove_lessons(db, [lesson.id])
    for position, row in enumerate(remaining):
        row.position = position
    course.updated_at = now()
    db.commit()
    return Response(status_code=204)


@router.post("/courses/{id}/lessons/{lesson_id}/exercises", status_code=201)
def create_exercise(
    id: int,
    lesson_id: int,
    data: ExerciseInput,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    course = editable(db, id, user)
    lesson = lesson_for(db, course, lesson_id)
    exercise = CourseExercise(
        lesson_id=lesson.id,
        position=len(exercises_of(db, lesson.id)),
        **exercise_fields(data),
    )
    db.add(exercise)
    audit(db, user, course, "course.update", {"exercise": data.title})
    db.commit()
    return exercise_source_json(exercise)


@router.put("/courses/{id}/lessons/{lesson_id}/exercises/order")
def reorder_exercises(
    id: int,
    lesson_id: int,
    data: OrderInput,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    course = editable(db, id, user)
    lesson = lesson_for(db, course, lesson_id)
    reorder(exercises_of(db, lesson.id), data.ids)
    db.commit()
    return lesson_json(db, course, lesson, user, source=True)


def exercise_fields(data):
    return {
        "title": data.title,
        "prompt": data.prompt,
        "starter_code": data.starter_code,
        "hints": json.dumps(data.hints),
        "solution": data.solution,
        "checker": data.checker,
        "reveal_after": data.reveal_after,
        "inputs": json.dumps(data.inputs),
        "updated_at": now(),
    }


@router.get("/exercises/{id}")
def get_exercise(id: int, user=Depends(optional_user), db: Session = Depends(get_db)):
    exercise, _, _ = exercise_context(db, id, user)
    return exercise_json(db, exercise, user)


@router.get("/exercises/{id}/source")
def get_exercise_source(
    id: int, user=Depends(current_user), db: Session = Depends(get_db)
):
    exercise, _, _ = exercise_context(db, id, user, edit=True)
    db.commit()
    return exercise_source_json(exercise)


@router.put("/exercises/{id}")
def update_exercise(
    id: int,
    data: ExerciseInput,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    exercise, _, course = exercise_context(db, id, user, edit=True)
    for key, value in exercise_fields(data).items():
        setattr(exercise, key, value)
    audit(db, user, course, "course.update", {"exercise": exercise.id})
    db.commit()
    return exercise_source_json(exercise)


@router.delete("/exercises/{id}", status_code=204)
def delete_exercise(id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    exercise, lesson, course = exercise_context(db, id, user, edit=True)
    audit(db, user, course, "course.update", {"deleted_exercise": exercise.title})
    remove_exercises(db, [exercise.id])
    for position, row in enumerate(exercises_of(db, lesson.id)):
        row.position = position
    db.commit()
    return Response(status_code=204)


@router.post("/exercises/{id}/hints")
def reveal_hint(id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    exercise, _, _ = exercise_context(db, id, user)
    db.refresh(user, with_for_update=True)
    progress = progress_row(db, user.id, exercise.id)
    if (progress.hints_revealed or 0) >= len(json.loads(exercise.hints or "[]")):
        raise HTTPException(409, "There are no more hints for this exercise")
    progress.hints_revealed = (progress.hints_revealed or 0) + 1
    db.commit()
    return exercise_json(db, exercise, user)


@router.post("/exercises/{id}/attempts", status_code=202)
def create_attempt(
    id: int,
    data: AttemptInput,
    user=Depends(current_user),
    db: Session = Depends(get_db),
):
    exercise, _, _ = exercise_context(db, id, user)
    # Serialize a user's submissions so only one attempt is ever queued or running.
    db.refresh(user, with_for_update=True)
    if db.scalar(
        select(ExerciseAttempt.id)
        .where(
            ExerciseAttempt.user_id == user.id,
            ExerciseAttempt.status.in_(ACTIVE_ATTEMPT),
        )
        .limit(1)
    ):
        raise HTTPException(
            409, "Wait for your current check to finish before running another"
        )
    if data.accelerator == "gpu":
        lock_pool(db)
        # Capacity is checked when the worker starts the attempt; it waits for a GPU.
        require_gpu(db, user, "job", check_capacity=False)
    attempt = ExerciseAttempt(
        exercise_id=exercise.id,
        user_id=user.id,
        code=data.code,
        accelerator=data.accelerator,
        status="queued",
    )
    db.add(attempt)
    db.commit()
    return attempt_json(attempt)


@router.get("/exercises/{id}/attempts")
def list_attempts(id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    exercise, _, _ = exercise_context(db, id, user)
    return [
        attempt_json(row)
        for row in db.scalars(
            select(ExerciseAttempt)
            .where(
                ExerciseAttempt.exercise_id == exercise.id,
                ExerciseAttempt.user_id == user.id,
            )
            .order_by(ExerciseAttempt.id.desc())
            .limit(20)
        )
    ]


@router.get("/exercise-attempts/{id}")
def get_attempt(id: int, user=Depends(current_user), db: Session = Depends(get_db)):
    row = db.get(ExerciseAttempt, id)
    if not row or row.user_id != user.id:
        raise HTTPException(404, "Attempt not found")
    exercise = db.get(CourseExercise, row.exercise_id)
    return {
        **attempt_json(row),
        "exercise": exercise_json(db, exercise, user) if exercise else None,
    }


def exercise_notebook(db, user, exercise_id, document):
    """Seed a new notebook draft with an exercise prompt, starter code and inputs."""
    exercise, lesson, course = exercise_context(db, exercise_id, user)
    document["cells"] = [
        {
            "id": "exercise-prompt",
            "cell_type": "markdown",
            "metadata": {},
            "source": f"# {exercise.title}\n\n{exercise.prompt}\n\n"
            f"*From {course.title} · {lesson.title}. Experiment freely here; check"
            " your answer on the lesson page.*",
        },
        {
            "id": "exercise-starter",
            "cell_type": "code",
            "metadata": {},
            "execution_count": None,
            "outputs": [],
            "source": exercise.starter_code,
        },
    ]
    slugs = known_slugs(json.loads(exercise.inputs or "[]"))
    if slugs:
        document["metadata"]["arena_practice_inputs"] = slugs
    document["metadata"]["arena_exercise"] = {
        "id": exercise.id,
        "course_id": course.id,
        "lesson_id": lesson.id,
    }
    return document


def certificate_json(db, row):
    holder = db.get(User, row.user_id)
    profile = db.get(UserProfile, row.user_id)
    course = db.get(Course, row.course_id)
    # The display name follows profile visibility; the username verifies the holder.
    public = not profile or (profile.visibility == "public" and not profile.hidden)
    details = json.loads(profile.details or "{}") if profile else {}
    return {
        "code": row.code,
        "course_id": row.course_id,
        "course_title": row.course_title,
        "course_available": bool(course and course.status == "published"),
        "issued_at": row.issued_at,
        "holder": holder.username if holder else "Deleted user",
        "holder_name": (details.get("display_name") or "") if public else "",
        "valid": True,
    }


@router.get("/certificates/{code}")
def verify_certificate(code: str, db: Session = Depends(get_db)):
    """Public verification of a certificate code."""
    row = db.scalar(
        select(Certificate).where(Certificate.code == code.strip().upper()[:40])
    )
    if not row:
        raise HTTPException(404, "Certificate not found")
    return certificate_json(db, row)


@router.get("/profiles/{username}/certificates")
def profile_certificates(
    username: str, user=Depends(optional_user), db: Session = Depends(get_db)
):
    from .accounts import visible_profile

    owner = visible_profile(db, username, user)
    return [
        certificate_json(db, row)
        for row in db.scalars(
            select(Certificate)
            .where(Certificate.user_id == owner.id)
            .order_by(Certificate.id.desc())
        )
    ]
