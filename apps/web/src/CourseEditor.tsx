import { useEffect, useState } from 'react';
import { ArrowDown, ArrowLeft, ArrowUp, Eye, Plus, Trash2 } from 'lucide-react';
import { api } from './api';
import type { CourseDetail } from './CoursePages';
import Markdown from './Markdown';

type ExerciseSource = {
  id: number;
  position: number;
  title: string;
  prompt: string;
  starter_code: string;
  hints: string[];
  solution: string;
  checker: string;
  reveal_after: number;
  inputs: string[];
  updated_at: string | null;
};
type ExerciseInput = Omit<ExerciseSource, 'id' | 'position' | 'updated_at'>;
type LessonSource = {
  id: number;
  course_id: number;
  course_title: string;
  title: string;
  body: string;
  exercises: ExerciseSource[];
};
type PracticeInput = { slug: string; title: string };

const TEMPLATE: ExerciseInput = {
  title: 'New exercise',
  prompt: 'Set `answer` to 42.',
  starter_code: 'answer = None\n',
  hints: ['Multiply 6 by 7.'],
  solution: 'answer = 6 * 7\n',
  checker: "assert answer == 42, 'answer should be 42.'\narena_pass('Correct!')\n",
  reveal_after: 3,
  inputs: [],
};

function useActions() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  async function run(action: () => Promise<void>, message: string) {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await action();
      setNotice(message);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const messages = (
    <>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="success">
          {notice}
        </p>
      )}
    </>
  );
  return { busy, run, messages, setError };
}

function moved(ids: number[], index: number, offset: number) {
  const next = [...ids];
  const [item] = next.splice(index, 1);
  next.splice(index + offset, 0, item);
  return next;
}

