import { useEffect, useRef, useState } from 'react';
import { Search, Pencil, ArrowUpRight, Download, FolderOpen, Trash2, X } from 'lucide-react';
import { api, type Item } from './api';

export const workKinds = {
  datasets: 'Datasets',
  models: 'Models',
  notebooks: 'Codes',
  competitions: 'Competitions',
  benchmarks: 'Benchmarks',
};
export type WorkKind = keyof typeof workKinds;
export type WorkItem = Item & { work_kind: WorkKind; work_resource?: string; created_at?: string };
function DeleteWorkDialog({
  item,
  close,
  deleted,
}: {
  item: WorkItem;
  close: () => void;
  deleted: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    const focus = document.activeElement as HTMLElement | null;
    dialog.current?.showModal();
    return () => {
      dialog.current?.close();
      focus?.focus();
    };
  }, []);
  async function remove() {
    setBusy(true);
    setError('');
    try {
      await api(`/work/${item.work_resource || item.work_kind}/${item.id}`, { method: 'DELETE' });
      deleted();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }
  return (
    <dialog
      ref={dialog}
      className="work-delete-dialog"
      aria-labelledby="delete-work-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) close();
      }}
    >
      <h2 id="delete-work-title">Delete this item?</h2>
      <p>
        <strong>{item.title}</strong>
      </p>
      <p>This permanently removes the item from Your work and Explore.</p>
      <p>
        {item.work_resource === 'benchmark-collections'
          ? 'Its evaluation history and stored run files will be deleted. Reusable tasks and models will remain.'
          : item.work_kind === 'datasets'
            ? 'The uploaded CSV will be deleted. Copies already attached to notebooks or downloaded will remain.'
            : item.work_kind === 'notebooks'
              ? 'Your saved notebook file will be deleted when its runtime is available. Linked draft editors will expire. Other users’ private copies and downloaded copies will remain.'
              : item.work_kind === 'models'
                ? 'This deletes the model card. The externally hosted model is not affected.'
                : 'Its test data, answers, entries, submissions and leaderboard will also be deleted.'}
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="work-delete-actions">
        <button className="button secondary" autoFocus disabled={busy} onClick={close}>
          Cancel
        </button>
        <button className="button danger" disabled={busy} onClick={() => void remove()}>
          {busy ? 'Deleting…' : 'Delete permanently'}
        </button>
      </div>
    </dialog>
  );
}

