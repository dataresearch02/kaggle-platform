import Engagement from './Engagement';
import { useEffect, useState } from 'react';
import { api, type User } from './api';
import Markdown from './Markdown';

type Comment = { id: number; owner_id: number; username: string; body: string; created_at: string };
export default function CodeComments({
  id,
  user,
  signIn,
  allowComments = true,
}: {
  allowComments?: boolean;
  id: number;
  user: User | null;
  signIn: () => void;
}) {
  const [rows, setRows] = useState<Comment[]>([]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [body, setBody] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    api<{ items: Comment[]; next_cursor: number | null }>(`/code/${id}/comments`)
      .then((page) => {
        if (active) {
          setRows(page.items);
          setCursor(page.next_cursor);
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [id]);
  return (
    <section className="code-comments">
      <h2>Comments</h2>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {!allowComments ? (
        <p>Comments are disabled for this notebook.</p>
      ) : user ? (
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            setBusy(true);
            setError('');
            try {
              const row = await api<Comment>(`/code/${id}/comments`, {
                method: 'POST',
                body: JSON.stringify({ body }),
              });
              setRows((previous) => [...previous, row]);
              setBody('');
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <label>
            Write a comment
            <textarea
              value={body}
              onChange={(event) => setBody(event.target.value)}
              required
              maxLength={10000}
              rows={4}
            />
          </label>
          <button className="button" disabled={busy || loading || !body.trim()}>
            Post comment
          </button>
        </form>
      ) : (
        <button className="button secondary" onClick={signIn}>
          Sign in to comment
        </button>
      )}
      {loading ? <p role="status">Loading comments…</p> : !rows.length && <p>No comments yet.</p>}
      {rows.map((row) => (
        <article className="code-published-cell" key={row.id}>
          <p>
            <strong>{row.username}</strong> · {new Date(row.created_at).toLocaleString()}
          </p>
          <Markdown>{row.body}</Markdown>
          <Engagement kind="notebook-comment" id={row.id} user={user} signIn={signIn} />
          {user?.id === row.owner_id && (
            <button
              className="text-button"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                setError('');
                try {
                  await api(`/code/${id}/comments/${row.id}`, { method: 'DELETE' });
                  setRows((values) => values.filter((item) => item.id !== row.id));
                } catch (e) {
                  setError((e as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              Delete comment
            </button>
          )}
        </article>
      ))}
      {cursor !== null && (
        <button
          className="button secondary"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setError('');
            try {
              const page = await api<{ items: Comment[]; next_cursor: number | null }>(
                `/code/${id}/comments?after=${cursor}`,
              );
              setRows((previous) =>
                [
                  ...previous,
                  ...page.items.filter((item) => !previous.some((row) => row.id === item.id)),
                ].sort((a, b) => a.id - b.id),
              );
              setCursor(page.next_cursor);
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          Load more comments
        </button>
      )}
    </section>
  );
}