/** `#courses/{id}/edit`: details, publication and lesson order. */
export default function CourseEditor({ id }: { id: number }) {
  const [course, setCourse] = useState<CourseDetail | null>(null);
  const [lessonTitle, setLessonTitle] = useState('');
  const { busy, run, messages, setError } = useActions();
  useEffect(() => {
    let active = true;
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
  }, [id]);
  if (!course) return <section className="course-page">{messages}</section>;
  if (!course.can_edit)
    return (
      <section className="course-page">
        <p>Only the course author or an administrator can edit this course.</p>
      </section>
    );
  return (
    <section className="course-page course-editor">
      <a className="text-button" href={`#courses/${id}`}>
        <ArrowLeft size={15} /> View course
      </a>
      <header className="course-heading">
        <div>
          <span className="eyebrow">COURSE AUTHORING</span>
          <h1>{course.title}</h1>
          <div className="pill-row">
            <span className={course.status === 'draft' ? 'draft-pill' : undefined}>
              {course.status === 'draft'
                ? 'Draft · visible to authors and administrators'
                : 'Published'}
            </span>
          </div>
        </div>
        <div className="course-actions">
          {course.status === 'draft' ? (
            <button
              className="button"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  setCourse(await api<CourseDetail>(`/courses/${id}/publish`, { method: 'POST' }));
                }, 'Course published')
              }
            >
              Publish
            </button>
          ) : (
            <button
              className="button secondary"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  setCourse(
                    await api<CourseDetail>(`/courses/${id}/unpublish`, { method: 'POST' }),
                  );
                }, 'Course unpublished; learners no longer see it')
              }
            >
              Unpublish
            </button>
          )}
          {course.status === 'draft' && (
            <button
              className="button danger"
              disabled={busy}
              onClick={() => {
                if (
                  window.confirm(
                    'Delete this draft course with its lessons, exercises and learner progress?',
                  )
                )
                  void run(async () => {
                    await api(`/courses/${id}`, { method: 'DELETE' });
                    window.location.hash = 'courses';
                  }, 'Course deleted');
              }}
            >
              <Trash2 size={15} /> Delete
            </button>
          )}
        </div>
      </header>
      {messages}
      <form
        className="account-card account-form"
        onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          void run(async () => {
            setCourse(
              await api<CourseDetail>(`/courses/${id}`, {
                method: 'PUT',
                body: JSON.stringify({
                  title: data.get('title'),
                  summary: data.get('summary'),
                  difficulty: data.get('difficulty'),
                  duration: data.get('duration'),
                }),
              }),
            );
          }, 'Course details saved');
        }}
      >
        <h2>Details</h2>
        <label>
          Title
          <input name="title" required minLength={3} maxLength={160} defaultValue={course.title} />
        </label>
        <label>
          Summary
          <textarea
            name="summary"
            required
            minLength={3}
            maxLength={2000}
            rows={3}
            defaultValue={course.summary}
          />
        </label>
        <label>
          Difficulty
          <select name="difficulty" defaultValue={course.difficulty}>
            <option value="beginner">Beginner</option>
            <option value="intermediate">Intermediate</option>
            <option value="advanced">Advanced</option>
          </select>
        </label>
        <label>
          Duration
          <input name="duration" maxLength={40} defaultValue={course.duration} placeholder="45 min" />
        </label>
        <div className="form-actions">
          <button className="button" disabled={busy}>
            Save details
          </button>
        </div>
      </form>
      <section className="account-card">
        <h2>Lessons</h2>
        <ol className="course-editor-list">
          {course.lessons.map((lesson, index) => (
            <li key={lesson.id}>
              <span>
                {lesson.title}
                <small> · {lesson.exercise_count} exercises</small>
              </span>
              <span className="course-editor-actions">
                <button
                  aria-label={`Move ${lesson.title} up`}
                  disabled={busy || index === 0}
                  onClick={() =>
                    void run(async () => {
                      setCourse(
                        await api<CourseDetail>(`/courses/${id}/lessons/order`, {
                          method: 'PUT',
                          body: JSON.stringify({
                            ids: moved(course.lessons.map((row) => row.id), index, -1),
                          }),
                        }),
                      );
                    }, 'Lesson order saved')
                  }
                >
                  <ArrowUp size={15} />
                </button>
                <button
                  aria-label={`Move ${lesson.title} down`}
                  disabled={busy || index === course.lessons.length - 1}
                  onClick={() =>
                    void run(async () => {
                      setCourse(
                        await api<CourseDetail>(`/courses/${id}/lessons/order`, {
                          method: 'PUT',
                          body: JSON.stringify({
                            ids: moved(course.lessons.map((row) => row.id), index, 1),
                          }),
                        }),
                      );
                    }, 'Lesson order saved')
                  }
                >
                  <ArrowDown size={15} />
                </button>
                <a className="text-button" href={`#courses/${id}/lessons/${lesson.id}/edit`}>
                  Edit
                </a>
                <button
                  className="text-button danger-text"
                  disabled={busy}
                  onClick={() => {
                    if (window.confirm(`Delete “${lesson.title}” with its exercises and attempts?`))
                      void run(async () => {
                        await api(`/courses/${id}/lessons/${lesson.id}`, { method: 'DELETE' });
                        setCourse(await api<CourseDetail>(`/courses/${id}`));
                      }, 'Lesson deleted');
                  }}
                >
                  Delete
                </button>
              </span>
            </li>
          ))}
        </ol>
        {!course.lessons.length && <p className="muted">Add a lesson before publishing.</p>}
        <form
          className="course-editor-add"
          onSubmit={(event) => {
            event.preventDefault();
            void run(async () => {
              const lesson = await api<{ id: number }>(`/courses/${id}/lessons`, {
                method: 'POST',
                body: JSON.stringify({ title: lessonTitle, body: '' }),
              });
              setLessonTitle('');
              window.location.hash = `courses/${id}/lessons/${lesson.id}/edit`;
            }, 'Lesson added');
          }}
        >
          <label>
            New lesson title
            <input
              required
              maxLength={160}
              value={lessonTitle}
              onChange={(event) => setLessonTitle(event.target.value)}
            />
          </label>
          <button className="button secondary" disabled={busy}>
            <Plus size={15} /> Add lesson
          </button>
        </form>
      </section>
    </section>
  );
}

