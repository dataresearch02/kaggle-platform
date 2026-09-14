import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { api } from './api';
import DiscussionEditor from './DiscussionEditor';

export type DiscussionScope = 'competition' | 'forum' | 'dataset' | 'model';

export default function DiscussionCreate({
  competitionId,
  scope = 'competition',
  scopeId,
  scopeTitle,
  close,
}: {
  competitionId?: number;
  scope?: DiscussionScope;
  scopeId?: number;
  scopeTitle?: string;
  close: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const target = scope === 'competition' ? (scopeId ?? competitionId) : scopeId;
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
          if (busy || uploading || target === undefined) return;
          setBusy(true);
          setError('');
          try {
            const post = await api<{ id: number; url: string }>('/competition-discussions', {
              method: 'POST',
              body: JSON.stringify({
                scope,
                scope_id: target,
                title: title.trim(),
                body: body.trim(),
              }),
            });
            close();
            location.hash = post.url.replace(/^#/, '');
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <header>
          <h2>New discussion{scopeTitle ? ` in ${scopeTitle}` : ''}</h2>
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
            competitionId={scope === 'competition' ? target : undefined}
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
