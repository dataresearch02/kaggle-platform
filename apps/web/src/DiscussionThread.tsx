import Engagement from './Engagement';
import { useEffect, useState } from 'react';
import { ArrowLeft, Bookmark, Pin, Trash2 } from 'lucide-react';
import Markdown from './Markdown';
import DiscussionEditor from './DiscussionEditor';
import DiscussionAvatar from './DiscussionAvatar';
import { api, type User } from './api';
export type DiscussionPost = {
  id: number;
  competition_id: number;
  title: string;
  body: string;
  owner: string;
  created_at: string;
  pinned: boolean;
  bookmarked: boolean;
  can_pin: boolean;
};
type Comment = { id: number; owner_id: number; username: string; body: string; created_at: string };
export default function DiscussionThread({
  id,
  competitionId,
  user,
  signIn,
}: {
  id: number;
  competitionId: number;
  user: User | null;
  signIn: () => void;
}) {
  const [post, setPost] = useState<DiscussionPost | null>(null);
  const [comments, setComments] = useState<Comment[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [body, setBody] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setPost(null);
    setError('');
    setComments([]);
    setNext(null);
    Promise.all([
      api<DiscussionPost>(`/competition-discussions/${id}`),
      api<{ items: Comment[]; next_cursor: number | null }>(
        `/competition-discussions/${id}/comments`,
      ),
    ])
      .then(([row, thread]) => {
        if (!active) return;
        if (row.competition_id !== competitionId) {
          setError('Discussion does not belong to this competition.');
          return;
        }
        setPost(row);
        setComments(thread.items);
        setNext(thread.next_cursor);
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
  }, [id, competitionId, user?.id, revision]);
  return (
    <section className="discussion-detail" aria-label="Discussion details">
      <a className="discussion-back" href={`#competitions/${competitionId}/discussion`}>
        <ArrowLeft size={18} /> All discussions
      </a>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {loading && <p role="status">Loading discussion…</p>}
      {post && (
        <>
          <article className="competition-post">
            <header className="discussion-detail-heading">
              <h2>{post.title}</h2>
              <div>
                <button
                  aria-label="Bookmark discussion"
                  aria-pressed={post.bookmarked}
                  disabled={busy}
                  onClick={async () => {
                    if (!user) {
                      signIn();
                      return;
                    }
                    setBusy(true);
                    try {
                      await api(`/competition-discussions/${id}/bookmark`, {
                        method: 'PUT',
                        body: JSON.stringify({ enabled: !post.bookmarked }),
                      });
                      setPost({ ...post, bookmarked: !post.bookmarked });
                    } catch (e) {
                      setError((e as Error).message);
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  <Bookmark size={18} />
                </button>
                {post.can_pin && (
                  <button
                    aria-label={post.pinned ? 'Unpin discussion' : 'Pin discussion'}
                    disabled={busy}
                    onClick={async () => {
                      setBusy(true);
                      try {
                        await api(`/competition-discussions/${id}/pin`, {
                          method: 'PUT',
                          body: JSON.stringify({ enabled: !post.pinned }),
                        });
                        setPost({ ...post, pinned: !post.pinned });
                      } catch (e) {
                        setError((e as Error).message);
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    <Pin size={18} />
                  </button>
                )}
              </div>
            </header>
            <div className="discussion-author">
              <DiscussionAvatar username={post.owner} />
              <small>
                {post.owner} · {new Date(post.created_at).toLocaleString()}
                {post.pinned ? ' · Pinned' : ''}
              </small>
            </div>
            <Markdown>{post.body}</Markdown>
            <Engagement
              kind="competition-post"
              id={post.id}
              user={user}
              signIn={signIn}
              allowReply={false}
            />
          </article>
          <section className="discussion-comments" aria-label="Discussion comments">
            <h3>Comments</h3>
            {user ? (
              <form
                onSubmit={async (event) => {
                  event.preventDefault();
                  if (busy || uploading || !body.trim()) return;
                  setBusy(true);
                  setError('');
                  try {
                    const comment = await api<Comment>(`/competition-discussions/${id}/comments`, {
                      method: 'POST',
                      body: JSON.stringify({ body }),
                    });
                    setComments((old) => [...old, comment]);
                    setBody('');
                  } catch (e) {
                    setError((e as Error).message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <h3>Post a comment</h3>
                <DiscussionEditor
                  label="Comment message"
                  value={body}
                  onChange={setBody}
                  competitionId={competitionId}
                  limit={10000}
                  disabled={busy}
                  onUploadingChange={setUploading}
                />
                <button className="button" disabled={busy || uploading || !body.trim()}>
                  {busy ? 'Posting…' : 'Post comment'}
                </button>
              </form>
            ) : (
              <button className="button secondary" onClick={signIn}>
                Sign in to comment
              </button>
            )}
            {comments.map((comment) => (
              <article className="discussion-comment" key={comment.id}>
                <header>
                  <DiscussionAvatar username={comment.username} />
                  <strong>{comment.username}</strong>
                  <small>{new Date(comment.created_at).toLocaleString()}</small>
                  {user?.id === comment.owner_id && (
                    <button
                      aria-label={`Delete comment by ${comment.username}`}
                      disabled={busy}
                      onClick={async () => {
                        setBusy(true);
                        try {
                          await api(`/engagement/competition-post/${id}/replies/${comment.id}`, {
                            method: 'DELETE',
                          });
                          setComments((old) => old.filter((row) => row.id !== comment.id));
                        } catch (e) {
                          setError((e as Error).message);
                        } finally {
                          setBusy(false);
                        }
                      }}
                    >
                      <Trash2 size={16} />
                    </button>
                  )}
                </header>
                <Markdown>{comment.body}</Markdown>
                <Engagement
                  kind="competition-comment"
                  id={comment.id}
                  competitionId={competitionId}
                  user={user}
                  signIn={signIn}
                />
              </article>
            ))}
            {!comments.length && <p>No comments yet. Be the first to join the conversation.</p>}
            {next && (
              <button
                className="button secondary"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    const result = await api<{ items: Comment[]; next_cursor: number | null }>(
                      `/competition-discussions/${id}/comments?after=${next}`,
                    );
                    setComments((old) =>
                      [
                        ...old,
                        ...result.items.filter((row) => !old.some((item) => item.id === row.id)),
                      ].sort((a, b) => a.id - b.id),
                    );
                    setNext(result.next_cursor);
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
        </>
      )}
      {!loading && !post && (
        <button className="button secondary" onClick={() => setRevision((v) => v + 1)}>
          Try again
        </button>
      )}
    </section>
  );
}
