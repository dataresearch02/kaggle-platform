import type { Page } from './navigation';
import { useEffect, useRef, useState } from 'react';
import { api } from './api';
import NotebookWorkspace from './NotebookWorkspace';

export default function NewNotebook({
  close,
  saved,
  competitionId,
}: {
  close: () => void;
  saved: () => void;
  competitionId?: number;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const draft = useRef<string | undefined>(undefined);
  const [draftId, setDraftId] = useState('');
  const [title, setTitle] = useState('Untitled notebook');
  const [error, setError] = useState('');
  const [permanent, setPermanent] = useState(false);
  const [savedNotebookId, setSavedNotebookId] = useState(0);
  const [closing, setClosing] = useState(false);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    let alive = true;
    const previous = document.body.style.overflow;
    const focus = document.activeElement as HTMLElement | null;
    dialog.current?.showModal();
    document.body.style.overflow = 'hidden';
    const remove = (id: string | undefined) => {
      if (id)
        void fetch(`/api/notebook-drafts/${id}`, {
          method: 'DELETE',
          keepalive: true,
          headers: { 'X-Arena-Client': 'web' },
        }).catch(() => {});
    };
    const discard = () => remove(draft.current);
    window.addEventListener('pagehide', discard);
    void api<{ id: string }>(
      `/notebook-drafts${competitionId ? `?competition_id=${competitionId}` : ''}`,
      { method: 'POST' },
    )
      .then(({ id }) => {
        if (alive) {
          draft.current = id;
          setDraftId(id);
        } else remove(id);
      })
      .catch((e) => {
        if (alive) setError(e.message);
      });
    const heartbeat = setInterval(() => {
      if (draft.current)
        void api(`/notebook-drafts/${draft.current}/heartbeat`, { method: 'POST' }).catch((e) => {
          if (alive) setError(e.message);
        });
    }, 30000);
    return () => {
      alive = false;
      clearInterval(heartbeat);
      window.removeEventListener('pagehide', discard);
      discard();
      document.body.style.overflow = previous;
      focus?.focus();
    };
  }, []);
  async function persist() {
    setSaving(true);
    try {
      const notebook = await api<{ id: number }>(`/notebook-drafts/${draftId}/save`, {
        method: 'POST',
        body: JSON.stringify({ title: title.trim(), competition_id: competitionId }),
      });
      setSavedNotebookId(notebook.id);
      setPermanent(true);
      setError('');
      saved();
    } finally {
      setSaving(false);
    }
  }
  async function dismiss(destination?: Page) {
    if (saving || closing) return;
    // Unmount the editor and cancel execution before discarding the temporary file.
    setClosing(true);
    try {
      if (draft.current) await api(`/notebook-drafts/${draft.current}`, { method: 'DELETE' });
      draft.current = undefined;
      close();
    } catch {
      setError('The server could not finish cleanup. The draft is marked for automatic deletion.');
      close();
    }
    if (destination) window.location.hash = destination;
  }
  return (
    <dialog
      ref={dialog}
      className="new-notebook-dialog"
      aria-label="New notebook"
      onCancel={(event) => {
        event.preventDefault();
        void dismiss();
      }}
    >
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {closing ? (
        <p>Closing notebook…</p>
      ) : draftId ? (
        <NotebookWorkspace
          title={title}
          onTitleChange={setTitle}
          onClose={() => void dismiss()}
          onNavigate={(page) => void dismiss(page)}
          permanent={permanent}
          notebookId={savedNotebookId}
          competitionId={competitionId}
          draftId={draftId}
          signedIn
          signIn={() => {}}
          autoStart
          onSaveDraft={persist}
          onSavingChange={setSaving}
        />
      ) : (
        <div className="notebook-opening">
          <p>{error ? 'Notebook could not be created.' : 'Creating temporary notebook…'}</p>
          <button onClick={() => void dismiss()}>Close notebook editor</button>
        </div>
      )}
    </dialog>
  );
}
