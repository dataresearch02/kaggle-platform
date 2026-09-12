import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { api } from './api';
import DiscussionEditor from './DiscussionEditor';

export default function DiscussionCreate({
  competitionId,
  close,
}: {
  competitionId: number;
  close: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    const focused = document.activeElement as HTMLElement;
    dialog.current?.showModal();
    return () => focused?.focus();
  }, []);
  return createPortal(
    <dialog
      ref={dialog}
      className="discussion-compose-drawer"
      aria-label="Create discussion"
      onCancel={(event) => {
        event.preventDefault();
        if (!busy && !uploading) close();
      }}
    >
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          if (busy || uploading) return;
          setBusy(true);
          setError('');
          try {
            const post = await api<{ id: number }>(`/competitions/${competitionId}/discussion`, {
              method: 'POST',
              body: JSON.stringify({ title: title.trim(), body: body.trim() }),
            });
            close();
            location.hash = `competitions/${competitionId}/discussion/${post.id}`;
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <header>
          <h2>New discussion</h2>
          <button
            type="button"
            aria-label="Close discussion sidebar"
            disabled={busy || uploading}
            onClick={close}
          >
            <X size={22} />
          </button>
        </header>
        <div className="discussion-compose-body">
          <label>
            Title
            <input
              autoFocus
              required
              minLength={3}
              maxLength={160}
              value={title}
              disabled={busy}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="What would you like to discuss?"
            />
          </label>
          <DiscussionEditor
            label="Discussion message"
            value={body}
            onChange={setBody}
            competitionId={competitionId}
            disabled={busy}
            onUploadingChange={setUploading}
          />
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
        </div>
        <footer>
          <button
            type="button"
            className="button secondary"
            onClick={close}
            disabled={busy || uploading}
          >
            Cancel
          </button>
          <button
            className="button"
            disabled={busy || uploading || title.trim().length < 3 || body.trim().length < 3}
          >
            {busy ? 'Posting…' : 'Post discussion'}
          </button>
        </footer>
      </form>
    </dialog>,
    document.body,
  );
}
