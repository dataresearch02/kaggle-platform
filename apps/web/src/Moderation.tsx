import { useEffect, useRef, useState } from 'react';
import { Eye, EyeOff, Flag, Trash2, X } from 'lucide-react';
import { api, type User } from './api';

export type ReportKind =
  | 'competition-post'
  | 'reply'
  | 'code'
  | 'notebook-comment'
  | 'dataset'
  | 'model'
  | 'profile';

export const reportKindLabels: Record<ReportKind, string> = {
  'competition-post': 'Discussion topic',
  reply: 'Comment or reply',
  code: 'Code',
  'notebook-comment': 'Notebook comment',
  dataset: 'Dataset',
  model: 'Model',
  profile: 'Profile',
};

/** Shown to authors and administrators on content a moderator has hidden. */
export function HiddenNotice({ hidden, reason }: { hidden?: boolean | number; reason?: string }) {
  if (!hidden) return null;
  return (
    <p className="moderation-notice" role="note">
      <EyeOff size={16} aria-hidden="true" />
      <span>
        Hidden by a moderator{reason ? `: ${reason}` : ''}. Only the author and administrators can
        see it.
      </span>
    </p>
  );
}

export function ReasonDialog({
  title,
  description,
  label,
  confirm,
  required = false,
  danger = false,
  busy,
  error,
  close,
  submit,
}: {
  title: string;
  description?: string;
  label?: string;
  confirm: string;
  required?: boolean;
  danger?: boolean;
  busy: boolean;
  error: string;
  close: () => void;
  submit: (reason: string) => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [value, setValue] = useState('');
  useEffect(() => {
    const element = ref.current!;
    element.showModal();
    return () => element.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className="moderation-dialog"
      aria-label={title}
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) close();
      }}
    >
      <div className="modal-head">
        <h2>{title}</h2>
        <button className="icon-button" aria-label="Close dialog" disabled={busy} onClick={close}>
          <X size={20} />
        </button>
      </div>
      {description && <p className="muted">{description}</p>}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          submit(value.trim());
        }}
      >
        {label && (
          <label>
            {label}
            <textarea
              autoFocus
              rows={3}
              maxLength={1000}
              minLength={required ? 3 : undefined}
              required={required}
              value={value}
              onChange={(event) => setValue(event.target.value)}
            />
          </label>
        )}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="button-row">
          <button className={`button${danger ? ' danger' : ''}`} disabled={busy}>
            {busy ? 'Please wait…' : confirm}
          </button>
          <button type="button" className="button secondary" disabled={busy} onClick={close}>
            Cancel
          </button>
        </div>
      </form>
    </dialog>
  );
}

type Action = 'report' | 'hide' | 'unhide' | 'delete';
export type ModerationChange = { hidden?: boolean; reason?: string; deleted?: boolean };

export async function moderate(
  kind: ReportKind,
  id: number,
  action: 'hide' | 'unhide' | 'delete',
  reason = '',
) {
  if (action === 'delete') await api(`/admin/moderation/${kind}/${id}`, { method: 'DELETE' });
  else
    await api(`/admin/moderation/${kind}/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ hidden: action === 'hide', reason }),
    });
}

export function moderationDialog(action: Action, label: string, kind?: ReportKind) {
  return {
    report: {
      title: `Report ${label}`,
      description: 'Tell the moderators what is wrong. Your report is only visible to them.',
      label: 'Reason',
      confirm: 'Send report',
      required: true,
    },
    hide: {
      title: `Hide ${label}`,
      description: 'Hidden content is visible only to its author and administrators.',
      label: 'Reason shown to the author',
      confirm: 'Hide',
      required: true,
    },
    unhide: {
      title: `Unhide ${label}`,
      description: 'Everyone who could see it before will see it again.',
      label: 'Note for the audit log (optional)',
      confirm: 'Unhide',
    },
    delete: {
      title: `Delete ${label}`,
      description:
        kind === 'profile'
          ? 'This clears the profile details and photo. The account itself is kept.'
          : 'This permanently deletes it and resolves its open reports. It cannot be undone.',
      confirm: 'Delete permanently',
      danger: true,
    },
  }[action];
}

/** Report for signed-in members; hide, unhide and delete for administrators. */
export default function ModerationActions({
  kind,
  id,
  ownerId,
  hidden,
  user,
  signIn,
  onChange,
  label = 'this item',
}: {
  kind: ReportKind;
  id: number;
  ownerId?: number;
  hidden?: boolean | number;
  user: User | null;
  signIn: () => void;
  onChange?: (change: ModerationChange) => void;
  label?: string;
}) {
  const [action, setAction] = useState<Action | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const admin = user?.role === 'admin';
  const own = !!user && user.id === ownerId;
  if (own && !admin) return null;
  function open(next: Action) {
    if (!user) {
      signIn();
      return;
    }
    setError('');
    setNotice('');
    setAction(next);
  }
  async function run(reason: string) {
    if (!action) return;
    setBusy(true);
    setError('');
    try {
      if (action === 'report') {
        await api('/reports', { method: 'POST', body: JSON.stringify({ kind, id, reason }) });
        setNotice('Reported. A moderator will review it.');
      } else {
        await moderate(kind, id, action, reason);
        onChange?.(
          action === 'delete'
            ? { deleted: true }
            : { hidden: action === 'hide', reason: action === 'hide' ? reason : '' },
        );
      }
      setAction(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <span className="moderation-actions">
        {!own && (
          <button
            type="button"
            className="text-button"
            aria-label={`Report ${label}`}
            onClick={() => open('report')}
          >
            <Flag size={14} /> Report
          </button>
        )}
        {admin && (
          <>
            <button
              type="button"
              className="text-button"
              aria-label={`${hidden ? 'Unhide' : 'Hide'} ${label}`}
              onClick={() => open(hidden ? 'unhide' : 'hide')}
            >
              {hidden ? <Eye size={14} /> : <EyeOff size={14} />} {hidden ? 'Unhide' : 'Hide'}
            </button>
            <button
              type="button"
              className="text-button danger-text"
              aria-label={`Delete ${label}`}
              onClick={() => open('delete')}
            >
              <Trash2 size={14} /> Delete
            </button>
          </>
        )}
        {notice && <small role="status">{notice}</small>}
      </span>
      {action && (
        <ReasonDialog
          {...moderationDialog(action, label, kind)}
          busy={busy}
          error={error}
          close={() => setAction(null)}
          submit={(reason) => void run(reason)}
        />
      )}
    </>
  );
}
