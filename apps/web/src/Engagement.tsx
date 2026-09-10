import { useEffect, useState } from 'react';
import { api, type User } from './api';
import Markdown from './Markdown';

type Reaction = { reaction: string; count: number; reacted: boolean };
type Reply = { id: number; owner_id: number; username: string; body: string; created_at: string };
type Thread = { reactions: Reaction[]; replies: Reply[]; next_cursor: number | null };
const labels: Record<string, string> = {
  like: '👍 Like',
  helpful: '💡 Helpful',
  celebrate: '🎉 Celebrate',
};

export default function Engagement({
  kind,
  id,
  user,
  signIn,
  allowReply = true,
}: {
  kind: 'notebook-comment' | 'discussion-comment' | 'discussion' | 'competition-post';
  id: number;
  user: User | null;
  signIn: () => void;
  allowReply?: boolean;
}) {
  const base = `/engagement/${kind}/${id}`;
  const [thread, setThread] = useState<Thread | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [replying, setReplying] = useState(false);
  const [body, setBody] = useState('');
  useEffect(() => {
    let active = true;
    setThread(null);
    setError('');
    api<Thread>(base)
      .then((data) => {
        if (active) setThread(data);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [base, user?.id]);
  async function act(action: () => Promise<void>) {
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
    <div className="engagement">
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="engagement-actions">
        {thread?.reactions.map((reaction) => (
          <button
            key={reaction.reaction}
            type="button"
            aria-pressed={reaction.reacted}
            disabled={busy}
            onClick={() => {
              if (!user) {
                signIn();
                return;
              }
              void act(async () => {
                const reactions = await api<Reaction[]>(`${base}/reactions/${reaction.reaction}`, {
                  method: reaction.reacted ? 'DELETE' : 'PUT',
                });
                setThread((value) => value && { ...value, reactions });
              });
            }}
          >
            {labels[reaction.reaction]} {reaction.count}
          </button>
        ))}
        {allowReply && (
          <button
            type="button"
            disabled={busy || !thread}
            aria-expanded={replying}
            onClick={() => {
              if (!user) signIn();
              else setReplying(!replying);
            }}
          >
            Reply
          </button>
        )}
      </div>
      {replying && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void act(async () => {
              const reply = await api<Reply>(`${base}/replies`, {
                method: 'POST',
                body: JSON.stringify({ body }),
              });
              setThread((value) => value && { ...value, replies: [...value.replies, reply] });
              setBody('');
              setReplying(false);
            });
          }}
        >
          <label>
            Write a reply
            <textarea
              autoFocus
              rows={3}
              maxLength={10000}
              required
              value={body}
              onChange={(event) => setBody(event.target.value)}
            />
          </label>
          <div className="button-row">
            <button className="button" disabled={busy || !body.trim()}>
              Post reply
            </button>
            <button
              className="button secondary"
              type="button"
              disabled={busy}
              onClick={() => setReplying(false)}
            >
              Cancel
            </button>
          </div>
        </form>
      )}
      {allowReply && (
        <div className="engagement-replies">
          {thread?.replies.map((reply) => (
            <article className="engagement-reply" key={reply.id}>
              <p>
                <strong>{reply.username}</strong> · {new Date(reply.created_at).toLocaleString()}
              </p>
              <Markdown>{reply.body}</Markdown>
              {user?.id === reply.owner_id && (
                <button
                  type="button"
                  className="text-button"
                  disabled={busy}
                  onClick={() =>
                    void act(async () => {
                      await api(`${base}/replies/${reply.id}`, { method: 'DELETE' });
                      setThread(
                        (value) =>
                          value && {
                            ...value,
                            replies: value.replies.filter((item) => item.id !== reply.id),
                          },
                      );
                    })
                  }
                >
                  Delete reply
                </button>
              )}
            </article>
          ))}
          {thread?.next_cursor != null && (
            <button
              className="text-button"
              disabled={busy}
              onClick={() =>
                void act(async () => {
                  const page = await api<Thread>(`${base}?after=${thread.next_cursor}`);
                  setThread(
                    (value) =>
                      value && {
                        ...page,
                        replies: [
                          ...value.replies,
                          ...page.replies.filter(
                            (item) => !value.replies.some((old) => old.id === item.id),
                          ),
                        ].sort((a, b) => a.id - b.id),
                      },
                  );
                })
              }
            >
              Load more replies
            </button>
          )}
        </div>
      )}
    </div>
  );
}
