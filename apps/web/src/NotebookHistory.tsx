import { useEffect, useRef, useState } from 'react';
import { api } from './api';
import type { Document } from './NotebookWorkspace';

export default function NotebookHistory({
  id,
  disabled,
  restore,
}: {
  id: number;
  disabled: boolean;
  restore: (document: Document) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<{ id: number; created_at: string }[]>([]);
  const [selected, setSelected] = useState<Document | null>(null);
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
        className="button secondary"
        disabled={disabled}
        onClick={() => {
          setSelected(null);
          setOpen(true);
        }}
      >
        Version history
      </button>
      <dialog
        ref={dialog}
        className="history-dialog"
        aria-label="Notebook version history"
        onClose={() => setOpen(false)}
      >
        <header>
          <h2>Version history</h2>
          <button onClick={() => dialog.current?.close()}>Close history</button>
        </header>
        <p>
          Saved versions are immutable. Restore loads a version into the editor; save it to keep the
          restored copy. Publishing still requires a separate action.
        </p>
        {error && <p role="alert">{error}</p>}
        {rows.map((row) => (
          <button
            className="history-version"
            key={row.id}
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setError('');
              try {
                setSelected(await api<Document>(`/code/${id}/versions/${row.id}`));
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            Version {row.id} · {new Date(row.created_at).toLocaleString()}
          </button>
        ))}
        {!rows.length && !busy && <p>No saved versions yet. Save the notebook to create one.</p>}
        {more && (
          <button disabled={busy} onClick={() => void load(rows.at(-1)?.id)}>
            Load older versions
          </button>
        )}
        {selected && (
          <>
            <pre>
              {selected.cells
                .map((cell) =>
                  typeof cell.source === 'string' ? cell.source : cell.source.join(''),
                )
                .join('\n\n')}
            </pre>
            <button
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
          </>
        )}
      </dialog>
    </>
  );
}