export default function YourWork({
  items,
  loading,
  error,
  signedIn,
  signIn,
  open,
  refresh,
  filter,
}: {
  items: WorkItem[];
  loading: boolean;
  error: string;
  signedIn: boolean;
  signIn: () => void;
  open: (item: WorkItem) => void;
  refresh: () => void;
  filter: WorkKind | 'all';
}) {
  const [query, setQuery] = useState('');
  const [deleting, setDeleting] = useState<WorkItem | null>(null);
  const [editing, setEditing] = useState<WorkItem | null>(null);
  const editForm = useRef<HTMLFormElement>(null);
  useEffect(() => {
    if (editing) {
      editForm.current?.scrollIntoView({ block: 'center' });
      editForm.current?.querySelector('input')?.focus();
    }
  }, [editing?.id, editing?.work_kind]);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const filtered = items.filter(
    (item) =>
      (filter === 'all' || item.work_kind === filter) &&
      `${item.title} ${item.description || ''}`.toLowerCase().includes(query.toLowerCase()),
  );
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!editing) return;
    setSaving(true);
    setSaveError('');
    try {
      await api(`/work/${editing.work_resource || editing.work_kind}/${editing.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ title: editing.title, description: editing.description || '' }),
      });
      setEditing(null);
      refresh();
    } catch (e) {
      setSaveError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  return (
    <section className="your-work">
      <div className="eyebrow">PERSONAL WORKSPACE</div>
      <div className="page-intro">
        <div>
          <h1>Your work</h1>
          <p>Find and manage the datasets, code, models, and challenges you create.</p>
        </div>
        <FolderOpen size={36} />
      </div>
      {!signedIn ? (
        <div className="empty">
          <h3>Your work starts here</h3>
          <p>Sign in to see your own content.</p>
          <button className="button" onClick={signIn}>
            Sign in
          </button>
        </div>
      ) : (
        <>
          <div className="work-tabs" aria-label="Filter your work">
            {(['all', ...Object.keys(workKinds)] as (WorkKind | 'all')[]).map((kind) => (
              <button
                key={kind}
                aria-pressed={filter === kind}
                onClick={() => {
                  location.hash = kind === 'all' ? 'work' : `work/${kind}`;
                }}
              >
                {kind === 'all' ? 'All work' : workKinds[kind]}
                <span>
                  {items.filter((item) => kind === 'all' || item.work_kind === kind).length}
                </span>
              </button>
            ))}
          </div>
          <label className="search work-search">
            <Search size={18} />
            <input
              aria-label="Search your work"
              placeholder="Search your work…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          {error ? (
            <div className="empty" role="alert">
              <p>{error}</p>
              <button className="button secondary" onClick={refresh}>
                Try again
              </button>
            </div>
          ) : loading ? (
            <p role="status">Loading your work…</p>
          ) : !filtered.length ? (
            <div className="empty">
              <FolderOpen />
              <h3>{items.length ? 'No matching work' : 'Create something of your own'}</h3>
              <p>
                {items.length
                  ? 'Try another search or category.'
                  : 'Use Create to upload a dataset or save your first notebook. Community examples stay in Explore.'}
              </p>
            </div>
          ) : (
            <div className="work-list">
              {filtered.map((item) => (
                <article
                  className="work-row"
                  key={`${item.work_resource || item.work_kind}-${item.id}`}
                >
                  <div className="work-row-info">
                    <small>
                      {workKinds[item.work_kind]} ·{' '}
                      {item.created_at
                        ? new Date(item.created_at).toLocaleDateString()
                        : 'Created by you'}
                    </small>
                    <button className="work-title" onClick={() => open(item)}>
                      {item.title}
                    </button>
                    <p>{item.description || 'No description yet.'}</p>
                  </div>
                  <div className="work-row-actions">
                    <button
                      aria-label={`Open ${item.title}`}
                      title="Open"
                      onClick={() => open(item)}
                    >
                      <ArrowUpRight size={18} />
                    </button>
                    <button
                      aria-label={`Edit details for ${item.title}`}
                      title="Edit details"
                      onClick={() => {
                        setEditing({ ...item });
                        setSaveError('');
                      }}
                    >
                      <Pencil size={17} />
                    </button>
                    <button
                      aria-label={`Delete ${item.title}`}
                      title="Delete"
                      className="work-delete-button"
                      onClick={() => setDeleting(item)}
                    >
                      <Trash2 size={17} />
                    </button>
                    {['datasets', 'notebooks'].includes(item.work_kind) && (
                      <a
                        aria-label={`Download ${item.title}`}
                        title={
                          item.work_kind === 'notebooks'
                            ? 'Download published code notebook'
                            : 'Download dataset'
                        }
                        href={`/api/${item.work_resource || item.work_kind}/${item.id}/download`}
                      >
                        <Download size={18} />
                      </a>
                    )}
                  </div>
                </article>
              ))}
            </div>
          )}
        </>
      )}
      {deleting && signedIn && (
        <DeleteWorkDialog
          item={deleting}
          close={() => setDeleting(null)}
          deleted={() => {
            if (editing?.id === deleting.id && editing.work_kind === deleting.work_kind)
              setEditing(null);
            setDeleting(null);
            refresh();
          }}
        />
      )}
      {editing && (
        <form
          ref={editForm}
          className="work-edit"
          onSubmit={(event) => void save(event)}
          aria-label="Edit work details"
        >
          <header>
            <h2>Edit details</h2>
            <button
              type="button"
              aria-label="Cancel editing"
              disabled={saving}
              onClick={() => setEditing(null)}
            >
              <X size={20} />
            </button>
          </header>
          <label>
            Title
            <input
              value={editing.title}
              required
              minLength={3}
              maxLength={160}
              onChange={(e) => setEditing({ ...editing, title: e.target.value })}
            />
          </label>
          <label>
            Description
            <textarea
              aria-label="Description"
              value={editing.description || ''}
              maxLength={5000}
              rows={4}
              onChange={(e) => setEditing({ ...editing, description: e.target.value })}
            />
          </label>
          {saveError && (
            <p className="error" role="alert">
              {saveError}
            </p>
          )}
          <button className="button" disabled={saving}>
            {saving ? 'Saving…' : 'Save details'}
          </button>
        </form>
      )}
    </section>
  );
}
