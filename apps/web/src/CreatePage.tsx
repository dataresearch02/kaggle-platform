import { useEffect, useRef, useState, type FormEvent } from 'react';
import { X, ArrowRight, Globe, Sparkles, UploadCloud } from 'lucide-react';
import {
  api,
  formatBytes,
  FRAMEWORKS,
  type Item,
  type MetricInfo,
  type VersionInfo,
} from './api';
import FileUpload from './FileUpload';
import StorageMeter from './StorageMeter';
import { uploadFile } from './chunkedUpload';
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
  const [metrics, setMetrics] = useState<MetricInfo[]>([]);
  const [metric, setMetric] = useState('RMSE');
  // Datasets: files upload in resumable chunks into the new dataset's first version.
  const [files, setFiles] = useState<File[]>([]);
  const [progress, setProgress] = useState<{ index: number; sent: number } | null>(null);
  const created = useRef<{ id: number; versionId: number } | null>(null);
  const uploads = useRef<AbortController | null>(null);
  const challenge = page === 'competitions' || page === 'benchmarks';
  useEffect(() => {
    if (!challenge) return;
    let active = true;
    api<MetricInfo[]>('/metrics')
      .then((rows) => {
        if (active) setMetrics(rows);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [challenge]);
  const selectedMetric = metrics.find((row) => row.name === metric);
  useEffect(() => {
    const previous = document.body.style.overflow;
    const returnFocus = document.activeElement as HTMLElement | null;
    const panel = dialog.current;
    panel?.showModal();
    document.body.style.overflow = 'hidden';
    heading.current?.focus();
    return () => {
      clearTimeout(timer.current);
      uploads.current?.abort();
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
  async function createDataset(form: FormData) {
    if (!files.length) throw new Error('Choose at least one file to upload.');
    if (!created.current) {
      const dataset = await api<Item & { draft_version: VersionInfo }>('/datasets/drafts', {
        method: 'POST',
        body: JSON.stringify({
          title: form.get('title'),
          description: form.get('description'),
          tags: form.get('tags') || '',
          license: form.get('license') || 'CC0-1.0',
        }),
      });
      created.current = { id: dataset.id, versionId: dataset.draft_version.id };
    }
    const { id, versionId } = created.current;
    uploads.current = new AbortController();
    for (const [index, file] of files.entries()) {
      setProgress({ index, sent: 0 });
      // Uploading the same file again resumes or replaces it in the draft.
      await uploadFile(file, versionId, file.webkitRelativePath || file.name, {
        signal: uploads.current.signal,
        onProgress: (sent) => setProgress({ index, sent }),
      });
    }
    await api(`/datasets/${id}/versions/draft/publish`, {
      method: 'POST',
      body: JSON.stringify({ note: 'Initial version' }),
    });
    success();
  }
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError('');
    const f = new FormData(e.currentTarget);
    if (page === 'models' && !f.get('url')) f.delete('url');
    for (const name of ['metric_k', 'public_fraction', 'max_daily_submissions', 'rules']) {
      if (f.get(name) === '') f.delete(name);
    }
    if (page === 'competitions' && f.get('deadline')) {
      f.set('deadline', new Date(String(f.get('deadline'))).toISOString());
    }
    try {
      if (page === 'datasets') await createDataset(f);
      else {
        await api(`/${page}`, {
          method: 'POST',
          body: ['competitions', 'benchmarks'].includes(page)
            ? f
            : JSON.stringify(Object.fromEntries(f)),
        });
        success();
      }
    } catch (e) {
      const message = (e as Error).message;
      setError(
        created.current
          ? `${message} The dataset is saved as a private draft: publish again to resume the upload, or finish it from the dataset page in Your Work.`
          : message,
      );
    } finally {
      setBusy(false);
      setProgress(null);
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
                <section className="upload-section">
                  <h2>Files</h2>
                  <p>
                    CSV, JSON, text, images, NumPy arrays, archives or any other files. Large files
                    upload in resumable chunks. The dataset is saved privately as version 1; use its
                    visibility settings to publish or invite readers.
                  </p>
                  <div
                    className="upload-drop"
                    onDragOver={(event) => event.preventDefault()}
                    onDrop={(event) => {
                      event.preventDefault();
                      const dropped = Array.from(event.dataTransfer.files);
                      if (!busy) setFiles((old) => [...old, ...dropped]);
                    }}
                  >
                    <UploadCloud size={38} strokeWidth={1.3} />
                    <strong>Drag and drop files here</strong>
                    <span>or choose files from your computer</span>
                    <label className="button secondary upload-browse">
                      Browse files
                      <input
                        type="file"
                        multiple
                        aria-label="Dataset files"
                        onChange={(event) => {
                          const chosen = Array.from(event.currentTarget.files || []);
                          setFiles((old) => [...old, ...chosen]);
                          event.currentTarget.value = '';
                        }}
                      />
                    </label>
                  </div>
                  {files.length > 0 && (
                    <ul className="upload-rows">
                      {files.map((file, index) => (
                        <li key={`${file.name}-${file.size}-${index}`}>
                          <div className="upload-row-heading">
                            <strong>{file.webkitRelativePath || file.name}</strong>
                            <span>
                              {formatBytes(file.size)}
                              <button
                                type="button"
                                className="icon-button"
                                aria-label={`Remove ${file.name}`}
                                onClick={() =>
                                  setFiles((old) => old.filter((_, position) => position !== index))
                                }
                              >
                                <X size={16} />
                              </button>
                            </span>
                          </div>
                          {progress && progress.index >= index && (
                            <div
                              className="gpu-meter-track"
                              role="progressbar"
                              aria-label={`Upload progress for ${file.name}`}
                              aria-valuemin={0}
                              aria-valuemax={100}
                              aria-valuenow={
                                progress.index > index
                                  ? 100
                                  : Math.floor((progress.sent / (file.size || 1)) * 100)
                              }
                            >
                              <div
                                style={{
                                  width: `${progress.index > index ? 100 : (progress.sent / (file.size || 1)) * 100}%`,
                                }}
                              />
                            </div>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                  <StorageMeter compact />
                </section>
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
                    Select a scoring metric. Test features are available to participants; answers
                    stay private. Published evaluation data cannot be changed.
                  </p>
                  <label>
                    Evaluation metric
                    <select
                      name="metric"
                      value={metric}
                      onChange={(event) => setMetric(event.target.value)}
                    >
                      {(metrics.length
                        ? metrics
                        : [{ name: 'RMSE', title: 'Root mean squared error', direction: 'lower' }]
                      ).map((row) => (
                        <option key={row.name} value={row.name}>
                          {row.title} — {row.direction} is better
                        </option>
                      ))}
                    </select>
                    {selectedMetric && (
                      <small>
                        {selectedMetric.input}. Formula: <code>{selectedMetric.formula}</code>
                      </small>
                    )}
                  </label>
                  {selectedMetric?.uses_k && (
                    <label>
                      K (predictions counted per row)
                      <input name="metric_k" type="number" min={1} max={100} defaultValue={5} />
                    </label>
                  )}
                  <label>
                    Public leaderboard fraction (optional)
                    <input
                      name="public_fraction"
                      type="number"
                      min={0.01}
                      max={0.99}
                      step={0.01}
                      placeholder="All rows public"
                    />
                    <small>
                      Used when the answer CSV has no Usage column: rows are assigned to the public
                      or private leaderboard deterministically.
                    </small>
                  </label>
                  <label>
                    Daily submissions per team or participant (optional)
                    <input
                      name="max_daily_submissions"
                      type="number"
                      min={1}
                      max={100}
                      placeholder={page === 'competitions' ? '5' : '20'}
                    />
                  </label>
                  <label>
                    Rules (Markdown, optional)
                    <textarea name="rules" rows={4} maxLength={50000} />
                    <small>Participants accept these rules when they join.</small>
                  </label>
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
                    hint="id,prediction columns, optionally followed by Usage (Public or Private). IDs must match the test file. Answers stay private."
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
                    <select name="framework" required defaultValue="PyTorch">
                      {FRAMEWORKS.map((framework) => (
                        <option key={framework.value} value={framework.label}>
                          {framework.label}
                        </option>
                      ))}
                    </select>
                    <small>
                      The first variation uses this framework. Add variations such as "base" or
                      "small" on the model page.
                    </small>
                  </label>
                  <label>
                    Model or documentation URL (optional)
                    <input
                      name="url"
                      type="url"
                      placeholder="https://…"
                      aria-describedby="model-url-hint"
                    />
                  </label>
                  <small id="model-url-hint">
                    This link is shown as an external reference. It will not be reachable from an
                    offline installation.
                  </small>
                  <small>
                    The card starts from a template with Overview, Intended use, Training data,
                    Evaluation, Limitations &amp; bias, License and How to use. Upload versioned
                    files from the model page.
                  </small>
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
                  {busy ? (progress ? 'Uploading…' : 'Publishing…') : 'Publish'}
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
