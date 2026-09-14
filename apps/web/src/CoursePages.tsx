import { useEffect, useState } from 'react';
import CodeMirror from '@uiw/react-codemirror';
import { python } from '@codemirror/lang-python';
import {
  ArrowLeft,
  ArrowRight,
  Award,
  BookOpen,
  Check,
  Lightbulb,
  Pencil,
  Play,
  RotateCcw,
} from 'lucide-react';
import { api, type Accelerator, type User } from './api';
import CourseEditor, { LessonEditor } from './CourseEditor';
import { InternetOff, useComputeUsage } from './GpuUsageMeter';
import Markdown from './Markdown';
import NewNotebook from './NewNotebook';
import { AcceleratorSelect } from './NotebookRuns';

export type CourseDetail = {
  id: number;
  title: string;
  summary: string;
  difficulty: string;
  duration: string;
  status: 'draft' | 'published';
  owner: string;
  lesson_count: number;
  exercise_count: number;
  can_edit: boolean;
  lessons: {
    id: number;
    title: string;
    position: number;
    exercise_count: number;
    completed?: boolean;
  }[];
  progress?: { completed_lessons: number; passed_exercises: number; certificate: string | null };
};
export type Attempt = {
  id: number;
  exercise_id: number;
  status: 'queued' | 'running' | 'passed' | 'failed';
  accelerator: Accelerator;
  code: string;
  message: string;
  stdout: string;
  error: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};
/** Learner view: never includes the checker; the solution only once unlocked. */
export type Exercise = {
  id: number;
  lesson_id: number;
  position: number;
  title: string;
  prompt: string;
  starter_code: string;
  inputs: string[];
  hint_count: number;
  hints: string[];
  reveal_after: number;
  attempts: number;
  passed: boolean;
  passed_at: string | null;
  solution_available: boolean;
  solution: string | null;
  latest_attempt: Attempt | null;
};
type Lesson = {
  id: number;
  course_id: number;
  course_title: string;
  course_status: 'draft' | 'published';
  title: string;
  body: string;
  position: number;
  lesson_count: number;
  previous_id: number | null;
  next_id: number | null;
  completed: boolean;
  can_edit: boolean;
  exercises: Exercise[];
};

/** `#courses/{id}`, `#courses/{id}/lessons/{lessonId}` and their `/edit` authoring views. */
export function courseRouteFromHash() {
  const match = window.location.hash.match(
    /^#courses\/(\d+)(?:\/(edit)|\/lessons\/(\d+)(\/edit)?)?$/,
  );
  if (!match) return null;
  return {
    id: Number(match[1]),
    lessonId: match[3] ? Number(match[3]) : undefined,
    edit: !!(match[2] || match[4]),
  };
}

export default function CoursePage({
  id,
  lessonId,
  edit,
  user,
  signIn,
}: {
  id: number;
  lessonId?: number;
  edit: boolean;
  user: User | null;
  signIn: () => void;
}) {
  if (edit && lessonId) return <LessonEditor courseId={id} lessonId={lessonId} />;
  if (edit) return <CourseEditor id={id} />;
  if (lessonId)
    return <LessonPage key={lessonId} courseId={id} lessonId={lessonId} user={user} signIn={signIn} />;
  return <CourseOverview id={id} user={user} signIn={signIn} />;
}

