import { useEffect, useRef, useState } from 'react';
import { History, X } from 'lucide-react';
import Markdown from './Markdown';
import { api } from './api';
import type { Document } from './NotebookWorkspace';

export default function NotebookHistory({
  id,
  disabled,
  restore,
  revision = 0,
}: {
  revision?: number;
  id: number;
  disabled: boolean;
  restore: (document: Document) => void;
}) {
  const [open, setOpen] = useState(false);
  const [count, setCount] = useState<number | null>(id > 0 ? null : 0);
  useEffect(() => {
    let active = true;
    if (id <= 0) {
      setCount(0);
      return;
    }
    api<{ count: number }>(`/code/${id}/versions/count`)
      .then((result) => {
        if (active) setCount(result.count);
      })
      .catch(() => {
        if (active) setCount(null);
      });
    return () => {
      active = false;
    };
  }, [id, revision, open]);
  const dialog = useRef<HTMLDialogElement>(null);

  const [rows, setRows] = useState<
    { id: number; created_at: string; label?: { name: string; tags: string[] } }[]
  >([]);
  const [selected, setSelected] = useState<Document | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [more, setMore] = useState(false);
  async function load(before?: number) {
    setBusy(true);
    setError('');
    try {
      const next = await api<typeof rows>(
        `/code/${id}/versions${before ? `?before=${before}` : ''}`,
      );
      setRows((old) => (before ? [...old, ...next] : next));
      setMore(next.length === 50);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (open) {
      dialog.current?.showModal();
      void load();
    }
  }, [open, id]);
  return (
    <>
      <button
        className="button secondary notebook-history-button"
        aria-label="Version history"
        disabled={disabled || id <= 0}
        title={
          count === null
            ? 'Version count unavailable; open history'
            : `${count} saved versions · Open history`
        }
        onClick={() => {
          setSelected(null);
          setSelectedId(null);
          setOpen(true);
        }}
      >
        {count ?? '…'}
      </button>
      <dialog
        ref={dialog}
        className="history-dialog"
        aria-label="Notebook version history"
        onClose={() => setOpen(false)}
      >
        <header>
          <h2>
            <History size={22} /> Version history
          </h2>
          <button aria-label="Close history" onClick={() => dialog.current?.close()}>
            <X size={20} />
          </button>
        </header>
        <p>
          Browse saved snapshots. Restoring creates unsaved changes; save when you’re ready to keep
          them.
        </p>
        {error && <p role="alert">{error}</p>}
        <div className="history-layout">
          <nav className="history-list" aria-label="Saved versions">
            {rows.map((row) => (
              <button
                className="history-version"
                key={row.id}
                aria-pressed={selectedId === row.id}
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  setError('');
                  try {
                    const snapshot = await api<Document>(`/code/${id}/versions/${row.id}`);
                    setSelected(snapshot);
                    setSelectedId(row.id);
                  } catch (e) {
                    setError((e as Error).message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <strong>{row.label?.name || `Version ${row.id}`}</strong>
                {row.label?.tags?.length ? <small>{row.label.tags.join(' · ')}</small> : null}
                <time dateTime={row.created_at}>{new Date(row.created_at).toLocaleString()}</time>
              </button>
            ))}
            {!rows.length && !busy && (
              <p>No saved versions yet. Save the notebook to create one.</p>
            )}
            {more && (
              <button disabled={busy} onClick={() => void load(rows.at(-1)?.id)}>
                Load older versions
              </button>
            )}
          </nav>
          <section className="history-preview" aria-label="Version preview" aria-busy={busy}>
            {busy ? (
              <p role="status">Loading version history…</p>
            ) : selected ? (
              <>
                <h3>
                  Version {selectedId} <small> · {selected.cells.length} cells</small>
                </h3>
                {selected.cells.map((cell, index) => {
                  const source =
                    typeof cell.source === 'string' ? cell.source : cell.source.join('');
                  return (
                    <article key={index} className="history-cell">
                      <span className="history-cell-label">
                        {cell.cell_type} · {index + 1}
                      </span>
                      {cell.cell_type === 'markdown' ? (
                        <Markdown>{source}</Markdown>
                      ) : (
                        <pre>{source}</pre>
                      )}
                    </article>
                  );
                })}
              </>
            ) : (
              <div className="history-empty">
                <History size={32} />
                <h3>Choose a saved version</h3>
                <p>Preview its cells before restoring.</p>
              </div>
            )}
          </section>
        </div>
        <footer>
          <span>Restoring does not publish your notebook.</span>
          {selected && (
            <button
              className="button primary"
              disabled={busy || disabled}
              onClick={() => {
                if (
                  window.confirm(
                    'Replace current editor contents with this version? Unsaved edits will be lost.',
                  )
                ) {
                  restore(selected);
                  dialog.current?.close();
                }
              }}
            >
              Restore into editor
            </button>
          )}
        </footer>
      </dialog>
    </>
  );
}
