import { useEffect, useRef, useState, type FormEvent } from 'react';
import { X, ArrowRight, Globe, Sparkles } from 'lucide-react';
import { api } from './api';
import FileUpload from './FileUpload';
const starterCode = 'import pandas as pd\n\n# Upload a CSV in JupyterLab to get started.\n';

export default function CreatePage({
  page,
  close,
  success,
}: {
  page: string;
  close: () => void;
  success: () => void;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [closing, setClosing] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const previous = document.body.style.overflow;
    const returnFocus = document.activeElement as HTMLElement | null;
    const panel = dialog.current;
    panel?.showModal();
    document.body.style.overflow = 'hidden';
    heading.current?.focus();
    return () => {
      clearTimeout(timer.current);
      panel?.close();
      document.body.style.overflow = previous;
      returnFocus?.focus();
    };
  }, []);
  function dismiss(done = close) {
    if (busy || closing) return;
    setClosing(true);
    timer.current = setTimeout(done, 220);
  }
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError('');
    const f = new FormData(e.currentTarget);
    if (page === 'competitions' && f.get('deadline')) {
      f.set('deadline', new Date(String(f.get('deadline'))).toISOString());
    }
    try {
      await api(`/${page}`, {
        method: 'POST',
        body: ['datasets', 'competitions', 'benchmarks'].includes(page)
          ? f
          : JSON.stringify(Object.fromEntries(f)),
      });
      success();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <dialog
      ref={dialog}
      className={`publish-drawer ${closing ? 'closing' : ''}`}
      aria-labelledby="publish-title"
      onCancel={(event) => {
        event.preventDefault();
        dismiss();
      }}
      onClick={(event) => {
        if (event.target !== event.currentTarget) return;
        const rect = event.currentTarget.getBoundingClientRect();
        if (
          event.clientX < rect.left ||
          event.clientX > rect.right ||
          event.clientY < rect.top ||
          event.clientY > rect.bottom
        )
          dismiss();
      }}
    >
      <section className="publish-page">
        <button
          type="button"
          className="icon-button drawer-close"
          aria-label="Close creation panel"
          disabled={busy || closing}
          onClick={() => dismiss()}
        >
          <X size={22} />
        </button>
        <header className="publish-header">
          <div>
            <h1 id="publish-title" ref={heading} tabIndex={-1}>
              {page === 'competitions'
                ? 'Create a competition'
                : page === 'benchmarks'
                  ? 'Create a benchmark'
                  : page === 'datasets'
                    ? 'Share a dataset'
                    : page === 'notebooks'
                      ? 'Create a notebook'
                      : page === 'models'
                        ? 'Publish a model card'
                        : 'Start a discussion'}
            </h1>
            <p>Add your files and tell the community what they can build.</p>
          </div>
          <span className="publish-visibility">
            <Globe size={16} /> Public
          </span>
        </header>
        <div className="publish-layout">
          <form onSubmit={submit} className="publish-form">
            <fieldset disabled={busy}>
              {page === 'datasets' && (
                <FileUpload
                  name="file"
                  label="CSV file"
                  maxMB={10}
                  hint="UTF-8 CSV with unique column names and at least one data row."
                />
              )}
              <h2>Details</h2>
              <label>
                Title
                <input name="title" required minLength={3} maxLength={160} />
              </label>
              <label>
                {page === 'discussions' ? 'Your question or idea' : 'Description'}
                <textarea
                  name={page === 'discussions' ? 'body' : 'description'}
                  required
                  minLength={3}
                  maxLength={5000}
                  rows={3}
                />
              </label>
              {page === 'datasets' && (
                <>
                  <label>
                    Tags
                    <input name="tags" placeholder="tabular, regression" maxLength={300} />
                  </label>
                </>
              )}
              {(page === 'competitions' || page === 'benchmarks') && (
                <>
                  <p className="muted">
                    RMSE scoring: lower is better. Test data is public; answers are kept private.
                    Published evaluation data cannot be changed.
                  </p>
                  <label>
                    Category
                    <input name="category" defaultValue="Regression" required maxLength={80} />
                  </label>
                  {page === 'competitions' && (
                    <>
                      <label>
                        Closing date and time
                        <input name="deadline" type="datetime-local" required />
                        <small>Your local timezone.</small>
                      </label>
                      <label>
                        Prize or recognition
                        <input name="prize" defaultValue="Knowledge" maxLength={80} />
                      </label>
                    </>
                  )}
                  <FileUpload
                    name="test_file"
                    label="Public test CSV"
                    maxMB={10}
                    hint="Include unique id values and feature columns. Participants can download this file."
                  />
                  <FileUpload
                    name="solution_file"
                    label="Private answer CSV"
                    maxMB={1}
                    hint="Exactly id,prediction columns. IDs must match the test file. Answers stay private."
                  />
                </>
              )}
              {(page === 'datasets' || page === 'models') && (
                <label>
                  License
                  <input name="license" defaultValue="CC0-1.0" required maxLength={80} />
                </label>
              )}
              {page === 'models' && (
                <>
                  <label>
                    Framework
                    <input
                      name="framework"
                      placeholder="PyTorch, scikit-learn…"
                      required
                      maxLength={80}
                    />
                  </label>
                  <label>
                    Model or documentation URL
                    <input name="url" type="url" placeholder="https://…" required />
                  </label>
                  <small>This publishes metadata and a link, not a hosted model.</small>
                </>
              )}
              {page === 'notebooks' && (
                <label>
                  Python code
                  <textarea
                    className="code-editor"
                    name="code"
                    defaultValue={starterCode}
                    rows={8}
                    maxLength={100000}
                  />
                </label>
              )}
              {error && (
                <p className="error" role="alert">
                  {error}
                </p>
              )}
              <div className="publish-actions">
                <button
                  type="button"
                  className="button secondary"
                  disabled={busy}
                  onClick={() => dismiss()}
                >
                  Cancel
                </button>
                <button className="button" disabled={busy}>
                  {busy ? 'Publishing…' : 'Publish'}
                  <ArrowRight size={16} />
                </button>
              </div>
            </fieldset>
          </form>
          <aside className="publish-help">
            <Sparkles size={24} />
            <h2>Make it useful.</h2>
            <p>
              A great upload starts with a clear story. Explain what the data represents and how
              someone can use it.
            </p>
            <hr />
            <h3>Before publishing</h3>
            <ul>
              <li>Use a descriptive, searchable title.</li>
              <li>Explain the columns and the source.</li>
              <li>Choose a license you can share under.</li>
            </ul>
            <div className="publish-note">
              <Globe size={18} />
              <p>
                Your published entry is visible to everyone. Challenge answers are kept private.
              </p>
            </div>
          </aside>
        </div>
      </section>
    </dialog>
  );
}
