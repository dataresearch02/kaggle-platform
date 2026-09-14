# Learn: courses, graded exercises and certificates

Courses have real pages: `#courses` lists them, `#courses/{id}` shows a course and
`#courses/{id}/lessons/{lessonId}` a lesson with its exercises. Authors edit at
`#courses/{id}/edit` and `#courses/{id}/lessons/{lessonId}/edit`. Certificates are
printable at `#certificates/{code}`. The code is in `apps/api/app/learn.py`,
`learn_content.py` (seeded exercises and the upgrade backfill) and the worker in
`compute_worker.py`.

## Authoring

- **Who:** hosts and administrators create courses (**Learn → Create course**). A host
  edits their own courses; administrators edit every course, including the seeded ones
  (which have no owner). Changes to someone else's course, publication and deletion are
  recorded in the audit log.
- **Course:** title, summary, difficulty (beginner, intermediate or advanced), duration
  and ordered lessons. New courses are drafts. Drafts, their lessons and exercises are
  visible only to the author and administrators; everyone else gets 404, and drafts are
  excluded from lists and search.
- **Publish and unpublish:** publishing needs at least one lesson. Unpublishing hides a
  course again without deleting progress. Only drafts can be deleted, and only if no
  certificate was issued for the course.
- **Order:** lessons and exercises are reordered in the editors. Administrators can set
  the catalog order with `PUT /api/courses/order`.
- **Lessons** are Markdown, rendered with the same sanitized Markdown component as the
  rest of Arena (no raw scripts, no remote images). The editor has a preview tab.

## Exercises

Each exercise has a prompt (Markdown), starter code, progressive hints, a solution,
hidden checker code, "reveal the solution after N checked attempts" (0 means only after
passing) and optional practice datasets.

### Checker contract

The checker is Python that runs **after the learner's code, in the same fresh kernel**,
so it can use the learner's variables and functions.

| Checker action | Result |
| --- | --- |
| `assert condition, "message"` fails | Failed, with the message |
| `arena_fail("message")` | Failed, with the message |
| `arena_pass("message")` | Passed, with the message |
| Finishes without error | Passed ("Correct! All checks passed.") |
| Raises another exception | Failed ("The checks stopped with TypeError: …") |

If the learner's code raises an error or exceeds the time limit, the checker does not
run and the attempt fails with the error. Output printed by the checker is never shown;
only the verdict message is. Messages are written for learners, so do not put secrets
in them. Checkers are compiled when saved, so syntax errors are rejected with the line
number.

Practice datasets are copied to `input/<slug>/train.csv` and `input/<slug>/test.csv`
(never answer files) in attempts, in notebooks opened from the exercise, and in
background runs of those notebooks. The available slugs are listed by
`GET /api/learn/practice-inputs`.

Limits: `EXERCISE_CELL_TIMEOUT_SECONDS` (default 60) for the learner's code and for the
checks, `EXERCISE_TIMEOUT_SECONDS` (default 180) for the whole Job including start-up.
Output shown to learners is truncated to 20,000 characters of stdout, 8,000 of errors
and 2,000 of message, with terminal escape codes removed.

### Attempts

**Run checks** queues an attempt. The evaluation worker runs it as a Kubernetes Job
(Docker container locally) with the runtime image, no network, no service-account
token, CPU/memory limits, a deadline and only its own work directory. Attempts are CPU
by default; GPU is available when allowed and counts toward the weekly GPU quota (see
[compute](compute.md)). A learner can have one queued or running attempt at a time.
Status moves from queued to running to passed or failed; the page polls for the result.

Checker verdicts and timeouts count as attempts. Infrastructure failures (for example
the cluster being unavailable or a worker restart) are reported but not counted. The
work directory, including the learner's code, is deleted after each attempt.

Hints are revealed one at a time with **Show a hint**. The solution is returned only
after a passing attempt or after `reveal_after` counted attempts.

**Open in notebook** creates a normal temporary notebook draft
(`POST /api/notebook-drafts?exercise_id=…`) with the prompt, the starter code and the
exercise's practice data. It is not graded; learners check their answer on the lesson.

