import Engagement from './Engagement';
import { useEffect, useState } from 'react';
import { api, type User } from './api';
import Markdown from './Markdown';
import ModerationActions, { HiddenNotice } from './Moderation';
import { Timestamp, UserLink, VoteButton } from './Community';
import RevisionHistory from './Revisions';

type Comment = {
  id: number;
  owner_id: number;
  username: string;
  body: string;
  created_at: string;
  edited_at?: string | null;
  deleted?: boolean;
  hidden?: boolean;
  hidden_reason?: string;
  votes?: number;
  voted?: boolean;
  owner_tier?: string | null;
  mentions?: string[];
};
type CommentPage = { items: Comment[]; next_cursor: number | null };
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
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  async function reload() {
    const page = await api<CommentPage>(`/code/${id}/comments`);
    setRows(page.items);
    setCursor(page.next_cursor);
  }
  useEffect(() => {
    let active = true;
    api<CommentPage>(`/code/${id}/comments`)
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
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError('');
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
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
          onSubmit={(event) => {
            event.preventDefault();
            void run(async () => {
              const row = await api<Comment>(`/code/${id}/comments`, {
                method: 'POST',
                body: JSON.stringify({ body }),
              });
              setRows((previous) => [...previous, row]);
              setBody('');
            });
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
              placeholder="Markdown and @username mentions are supported."
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
          <p className="discussion-author">
            <UserLink username={row.username} tier={row.owner_tier} />
            <Timestamp created={row.created_at} edited={row.edited_at} />
          </p>
          {row.deleted ? (
            <p className="deleted-placeholder">This comment was deleted by its author.</p>
          ) : editing === row.id ? (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void run(async () => {
                  const updated = await api<Comment>(`/code/${id}/comments/${row.id}`, {
                    method: 'PUT',
                    body: JSON.stringify({ body: draft }),
                  });
                  setRows((values) => values.map((item) => (item.id === row.id ? updated : item)));
                  setEditing(null);
                });
              }}
            >
              <label>
                Edit comment
                <textarea
                  rows={4}
                  maxLength={10000}
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                />
              </label>
              <div className="button-row">
                <button className="button small" disabled={busy || !draft.trim()}>
                  Save
                </button>
                <button
                  type="button"
                  className="text-button"
                  disabled={busy}
                  onClick={() => setEditing(null)}
                >
                  Cancel
                </button>
              </div>
            </form>
          ) : (
            <>
              <HiddenNotice hidden={row.hidden} reason={row.hidden_reason} />
              <Markdown mentions={row.mentions}>{row.body}</Markdown>
            </>
          )}
          <div className="comment-actions">
            <VoteButton
              kind="notebook-comment"
              id={row.id}
              votes={row.votes}
              voted={row.voted}
              ownerId={row.owner_id}
              user={user}
              signIn={signIn}
              label={`comment by ${row.username}`}
              disabled={row.deleted}
            />
            {user?.id === row.owner_id && !row.deleted && (
              <>
                <button
                  className="text-button"
                  disabled={busy}
                  onClick={() => {
                    setDraft(row.body);
                    setEditing(row.id);
                  }}
                >
                  Edit comment
                </button>
                <button
                  className="text-button"
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      await api(`/code/${id}/comments/${row.id}`, { method: 'DELETE' });
                      await reload();
                    })
                  }
                >
                  Delete comment
                </button>
              </>
            )}
            {(row.edited_at || row.deleted) && (
              <RevisionHistory kind="notebook-comment" id={row.id} user={user} />
            )}
          </div>
          <ModerationActions
            kind="notebook-comment"
            id={row.id}
            ownerId={row.owner_id}
            hidden={row.hidden}
            user={user}
            signIn={signIn}
            label={`comment by ${row.username}`}
            onChange={(change) =>
              setRows((values) =>
                change.deleted
                  ? values.filter((item) => item.id !== row.id)
                  : values.map((item) =>
                      item.id === row.id
                        ? { ...item, hidden: change.hidden, hidden_reason: change.reason }
                        : item,
                    ),
              )
            }
          />
          <Engagement
            kind="notebook-comment"
            id={row.id}
            user={user}
            signIn={signIn}
            canReply={!row.deleted && allowComments}
          />
        </article>
      ))}
      {cursor !== null && (
        <button
          className="button secondary"
          disabled={busy}
          onClick={() =>
            void run(async () => {
              const page = await api<CommentPage>(`/code/${id}/comments?after=${cursor}`);
              setRows((previous) =>
                [
                  ...previous,
                  ...page.items.filter((item) => !previous.some((row) => row.id === item.id)),
                ].sort((a, b) => a.id - b.id),
              );
              setCursor(page.next_cursor);
            })
          }
        >
          Load more comments
        </button>
      )}
    </section>
  );
}
