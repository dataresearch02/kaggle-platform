import { useState } from 'react';
import { Boxes, ChevronRight, Download, FileText, Plus, Upload, X } from 'lucide-react';
import { api, type Item } from './api';

type Input = { id: number; title: string; filename?: string };
export default function NotebookPanel({
  inputs,
  attach,
  headings,
  jump,
  ready,
  notebookId,
  draft,
  cellCount,
  outputCount,
}: {
  inputs: Input[];
  attach: (item: Input) => Promise<void>;
  headings: { id: string; title: string }[];
  jump: (id: string) => void;
  ready: boolean;
  notebookId: number;
  draft: boolean;
  cellCount: number;
  outputCount: number;
}) {
  const [picker, setPicker] = useState(false);
  const [upload, setUpload] = useState(false);
  const [items, setItems] = useState<Item[]>([]);
  const [query, setQuery] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function browse() {
    setPicker(true);
    setBusy(true);
    setError('');
    try {
      setItems(await api<Item[]>('/datasets'));
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
      <h2>Notebook</h2>
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
          <ul className="notebook-inputs">
            {inputs.map((item) => (
              <li key={item.id}>
                <FileText size={17} />
                <div>
                  <strong>{item.title}</strong>
                  <small>{item.filename || 'CSV dataset'} · loader cell added</small>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <div className="notebook-input-empty">
            <div className="notebook-cubes">
              <Boxes size={104} strokeWidth={1.5} />
            </div>
            <h3>No input attached</h3>
            <p>Attach an Arena dataset to your notebook</p>
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
        <p className="notebook-panel-note">Cell outputs are included when you save.</p>
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
        <div className="notebook-outline">
          {headings.length ? (
            headings.map((h) => (
              <button key={h.id} onClick={() => jump(h.id)}>
                {h.title}
              </button>
            ))
          ) : (
            <p>Add Markdown headings to outline your notebook.</p>
          )}
        </div>
      </details>
      <details>
        <summary>Session options</summary>
        <dl>
          <dt>Language</dt>
          <dd>Python 3</dd>
          <dt>Accelerator</dt>
          <dd>CPU</dd>
          <dt>Notebook</dt>
          <dd>{cellCount} cells</dd>
          <dt>Execution limit</dt>
          <dd>2 minutes / request</dd>
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
                This publishes a public CSV dataset and adds a Python loader cell to this notebook.
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
                {busy ? 'Uploading…' : 'Publish and attach'}
              </button>
            </form>
          ) : (
            <>
              <input
                aria-label="Search datasets"
                placeholder="Search datasets"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              {busy ? (
                <p>Loading datasets…</p>
              ) : (
                items
                  .filter((item) => item.title.toLowerCase().includes(query.toLowerCase()))
                  .map((item) => (
                    <button
                      className="notebook-dataset-option"
                      key={item.id}
                      disabled={inputs.some((input) => input.id === item.id)}
                      onClick={() => void selectInput(item)}
                    >
                      <FileText size={20} />
                      <span>
                        {item.title}
                        <small>{item.filename}</small>
                      </span>
                      <Plus size={16} />
                    </button>
                  ))
              )}
              {!busy &&
                !items.filter((item) => item.title.toLowerCase().includes(query.toLowerCase()))
                  .length && <p>No matching datasets.</p>}
            </>
          )}
        </div>
      )}
    </aside>
  );
}