### Secrecy and isolation

- Learner API responses (`/api/courses`, lessons, `/api/exercises/{id}`, attempts)
  never include checker code. Solutions appear only once unlocked. Only authors and
  administrators can call `GET /api/exercises/{id}/source` and the lesson `source`
  endpoint. Tests scan learner responses for checker text.
- The runner reads `checker.py` and deletes it before the learner's code starts, so the
  learner cannot read the file. The verdict is printed after a random marker generated
  per attempt, and only the learner cell's output is returned.
- Limitation: because the checker shares the learner's kernel, a determined learner can
  tamper with the checks (for example by replacing functions the checker calls).
  Certificates are learning records, not proctored exams.

## Progress and certificates

Learners mark lessons complete; exercise progress (attempts, hints revealed, passed) is
tracked per exercise. When a learner has passed every exercise of a published course
(with at least one exercise), Arena issues a certificate once, with a random
80-bit verification code such as `3F9A1-0C7D2-B84E6-19A0F`. A learner who finished
before the course was published receives it on their next visit to the course.

- `#certificates/{code}` shows a printable certificate (**Print** prints only the
  certificate). Anyone with the code can verify it with `GET /api/certificates/{code}`.
  The holder's username is always shown; the display name only when their profile is
  public.
- Certificates are listed on the holder's profile overview. The list follows profile
  visibility: a private or hidden profile returns 404 to other users.
- Certificates keep the course title as issued, even if the course changes later.

## Seeded courses and upgrades

Python foundations, Pandas essentials and Intro to machine learning each have three
graded exercises. The Pandas and machine learning exercises use the wine cultivar and
diabetes practice datasets; all are solvable offline with the runtime image's pandas and
scikit-learn and have been checked against it.

Existing installations upgrade in place:

1. Migration `0011_course_authoring` adds `owner_id`, `difficulty`, `status`
   (existing courses stay `published`), `position` (id order), `created_at`,
   `updated_at` and `published_at` to `courses`.
2. At startup `ensure_learning_content` converts legacy lesson JSON into lessons (the
   old text becomes Markdown and the code snippet a fenced Python block), maps legacy
   per-index completion to lesson progress and adds the seeded exercises. Each step
   records a `content_receipts` row, so it runs once; authors can later edit or delete
   the converted content. The legacy `courses.lessons` and `progress` data are kept.

The original `GET /api/courses/{id}/progress` and
`POST /api/courses/{id}/lessons/{index}/complete` endpoints keep working by lesson
position.

## API

| Method and path | Purpose |
| --- | --- |
| `GET /api/courses`, `POST /api/courses` | List visible courses; create a draft (host/admin) |
| `GET/PUT/DELETE /api/courses/{id}` | Course detail with progress; update; delete a draft |
| `POST /api/courses/{id}/publish`, `/unpublish` | Change publication |
| `PUT /api/courses/order` | Catalog order (admin) |
| `POST /api/courses/{id}/lessons`, `PUT …/lessons/order` | Add and reorder lessons |
| `GET/PUT/DELETE /api/courses/{id}/lessons/{lessonId}` | Lesson for learners; update; delete |
| `GET /api/courses/{id}/lessons/{lessonId}/source` | Lesson with full exercises (author) |
| `POST …/lessons/{lessonId}/exercises`, `PUT …/exercises/order` | Add and reorder exercises |
| `GET /api/exercises/{id}` / `GET …/source` | Learner view / author view |
| `PUT/DELETE /api/exercises/{id}` | Update or delete an exercise |
| `POST /api/exercises/{id}/hints` | Reveal the next hint |
| `POST/GET /api/exercises/{id}/attempts`, `GET /api/exercise-attempts/{id}` | Queue, list and poll attempts |
| `POST /api/lessons/{lessonId}/complete` | Mark a lesson complete |
| `GET /api/certificates/{code}` | Public verification |
| `GET /api/profiles/{username}/certificates` | Certificates on a profile |
| `GET /api/learn/practice-inputs` | Practice datasets for exercises |