function CourseOverview({
  id,
  user,
  signIn,
}: {
  id: number;
  user: User | null;
  signIn: () => void;
}) {
  const [course, setCourse] = useState<CourseDetail | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    setError('');
    api<CourseDetail>(`/courses/${id}`)
      .then((row) => {
        if (active) setCourse(row);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [id, user?.id]);
  if (error)
    return (
      <section className="course-page">
        <a className="text-button" href="#courses">
          <ArrowLeft size={15} /> All courses
        </a>
        <p role="alert" className="error">
          {error}
        </p>
      </section>
    );
  if (!course) return <p role="status">Loading course…</p>;
  const completed = course.lessons.filter((lesson) => lesson.completed).length;
  const next = course.lessons.find((lesson) => !lesson.completed) || course.lessons[0];
  return (
    <section className="course-page">
      <a className="text-button" href="#courses">
        <ArrowLeft size={15} /> All courses
      </a>
      <header className="course-heading">
        <div>
          <span className="eyebrow">LEARN · {course.difficulty.toUpperCase()}</span>
          <h1>{course.title}</h1>
          <p>{course.summary}</p>
          <div className="pill-row">
            {course.status === 'draft' && (
              <span className="draft-pill">Draft · visible to authors and administrators</span>
            )}
            <span>{course.lesson_count} lessons</span>
            <span>{course.exercise_count} graded exercises</span>
            <span>{course.duration}</span>
            <span>by {course.owner}</span>
          </div>
        </div>
        <div className="course-actions">
          {course.can_edit && (
            <a className="button secondary" href={`#courses/${course.id}/edit`}>
              <Pencil size={15} /> Edit course
            </a>
          )}
          {next && (
            <a className="button" href={`#courses/${course.id}/lessons/${next.id}`}>
              {completed ? 'Continue' : 'Start learning'} <ArrowRight size={16} />
            </a>
          )}
        </div>
      </header>
      {user && course.progress ? (
        <div className="course-progress">
          <div className="progress-track">
            <div style={{ width: `${(completed / (course.lesson_count || 1)) * 100}%` }} />
          </div>
          <p className="muted">
            {completed} of {course.lesson_count} lessons complete ·{' '}
            {course.progress.passed_exercises} of {course.exercise_count} exercises passed
          </p>
          {course.progress.certificate ? (
            <a className="certificate-link" href={`#certificates/${course.progress.certificate}`}>
              <Award size={17} /> View your certificate
            </a>
          ) : (
            course.exercise_count > 0 && (
              <p className="muted">Pass every exercise to earn a certificate.</p>
            )
          )}
        </div>
      ) : (
        !user && (
          <p className="muted">
            <button className="text-button" onClick={signIn}>
              Sign in
            </button>{' '}
            to track progress, check exercises and earn a certificate.
          </p>
        )
      )}
      <ol className="course-lessons">
        {course.lessons.map((lesson, index) => (
          <li key={lesson.id}>
            <a href={`#courses/${course.id}/lessons/${lesson.id}`}>
              <span className={`lesson-number${lesson.completed ? ' done' : ''}`}>
                {lesson.completed ? <Check size={15} aria-label="Completed" /> : index + 1}
              </span>
              <span>
                <strong>{lesson.title}</strong>
                <small>
                  {lesson.exercise_count
                    ? `${lesson.exercise_count} exercise${lesson.exercise_count === 1 ? '' : 's'}`
                    : 'Reading'}
                </small>
              </span>
              <ArrowRight size={16} />
            </a>
          </li>
        ))}
        {!course.lessons.length && <li className="muted">This course has no lessons yet.</li>}
      </ol>
    </section>
  );
}

function LessonPage({
  courseId,
  lessonId,
  user,
  signIn,
}: {
  courseId: number;
  lessonId: number;
  user: User | null;
  signIn: () => void;
}) {
  const [lesson, setLesson] = useState<Lesson | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const usage = useComputeUsage(user?.id || 0);
  useEffect(() => {
    let active = true;
    api<Lesson>(`/courses/${courseId}/lessons/${lessonId}`)
      .then((row) => {
        if (active) setLesson(row);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [courseId, lessonId, user?.id]);
  if (error)
    return (
      <section className="course-page">
        <a className="text-button" href={`#courses/${courseId}`}>
          <ArrowLeft size={15} /> Course
        </a>
        <p role="alert" className="error">
          {error}
        </p>
      </section>
    );
  if (!lesson) return <p role="status">Loading lesson…</p>;
  return (
    <section className="course-page lesson-page">
      <nav className="lesson-breadcrumb" aria-label="Lesson navigation">
        <a className="text-button" href={`#courses/${courseId}`}>
          <ArrowLeft size={15} /> {lesson.course_title}
        </a>
        <span>
          Lesson {lesson.position + 1} of {lesson.lesson_count}
        </span>
      </nav>
      <header className="course-heading">
        <div>
          <span className="eyebrow">LESSON {lesson.position + 1}</span>
          <h1>{lesson.title}</h1>
          {lesson.course_status === 'draft' && <span className="draft-pill">Draft course</span>}
        </div>
        {lesson.can_edit && (
          <a className="button secondary" href={`#courses/${courseId}/lessons/${lessonId}/edit`}>
            <Pencil size={15} /> Edit lesson
          </a>
        )}
      </header>
      <article className="lesson-body">
        <Markdown>{lesson.body || '*This lesson has no text yet.*'}</Markdown>
      </article>
      {lesson.exercises.map((exercise) => (
        <ExercisePanel
          key={exercise.id}
          initial={exercise}
          user={user}
          signIn={signIn}
          gpuAvailable={!!usage?.gpu_available.background}
        />
      ))}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <footer className="lesson-footer">
        {lesson.previous_id ? (
          <a className="button secondary" href={`#courses/${courseId}/lessons/${lesson.previous_id}`}>
            <ArrowLeft size={16} /> Previous
          </a>
        ) : (
          <span />
        )}
        {user ? (
          <button
            className="button secondary"
            disabled={busy || lesson.completed}
            onClick={async () => {
              setBusy(true);
              try {
                await api(`/lessons/${lessonId}/complete`, { method: 'POST' });
                setLesson({ ...lesson, completed: true });
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <Check size={16} /> {lesson.completed ? 'Completed' : 'Mark lesson complete'}
          </button>
        ) : (
          <button className="button secondary" onClick={signIn}>
            Sign in to track progress
          </button>
        )}
        {lesson.next_id ? (
          <a className="button" href={`#courses/${courseId}/lessons/${lesson.next_id}`}>
            Next lesson <ArrowRight size={16} />
          </a>
        ) : (
          <a className="button" href={`#courses/${courseId}`}>
            Back to course <ArrowRight size={16} />
          </a>
        )}
      </footer>
    </section>
  );
}

const attemptLabels: Record<Attempt['status'], string> = {
  queued: 'Queued: waiting for an isolated runtime',
  running: 'Running your code and the checks…',
  passed: 'Passed',
  failed: 'Not yet',
};

function ExercisePanel({
  initial,
  user,
  signIn,
  gpuAvailable,
}: {
  initial: Exercise;
  user: User | null;
  signIn: () => void;
  gpuAvailable: boolean;
}) {
  const [exercise, setExercise] = useState(initial);
  const [code, setCode] = useState(initial.latest_attempt?.code ?? initial.starter_code);
  const [attempt, setAttempt] = useState<Attempt | null>(initial.latest_attempt);
  const [accelerator, setAccelerator] = useState<Accelerator>('cpu');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notebook, setNotebook] = useState(false);
  const pending = attempt?.status === 'queued' || attempt?.status === 'running';
  useEffect(() => {
    if (!attempt || !pending) return;
    let active = true;
    const timer = setTimeout(async () => {
      try {
        const { exercise: updated, ...row } = await api<Attempt & { exercise: Exercise | null }>(
          `/exercise-attempts/${attempt.id}`,
        );
        if (!active) return;
        setAttempt(row);
        if (updated) setExercise(updated);
      } catch (e) {
        if (active) setError((e as Error).message);
      }
    }, 2000);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [attempt, pending]);
  async function act(action: () => Promise<void>) {
    if (!user) {
      signIn();
      return;
    }
    setBusy(true);
    setError('');
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section
      className={`exercise-card${exercise.passed ? ' passed' : ''}`}
      aria-labelledby={`exercise-${exercise.id}`}
    >
      <header>
        <span className="eyebrow">EXERCISE {exercise.position + 1}</span>
        <h2 id={`exercise-${exercise.id}`}>{exercise.title}</h2>
        {exercise.passed && (
          <span className="run-status passed">
            <Check size={13} /> Passed
          </span>
        )}
      </header>
      <Markdown>{exercise.prompt}</Markdown>
      {exercise.inputs.length > 0 && (
        <p className="muted exercise-inputs">
          Data:{' '}
          {exercise.inputs.map((slug) => (
            <code key={slug}>input/{slug}/</code>
          ))}{' '}
          (train.csv and test.csv)
        </p>
      )}
      <div className="exercise-editor">
        <CodeMirror
          aria-label={`Code for ${exercise.title}`}
          value={code}
          extensions={[python()]}
          minHeight="140px"
          editable={!pending}
          onChange={setCode}
          basicSetup={{ foldGutter: false, highlightActiveLine: false }}
        />
      </div>
      <div className="exercise-controls">
        <AcceleratorSelect
          value={accelerator}
          onChange={setAccelerator}
          gpuAvailable={gpuAvailable}
          disabled={busy || pending}
        />
        <button
          className="button"
          disabled={busy || pending || !code.trim()}
          onClick={() =>
            void act(async () => {
              setAttempt(
                await api<Attempt>(`/exercises/${exercise.id}/attempts`, {
                  method: 'POST',
                  body: JSON.stringify({ code, accelerator }),
                }),
              );
            })
          }
        >
          <Play size={15} /> {pending ? 'Checking…' : 'Run checks'}
        </button>
        <button
          className="button secondary"
          disabled={busy || pending}
          onClick={() => setCode(exercise.starter_code)}
        >
          <RotateCcw size={15} /> Reset code
        </button>
        <button
          className="button secondary"
          disabled={busy}
          onClick={() => (user ? setNotebook(true) : signIn())}
        >
          <BookOpen size={15} /> Open in notebook
        </button>
        <InternetOff />
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {attempt && (
        <div className={`exercise-result ${attempt.status}`} role="status" aria-live="polite">
          <strong>{attemptLabels[attempt.status]}</strong>
          {attempt.message && <p>{attempt.message}</p>}
          {attempt.stdout && (
            <details open>
              <summary>Output</summary>
              <pre>{attempt.stdout}</pre>
            </details>
          )}
          {attempt.error && (
            <details open>
              <summary>Error</summary>
              <pre className="cell-error">{attempt.error}</pre>
            </details>
          )}
        </div>
      )}
      <div className="exercise-help">
        {exercise.hints.map((hint, index) => (
          <div key={index} className="exercise-hint">
            <Lightbulb size={15} aria-hidden="true" />
            <div>
              <strong>Hint {index + 1}</strong>
              <Markdown>{hint}</Markdown>
            </div>
          </div>
        ))}
        {exercise.hints.length < exercise.hint_count && (
          <button
            className="text-button"
            disabled={busy}
            onClick={() =>
              void act(async () =>
                setExercise(await api<Exercise>(`/exercises/${exercise.id}/hints`, { method: 'POST' })),
              )
            }
          >
            <Lightbulb size={15} /> Show a hint ({exercise.hint_count - exercise.hints.length} left)
          </button>
        )}
        {exercise.solution_available && exercise.solution !== null ? (
          <details className="exercise-solution">
            <summary>Solution</summary>
            <pre>{exercise.solution}</pre>
          </details>
        ) : (
          <p className="muted">
            {exercise.reveal_after > 0
              ? `The solution unlocks when you pass, or after ${exercise.reveal_after} checked attempts (${exercise.attempts} so far).`
              : 'The solution unlocks when you pass.'}
          </p>
        )}
      </div>
      {notebook && (
        <NewNotebook
          close={() => setNotebook(false)}
          saved={() => {}}
          exerciseId={exercise.id}
          initialTitle={exercise.title}
        />
      )}
    </section>
  );
}
