import { useEffect, useState } from 'react';
import { api, type User } from './api';
import Markdown from './Markdown';
import DiscussionEditor from './DiscussionEditor';
import DiscussionAvatar from './DiscussionAvatar';
import ModerationActions, { HiddenNotice } from './Moderation';
import { Timestamp, UserLink, VoteButton } from './Community';
import RevisionHistory from './Revisions';

type Reaction = { reaction: string; count: number; reacted: boolean };
export type Reply = {
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
  canReply = true,
  competitionId,
}: {
  kind:
    | 'notebook-comment'
    | 'discussion-comment'
    | 'discussion'
    | 'competition-post'
    | 'competition-comment';
  id: number;
  user: User | null;
  signIn: () => void;
  allowReply?: boolean;
  /** False on locked topics and deleted comments: existing replies stay readable. */
  canReply?: boolean;
  competitionId?: number;
}) {
  const base = `/engagement/${kind}/${id}`;
  const [thread, setThread] = useState<Thread | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [replying, setReplying] = useState(false);
  const [body, setBody] = useState('');
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState('');
  const [uploading, setUploading] = useState(false);
  const discussion = kind === 'competition-post' || kind === 'competition-comment';
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
  function replace(reply: Reply) {
    setThread(
      (value) =>
        value && {
          ...value,
          replies: value.replies.map((item) => (item.id === reply.id ? reply : item)),
        },
    );
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
        {allowReply && canReply && (
          <button
            type="button"
            disabled={busy || uploading || !thread}
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
      {replying && canReply && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (busy || uploading || !body.trim()) return;
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
          {discussion ? (
            <DiscussionEditor
              label="Write a reply"
              value={body}
              onChange={setBody}
              competitionId={competitionId}
              limit={10000}
              disabled={busy}
              onUploadingChange={setUploading}
            />
          ) : (
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
          )}
          <div className="button-row">
            <button className="button" disabled={busy || uploading || !body.trim()}>
              Post reply
            </button>
            <button
              className="button secondary"
              type="button"
              disabled={busy || uploading}
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
              <p className="discussion-author">
                {discussion && <DiscussionAvatar username={reply.username} />}
                <UserLink username={reply.username} tier={reply.owner_tier} />
                <Timestamp created={reply.created_at} edited={reply.edited_at} />
              </p>
              {reply.deleted ? (
                <p className="deleted-placeholder">This reply was deleted by its author.</p>
              ) : editing === reply.id ? (
                <form
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (!draft.trim()) return;
                    void act(async () => {
                      replace(
                        await api<Reply>(`${base}/replies/${reply.id}`, {
                          method: 'PUT',
                          body: JSON.stringify({ body: draft }),
                        }),
                      );
                      setEditing(null);
                    });
                  }}
                >
                  <label>
                    Edit reply
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
                  <HiddenNotice hidden={reply.hidden} reason={reply.hidden_reason} />
                  <Markdown mentions={reply.mentions}>{reply.body}</Markdown>
                </>
              )}
              <div className="comment-actions">
                <VoteButton
                  kind="reply"
                  id={reply.id}
                  votes={reply.votes}
                  voted={reply.voted}
                  ownerId={reply.owner_id}
                  user={user}
                  signIn={signIn}
                  label={`reply by ${reply.username}`}
                  disabled={reply.deleted}
                />
                <ModerationActions
                  kind="reply"
                  id={reply.id}
                  ownerId={reply.owner_id}
                  hidden={reply.hidden}
                  user={user}
                  signIn={signIn}
                  label={`reply by ${reply.username}`}
                  onChange={(change) =>
                    setThread(
                      (value) =>
                        value && {
                          ...value,
                          replies: change.deleted
                            ? value.replies.filter((item) => item.id !== reply.id)
                            : value.replies.map((item) =>
                                item.id === reply.id
                                  ? { ...item, hidden: change.hidden, hidden_reason: change.reason }
                                  : item,
                              ),
                        },
                    )
                  }
                />
                {user?.id === reply.owner_id && !reply.deleted && (
                  <>
                    <button
                      type="button"
                      className="text-button"
                      disabled={busy}
                      onClick={() => {
                        setDraft(reply.body);
                        setEditing(reply.id);
                      }}
                    >
                      Edit reply
                    </button>
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
                  </>
                )}
                {(reply.edited_at || reply.deleted) && (
                  <RevisionHistory kind="reply" id={reply.id} user={user} />
                )}
              </div>
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
