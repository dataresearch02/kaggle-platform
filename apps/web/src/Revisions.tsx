import { useState } from 'react';
import { api, type User } from './api';

type Revision = {
  id: number;
  editor: string | null;
  title: string | null;
  body: string;
  created_at: string;
};

/** Previous versions of an edited or author-deleted post, for administrators only. */
export default function RevisionHistory({
  kind,
  id,
  user,
}: {
  kind: 'competition-post' | 'reply' | 'notebook-comment';
  id: number;
  user: User | null;
}) {
  const [rows, setRows] = useState<Revision[] | null>(null);
  const [error, setError] = useState('');
  if (user?.role !== 'admin') return null;
  return (
    <details
      className="revision-history"
      onToggle={(event) => {
        if (!(event.currentTarget as HTMLDetailsElement).open || rows) return;
        api<Revision[]>(`/admin/revisions/${kind}/${id}`)
          .then(setRows)
          .catch((e) => setError(e.message));
      }}
    >
      <summary>Revision history</summary>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {rows && !rows.length && <p className="muted">No earlier versions.</p>}
      {rows?.map((row) => (
        <article key={row.id}>
          <small>
            Replaced {new Date(row.created_at).toLocaleString()}
            {row.editor ? ` by ${row.editor}` : ''}
          </small>
          {row.title && <strong>{row.title}</strong>}
          <pre>{row.body}</pre>
        </article>
      ))}
    </details>
  );
}
