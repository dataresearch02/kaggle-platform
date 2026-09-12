import { useEffect, useState } from 'react';
import {
  Boxes,
  ChevronRight,
  Download,
  FileText,
  Plus,
  Upload,
  X,
  Trophy,
  BookOpen,
  Database,
  Table2,
} from 'lucide-react';
import { api, type Item } from './api';

export type InputFile = {
  id: number;
  kind?: string;
  filename: string;
  path: string;
  size?: number;
  sha256?: string;
};
export type Input = {
  id: number;
  title: string;
  filename?: string;
  kind?: 'notebook-output' | 'dataset' | 'competition' | 'notebook' | 'model';
  files?: InputFile[];
  path?: string;
};
export default function NotebookPanel({
  inputs,
  attach,
  remove,
  preview,
  headings,
  jump,
  ready,
  notebookId,
  draft,
  cellCount,
  outputCount,
  close,
  revision = 0,
}: {
  revision?: number;
  inputs: Input[];
  attach: (item: Input) => Promise<void>;
  remove: (item: Input) => Promise<void>;
  preview: (source: Input, file: InputFile) => void;
  headings: { id: string; title: string; level: number }[];
  jump: (id: string) => void;
  ready: boolean;
  notebookId: number;
  draft: boolean;
  cellCount: number;
  outputCount: number;
  close: () => void;
}) {
  const [source, setSource] = useState<'dataset' | 'competition' | 'notebook' | 'model'>(
    'competition',
  );
  const [runtime, setRuntime] = useState<{
    gpu_count: number;
    gpu_resource: string;
    cell_timeout_seconds: number;
  } | null>(null);
  useEffect(() => {
    let active = true;
    api<{ gpu_count: number; gpu_resource: string; cell_timeout_seconds: number }>(
      '/notebook-runtime',
    )
      .then((value) => {
        if (active) setRuntime(value);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);
  const [items, setItems] = useState<Input[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [savedOutputs, setSavedOutputs] = useState<Input[]>([]);
  const [collapsedInputs, setCollapsedInputs] = useState<Set<string>>(new Set());
  const [picker, setPicker] = useState(false);
  const [upload, setUpload] = useState(false);
  const [query, setQuery] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    if (notebookId > 0)
      api<{ items: Input[] }>(`/notebook-outputs?notebook_id=${notebookId}`)
        .then((result) => {
          if (active) setSavedOutputs(result.items);
        })
        .catch(() => {
          if (active) setError('Could not load saved output files.');
        });
    return () => {
      active = false;
    };
  }, [notebookId, revision]);
  async function browse(kind = source, before?: number) {
    setPicker(true);
    setSource(kind);
    setBusy(true);
    setError('');
    try {
      const result = await api<{ items: Input[]; next_cursor: number | null }>(
        `/input-sources?kind=${kind}&q=${encodeURIComponent(query)}${before ? `&before=${before}` : ''}`,
      );
      setItems((old) => (before ? [...old, ...result.items] : result.items));
      setNext(result.next_cursor);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function selectInput(item: Input) {
    setBusy(true);
    setError('');
    try {
      await attach(item);
      setPicker(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function publish(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const item = await api<Item>('/datasets', {
        method: 'POST',
        body: new FormData(event.currentTarget),
      });
      await attach(item);
      setUpload(false);
      setPicker(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <aside className="notebook-panel" aria-label="Notebook panel">
      <header className="notebook-panel-heading">
        <h2>Notebook</h2>
        <button aria-label="Close notebook panel" title="Close notebook panel" onClick={close}>
          <X size={20} />
        </button>
      </header>
      <details open className="notebook-input-section">
        <summary>Input</summary>
        <div className="notebook-input-actions">
          <button disabled={!ready} onClick={() => void browse()}>
            <Plus size={16} /> Add Input
          </button>
          <button
            disabled={!ready}
            onClick={() => {
              setUpload(true);
              setError('');
            }}
          >
            <Upload size={16} /> Upload
          </button>
        </div>
        {inputs.length ? (
          <div className="notebook-inputs">
            {(['competition', 'notebook', 'dataset', 'model'] as const).map((kind) => {
              const sources = inputs.filter(
                (item) =>
                  (item.kind === 'notebook-output' ? 'notebook' : item.kind || 'dataset') === kind,
              );
              if (!sources.length) return null;
              const Icon =
                kind === 'competition' ? Trophy : kind === 'notebook' ? BookOpen : Database;
              return (
                <section className="notebook-input-group" key={kind} aria-label={`${kind} inputs`}>
                  <h3>
                    {kind === 'competition'
                      ? 'Competitions'
                      : kind === 'notebook'
                        ? 'Notebooks'
                        : kind === 'model'
                          ? 'Models'
                          : 'Datasets'}
                  </h3>
                  {sources.map((item) => {
                    const key = `${item.kind || 'dataset'}-${item.id}`;
                    const expanded = !collapsedInputs.has(key);
                    const files = item.files || [
                      {
                        id: item.id,
                        filename: item.filename || 'Dataset file',
                        path: item.path || `arena-input-${item.id}.csv`,
                      },
                    ];
                    return (
                      <div className="notebook-input-source" key={key}>
                        <div className="notebook-input-source-row">
                          <button
                            className="notebook-input-source-toggle"
                            aria-expanded={expanded}
                            aria-controls={`input-files-${key}`}
                            title={item.path || item.title}
                            onClick={() =>
                              setCollapsedInputs((previous) => {
                                const next = new Set(previous);
                                if (next.has(key)) next.delete(key);
                                else next.add(key);
                                return next;
                              })
                            }
                          >
                            <ChevronRight size={14} className="notebook-input-chevron" />
                            <span className={`notebook-input-source-icon ${kind}`}>
                              <Icon size={17} />
                            </span>
                            <span className="notebook-input-source-title">{item.title}</span>
                          </button>
                          <button
                            className="notebook-input-remove"
                            title={`Remove ${item.title}`}
                            aria-label={`Remove ${item.title}`}
                            disabled={busy || !ready}
                            onClick={async () => {
                              setBusy(true);
                              setError('');
                              try {
                                await remove(item);
                              } catch (e) {
                                setError((e as Error).message);
                              } finally {
                                setBusy(false);
                              }
                            }}
                          >
                            <X size={15} />
                          </button>
                        </div>
                        <ul
                          id={`input-files-${key}`}
                          className="notebook-input-files"
                          hidden={!expanded}
                        >
                          {[...files]
                            .sort((a, b) => a.filename.localeCompare(b.filename))
                            .map((file) => (
                              <li key={`${file.kind || item.kind}-${file.id}`} title={file.path}>
                                <button
                                  className="notebook-input-file-button"
                                  onClick={() => preview(item, file)}
                                >
                                  {/\.(csv|tsv|parquet|xlsx?)$/i.test(file.filename) ? (
                                    <Table2 size={18} />
                                  ) : (
                                    <FileText size={18} />
                                  )}
                                  <span>{file.filename}</span>
                                </button>
                              </li>
                            ))}
                        </ul>
                      </div>
                    );
                  })}
                </section>
              );
            })}
          </div>
        ) : (
          <div className="notebook-input-empty">
            <div className="notebook-cubes">
              <Boxes size={104} strokeWidth={1.5} />
            </div>
            <h3>No input attached</h3>
            <p>Attach all input files from a competition, notebook, dataset, or model</p>
          </div>
        )}
      </details>
      <details open>
        <summary>Output</summary>
        <div className="notebook-output-summary">
          <ChevronRight size={14} />
          <FileText size={18} />
          <span>Notebook outputs</span>
          <span>{outputCount}</span>
        </div>
        <p className="notebook-panel-note">
          Saving a notebook version includes generated files from its working folder. Those files
          are available directly through Add Input → Notebooks.
        </p>
        <button
          disabled={!ready || !notebookId || busy}
          onClick={async () => {
            setBusy(true);
            setError('');
            try {
              setSavedOutputs(
                (await api<{ items: Input[] }>(`/notebook-outputs?notebook_id=${notebookId}`))
                  .items,
              );
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          Refresh output files
        </button>
        {savedOutputs.map((output) => (
          <p key={output.id}>
            <a href={`/api/notebook-outputs/${output.id}/download`}>{output.filename}</a> · saved
            output #{output.id}
          </p>
        ))}
        {error && !picker && !upload && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        {!draft && ready && (
          <a
            className="notebook-output-download"
            href={`/api/notebooks/${notebookId}/working-copy`}
          >
            <Download size={14} /> Download saved notebook
          </a>
        )}
      </details>
      <details open>
        <summary>Table of contents</summary>
        <nav className="notebook-outline" aria-label="Notebook headings">
          {headings.length ? (
            headings.map((h) => (
              <button
                key={h.id}
                style={{ paddingLeft: `${12 + (h.level - 1) * 12}px` }}
                onClick={() => jump(h.id)}
              >
                {h.title}
              </button>
            ))
          ) : (
            <p>Add Markdown headings to outline your notebook.</p>
          )}
        </nav>
      </details>
      <details>
        <summary>Session options</summary>
        <dl>
          <dt>Language</dt>
          <dd>Python 3</dd>
          <dt>Accelerator</dt>
          <dd>
            {runtime
              ? runtime.gpu_count
                ? `${runtime.gpu_resource.startsWith('nvidia.') ? 'NVIDIA GPU' : 'GPU'} × ${runtime.gpu_count} (configured)`
                : 'CPU'
              : 'Unavailable'}
          </dd>
          <dt>Notebook</dt>
          <dd>{cellCount} cells</dd>
          <dt>Execution limit</dt>
          <dd>
            {runtime
              ? `${Math.ceil(runtime.cell_timeout_seconds / 60)} minutes / request`
              : 'Unavailable'}
          </dd>
        </dl>
      </details>
      <details>
        <summary>Schedule a notebook to run</summary>
        <p className="notebook-panel-note">
          Scheduled runs are not available yet. Use Run All to execute this notebook now.
        </p>
      </details>
      {(picker || upload) && (
        <div
          className="notebook-input-picker"
          role="dialog"
          aria-label={upload ? 'Upload dataset' : 'Add notebook input'}
        >
          <header>
            <h3>{upload ? 'Upload dataset' : 'Add Input'}</h3>
            <button
              aria-label="Close input panel"
              disabled={busy}
              onClick={() => {
                setPicker(false);
                setUpload(false);
              }}
            >
              <X size={18} />
            </button>
          </header>
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          {upload ? (
            <form onSubmit={(event) => void publish(event)}>
              <p>
                This saves a private CSV dataset and adds a Python loader cell to this notebook.
              </p>
              <label>
                Dataset title
                <input name="title" required minLength={3} maxLength={160} />
              </label>
              <label>
                Description
                <textarea name="description" required minLength={3} maxLength={5000} />
              </label>
              <label>
                CSV file
                <input name="file" type="file" accept=".csv" required />
              </label>
              <button type="submit" disabled={busy}>
                {busy ? 'Uploading…' : 'Upload and attach'}
              </button>
            </form>
          ) : (
            <>
              <div className="notebook-input-source-tabs">
                {(['competition', 'notebook', 'dataset', 'model'] as const).map((kind) => (
                  <button
                    key={kind}
                    aria-pressed={source === kind}
                    disabled={busy}
                    onClick={() => void browse(kind)}
                  >
                    {kind === 'competition'
                      ? 'Competitions'
                      : kind === 'notebook'
                        ? 'Notebooks'
                        : kind === 'model'
                          ? 'Models'
                          : 'Datasets'}
                  </button>
                ))}
              </div>
              <p>
                Attach a source as one folder. Competitions require joining; notebooks include their
                saved output files.
              </p>
              <input
                aria-label="Search input sources"
                placeholder="Search by name"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              <button disabled={busy} onClick={() => void browse()}>
                Search
              </button>
              {busy ? (
                <p>Loading inputs…</p>
              ) : (
                items.map((item) => (
                  <button
                    className="notebook-dataset-option"
                    key={`${item.kind}-${item.id}`}
                    disabled={inputs.some(
                      (input) => input.id === item.id && input.kind === item.kind,
                    )}
                    onClick={() => void selectInput(item)}
                  >
                    <Boxes size={20} />
                    <span>
                      {item.title}
                      <small>Add all files</small>
                    </span>
                    <Plus size={16} />
                  </button>
                ))
              )}
              {next && (
                <button disabled={busy} onClick={() => void browse(source, next)}>
                  Load more sources
                </button>
              )}
              {!busy && !items.length && <p>No matching sources available.</p>}
            </>
          )}
        </div>
      )}
    </aside>
  );
}