/** `#courses/{id}/lessons/{lessonId}/edit`: Markdown body and graded exercises. */
export function LessonEditor({ courseId, lessonId }: { courseId: number; lessonId: number }) {
  const [lesson, setLesson] = useState<LessonSource | null>(null);
  const [practice, setPractice] = useState<PracticeInput[]>([]);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [preview, setPreview] = useState(false);
  const { busy, run, messages, setError } = useActions();
  const path = `/courses/${courseId}/lessons/${lessonId}`;
  async function reload() {
    const row = await api<LessonSource>(`${path}/source`);
    setLesson(row);
    return row;
  }
  useEffect(() => {
    let active = true;
    Promise.all([api<LessonSource>(`${path}/source`), api<PracticeInput[]>('/learn/practice-inputs')])
      .then(([row, inputs]) => {
        if (!active) return;
        setLesson(row);
        setTitle(row.title);
        setBody(row.body);
        setPractice(inputs);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [path]);
  if (!lesson) return <section className="course-page">{messages}</section>;
  const order = (index: number, offset: number) =>
    run(async () => {
      await api(`${path}/exercises/order`, {
        method: 'PUT',
        body: JSON.stringify({
          ids: moved(lesson.exercises.map((row) => row.id), index, offset),
        }),
      });
      await reload();
    }, 'Exercise order saved');
  return (
    <section className="course-page course-editor">
      <a className="text-button" href={`#courses/${courseId}/edit`}>
        <ArrowLeft size={15} /> {lesson.course_title}
      </a>
      <header className="course-heading">
        <div>
          <span className="eyebrow">LESSON AUTHORING</span>
          <h1>{lesson.title}</h1>
        </div>
        <a className="button secondary" href={`#courses/${courseId}/lessons/${lessonId}`}>
          <Eye size={15} /> View lesson
        </a>
      </header>
      {messages}
      <form
        className="account-card account-form"
        onSubmit={(event) => {
          event.preventDefault();
          void run(async () => {
            await api(path, { method: 'PUT', body: JSON.stringify({ title, body }) });
            await reload();
          }, 'Lesson saved');
        }}
      >
        <label>
          Title
          <input
            required
            maxLength={160}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
        </label>
        <div className="lesson-editor-tabs" role="group" aria-label="Lesson body view">
          <button type="button" aria-pressed={!preview} onClick={() => setPreview(false)}>
            Write
          </button>
          <button type="button" aria-pressed={preview} onClick={() => setPreview(true)}>
            Preview
          </button>
        </div>
        {preview ? (
          <div className="lesson-body">
            <Markdown>{body || '*Nothing to preview yet.*'}</Markdown>
          </div>
        ) : (
          <label>
            Lesson (Markdown)
            <textarea
              className="code-editor"
              rows={14}
              maxLength={100000}
              value={body}
              onChange={(event) => setBody(event.target.value)}
            />
          </label>
        )}
        <div className="form-actions">
          <button className="button" disabled={busy}>
            Save lesson
          </button>
        </div>
      </form>
      <section className="account-card">
        <h2>Exercises</h2>
        <p className="muted">
          The checker runs after the learner’s code in the same fresh kernel, with the learner’s
          variables available. Fail with <code>assert condition, "message"</code> or{' '}
          <code>arena_fail("message")</code>; pass with <code>arena_pass("message")</code> or by
          finishing without an error. Learners never see the checker. Practice datasets are copied
          to <code>input/&lt;dataset&gt;/</code>.
        </p>
        {lesson.exercises.map((exercise, index) => (
          <ExerciseForm
            key={`${exercise.id}-${exercise.updated_at}`}
            exercise={exercise}
            practice={practice}
            busy={busy}
            first={index === 0}
            last={index === lesson.exercises.length - 1}
            save={(data) =>
              run(async () => {
                await api(`/exercises/${exercise.id}`, { method: 'PUT', body: JSON.stringify(data) });
                await reload();
              }, 'Exercise saved')
            }
            remove={() => {
              if (window.confirm(`Delete “${exercise.title}” and its learner attempts?`))
                void run(async () => {
                  await api(`/exercises/${exercise.id}`, { method: 'DELETE' });
                  await reload();
                }, 'Exercise deleted');
            }}
            move={(offset) => void order(index, offset)}
          />
        ))}
        <button
          className="button secondary"
          disabled={busy}
          onClick={() =>
            void run(async () => {
              await api(`${path}/exercises`, { method: 'POST', body: JSON.stringify(TEMPLATE) });
              await reload();
            }, 'Exercise added')
          }
        >
          <Plus size={15} /> Add exercise
        </button>
      </section>
    </section>
  );
}

function ExerciseForm({
  exercise,
  practice,
  busy,
  first,
  last,
  save,
  remove,
  move,
}: {
  exercise: ExerciseSource;
  practice: PracticeInput[];
  busy: boolean;
  first: boolean;
  last: boolean;
  save: (data: ExerciseInput) => Promise<void>;
  remove: () => void;
  move: (offset: number) => void;
}) {
  return (
    <details className="exercise-form" open={exercise.title === TEMPLATE.title}>
      <summary>
        {exercise.position + 1}. {exercise.title}
      </summary>
      <form
        className="account-form"
        onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          const text = (name: string) => String(data.get(name) || '');
          void save({
            title: text('title'),
            prompt: text('prompt'),
            starter_code: text('starter_code'),
            hints: text('hints')
              .split('\n')
              .map((hint) => hint.trim())
              .filter(Boolean),
            solution: text('solution'),
            checker: text('checker'),
            reveal_after: Number(text('reveal_after')),
            inputs: data.getAll('inputs').map(String),
          });
        }}
      >
        <label>
          Title
          <input name="title" required minLength={3} maxLength={160} defaultValue={exercise.title} />
        </label>
        <label>
          Prompt (Markdown)
          <textarea name="prompt" rows={4} required defaultValue={exercise.prompt} />
        </label>
        <label>
          Starter code
          <textarea
            className="code-editor"
            name="starter_code"
            rows={6}
            defaultValue={exercise.starter_code}
          />
        </label>
        <label>
          Hints, one per line, revealed in order
          <textarea name="hints" rows={3} defaultValue={exercise.hints.join('\n')} />
        </label>
        <label>
          Solution
          <textarea
            className="code-editor"
            name="solution"
            rows={6}
            required
            defaultValue={exercise.solution}
          />
        </label>
        <label>
          Hidden checker
          <textarea
            className="code-editor"
            name="checker"
            rows={8}
            required
            defaultValue={exercise.checker}
          />
        </label>
        <label>
          Reveal the solution after this many checked attempts (0: only after passing)
          <input
            name="reveal_after"
            type="number"
            min={0}
            max={100}
            required
            defaultValue={exercise.reveal_after}
          />
        </label>
        <fieldset>
          <legend>Practice datasets</legend>
          {practice.map((item) => (
            <label key={item.slug} className="checkbox-label">
              <input
                type="checkbox"
                name="inputs"
                value={item.slug}
                defaultChecked={exercise.inputs.includes(item.slug)}
              />{' '}
              {item.title} <code>input/{item.slug}/</code>
            </label>
          ))}
        </fieldset>
        <div className="form-actions">
          <button className="button" disabled={busy}>
            Save exercise
          </button>
          <button
            type="button"
            className="button secondary"
            aria-label={`Move ${exercise.title} up`}
            disabled={busy || first}
            onClick={() => move(-1)}
          >
            <ArrowUp size={15} />
          </button>
          <button
            type="button"
            className="button secondary"
            aria-label={`Move ${exercise.title} down`}
            disabled={busy || last}
            onClick={() => move(1)}
          >
            <ArrowDown size={15} />
          </button>
          <button type="button" className="text-button danger-text" disabled={busy} onClick={remove}>
            Delete
          </button>
        </div>
      </form>
    </details>
  );
}
